import heapq
import logging
import time
from dataclasses import dataclass
from typing import Optional, Iterator, Tuple

import requests

from swipe.matchmaking.schemas import Match, MMSettings, MMRoundData
from swipe.matchmaking.services import MMUserService
from swipe.settings import settings
from swipe.swipe_server.misc.database import SessionLocal
from swipe.swipe_server.users.enums import Gender
from swipe.swipe_server.users.models import IDList

logger = logging.getLogger('matchmaker')


class Vertex:
    def __init__(self, user_id: str, mm_settings: MMSettings):
        # current settings
        self.mm_settings = mm_settings
        self.user_id = user_id
        # used during current round in the generate_matches
        self.processed = False
        # got a match previous round in call or waiting for accept
        # skipping this round
        self.matched = False
        # skipping this round
        self.waiting = False
        # user_id -> bidirectional T|F
        self.edges: dict[str, bool] = {}

    def connect(self, user_id: str, bidirectional: bool = False):
        self.edges[user_id] = bidirectional

    def connects_to(self, user_id: str) -> Optional[bool]:
        return self.edges.get(user_id)

    def disconnect(self, user_id: str):
        self.edges.pop(user_id, None)

    def can_connect_to(self, other: 'Vertex'):
        """
        True if the other vertex matches the filtering criteria
        of the current vertex
        :param other:
        :return:
        """
        min_age = self.mm_settings.age - self.mm_settings.age_diff
        max_age = self.mm_settings.age + self.mm_settings.age_diff
        return min_age <= other.mm_settings.age <= max_age \
               and (self.mm_settings.gender_filter is None or
                    other.mm_settings.gender == self.mm_settings.gender_filter or
                    other.mm_settings.gender == Gender.ATTACK_HELICOPTER)

    def __repr__(self):
        return f'[{self.user_id}, {self.edges}, ' \
               f'matched: {self.matched}, waiting: {self.waiting}]\n'


@dataclass
class HeapItem:
    user_id: str
    weight: int

    def __lt__(self, other: 'HeapItem'):
        # yes they are fucking inverted, because I need a maxheap
        return self.weight > other.weight

    def __eq__(self, other: 'HeapItem'):
        return self.weight == other.weight

    def __repr__(self):
        return f"'{self.user_id}' weight: {self.weight}"


class Matchmaker:
    def __init__(self, user_service: MMUserService):
        self._user_service = user_service

        # users that got no candidates this round
        # for them I'm fetching new candidates from DB with increased age diff
        self._empty_candidates: set[str] = set()
        # current connection graph
        self._connection_graph: dict[str, Vertex] = {}

    def run_matchmaking_round(self, incoming_data: MMRoundData) \
            -> Iterator[Match]:
        # round starts
        logger.info(f"Round started, current graph\n"
                    f"{self._connection_graph}")

        logger.info(f"Clearing match flag on returning users\n"
                    f"{incoming_data.returning_users}")
        # clear match flag on returning users
        self._process_returning_users(incoming_data)

        # remove edges between returning declined users
        logger.info(f"Removing edges between declined users\n"
                    f"{incoming_data.decline_pairs}")
        self._process_decline_pairs(incoming_data)

        logger.info(f"Processing disconnected users\n"
                    f"{incoming_data.disconnected_users}")
        self._process_disconnected_users(incoming_data)

        # merge incoming user graph with the current graph
        # at least O(n^2) fuuuuuck
        logger.info(f"Merging new graph with current graph, incoming graph:\n"
                    f"{incoming_data.new_users}")
        self._merge_graphs(incoming_data)

        # ------------------new data processing done--------------------
        # fetch new candidates from DB for users who didn't have any matches
        # last round
        logger.info(f"Processing empty candidates\n"
                    f"{self._empty_candidates}")
        self._process_empty_candidates()

        # put new users to the heap
        # building a heap out of all
        # some users might have disconnected
        logger.info("Building current round heap")
        # excluding matched, because they haven't returned to lobby
        # excluding waiting, because they are skipping this round
        current_round_heap: list[HeapItem] = [
            HeapItem(user_id, graph_vertex.mm_settings.current_weight)
            for user_id, graph_vertex in self._connection_graph.items()
            if not graph_vertex.matched and not graph_vertex.waiting
        ]
        heapq.heapify(current_round_heap)

        logger.info("Generating")
        yield from self._generate_matches(current_round_heap)

        # before the end of the round, reset all processed flags
        logger.info("Resetting processed flags")
        self._reset_processed_flags()

    def _generate_matches(self, current_round_heap: list[HeapItem]) \
            -> Iterator[Match]:
        heap_size = len(current_round_heap)
        while heap_size:
            logger.info(f"Current heap {current_round_heap}")
            heap_size -= 1

            # pick heap top
            current_user = heapq.heappop(current_round_heap)
            current_user_id = current_user.user_id

            logger.info(f"Got heap head: {current_user}")
            current_vertex = self._connection_graph[current_user_id]

            # skipping processed vertices
            if current_vertex.processed:
                if current_vertex.matched:
                    logger.info(
                        f"{current_user_id} already got a match this round")
                    continue
                logger.info(f"{current_user_id} was already processed, "
                            f"but no match was found")
                continue

            # traverse connection graph
            logger.info(f"Looking for match for {current_user_id}")
            match_user_id: str = self.find_match(current_user_id)

            if match_user_id:
                logger.info(
                    f"Found match {match_user_id} for {current_user_id}")
                match_vertex = self._connection_graph[match_user_id]

                # set both weights to 0 for next round
                current_vertex.mm_settings.reset_weight()
                match_vertex.mm_settings.reset_weight()
                # mark as matched
                current_vertex.matched = True
                match_vertex.matched = True
                # mark both as processed, so they are skipped next iteration
                current_vertex.processed = True
                match_vertex.processed = True

                logger.info(f"marking {match_user_id} and {current_user_id} "
                            f"as processed and matched")
                yield current_user_id, match_user_id
            else:
                logger.info(f"No matches found for {current_user}, "
                            f"increasing weight, marking as processed")
                # add to empty so that we fetch more candidates next round
                self._empty_candidates.add(current_user_id)
                current_vertex.processed = True
                current_vertex.mm_settings.increase_weight()
                current_vertex.mm_settings.increase_age_diff()

    def find_match(self, user_id: str):
        current_vertex = self._connection_graph[user_id]

        # some of the edges might be gone by now
        logger.info(f"Filtering connections of {user_id}, \n"
                    f"before: {current_vertex.edges.items()}")
        potential_edges: list[Tuple[str, bool]] = list(filter(  # noqa
            lambda item: item[0] in self._connection_graph,
            current_vertex.edges.items()))
        logger.info(f"Filtering connections of {user_id}, \n"
                    f"after: {potential_edges}")
        # getting candidate with the most weight
        # TODO might be a good idea to maintain a maxheap, instead of sorting
        # on EACH iteration
        potential_edges.sort(
            key=lambda item: self._connection_graph[
                item[0]].mm_settings.current_weight,
            reverse=True)
        current_vertex.edges = dict(potential_edges)

        logger.info(f"Edges of {user_id}: {potential_edges}")
        for potential_match_id, _ in potential_edges:
            logger.info(f"Checking {potential_match_id}")
            vertex_matched = \
                self._connection_graph[potential_match_id].matched
            logger.info(
                f"{potential_match_id} already matched: {vertex_matched}")
            # if the edge is bidirectional -> we got a match
            if not vertex_matched and \
                    current_vertex.connects_to(potential_match_id):
                return potential_match_id

        return None

    def get_vertex(self, user_a):
        return self._connection_graph[user_a]

    def _connect_vertices(self, vertex_1: Vertex, vertex_2: Vertex):
        if vertex_1.can_connect_to(vertex_2):
            if vertex_2.can_connect_to(vertex_1):
                logger.info(f"{vertex_2.user_id} "
                            f"can connect both ways to {vertex_1.user_id}")
                vertex_1.connect(vertex_2.user_id, True)
                vertex_2.connect(vertex_1.user_id, True)
            else:
                logger.info(f"{vertex_1.user_id} "
                            f"can connect to {vertex_2.user_id}")
                vertex_1.connect(vertex_2.user_id, False)
        else:
            if vertex_2.can_connect_to(vertex_1):
                logger.info(f"{vertex_2.user_id} "
                            f"can connect to {vertex_1.user_id}")
                vertex_2.connect(vertex_1.user_id, False)

    def _process_disconnected_users(self, incoming_data: MMRoundData):
        for user_id in incoming_data.disconnected_users:
            logger.info(f"{user_id} disconnected during previous round, "
                        f"removing him from the old and new graphs")
            incoming_data.new_users.pop(user_id, None)
            if user_id in self._empty_candidates:
                self._empty_candidates.remove(user_id)

            if user_id not in self._connection_graph:
                # he might have connected during wait time and disconnected
                continue

            for connection_user_id \
                    in self._connection_graph[user_id].edges.keys():
                logger.info(f"Removing connection "
                            f"{connection_user_id} to {user_id}")
                self._connection_graph[connection_user_id] \
                    .disconnect(user_id)

            logger.info(f"Removing {user_id} from graph")
            del self._connection_graph[user_id]

    def _process_returning_users(self, incoming_data: MMRoundData):
        for user_id in incoming_data.returning_users:
            # enable edges
            logger.info(f"Enabling {user_id}")
            self._connection_graph[user_id].matched = False

    def _process_decline_pairs(self, incoming_data: MMRoundData):
        for user_a_id, user_b_id in incoming_data.decline_pairs:
            logger.info(f"Processing {user_a_id}, {user_b_id}")
            if settings.ENABLE_MATCHMAKING_BLACKLIST:
                # disconnect vertices
                self._connection_graph[user_a_id].disconnect(user_b_id)
                self._connection_graph[user_b_id].disconnect(user_a_id)

            # enable edges
            self._connection_graph[user_a_id].matched = False
            # self._connection_graph[user_a_id].waiting = True

            self._connection_graph[user_b_id].matched = False
            # self._connection_graph[user_b_id].waiting = True

    def _merge_graphs(self, incoming_data: MMRoundData):
        for incoming_user_id, incoming_vertex \
                in incoming_data.new_users.items():
            logger.info(
                f"Processing {incoming_user_id} -> {incoming_vertex.edges}")

            # TODO it's a workaround for users who have connected
            # without disconnecting. It shouldn't be possible anyway
            if incoming_user_id in self._connection_graph:
                logger.error(
                    f"HOW THE FUCK is {incoming_user_id} in the graph???")
                # self._connection_graph[incoming_user_id].matched = False
                continue

            logger.info(f"Removing incoming edges of {incoming_user_id} "
                        f"that are not in the graph. current edges\n"
                        f"{incoming_vertex.edges}")
            # user might have disconnected before, so he won't be in the
            # connection graph
            incoming_vertex.edges = set(filter(
                lambda edge: edge in self._connection_graph,
                incoming_vertex.edges))
            logger.info(f"Remaining edges of {incoming_user_id}\n"
                        f"{incoming_vertex.edges}")
            incoming_vertex = Vertex(
                user_id=incoming_vertex.user_id,
                mm_settings=incoming_vertex.mm_settings)
            # add to graph
            for user_id, graph_vertex in self._connection_graph.items():
                logger.info(f"Connecting {incoming_user_id} to {user_id}")
                self._connect_vertices(incoming_vertex, graph_vertex)

            logger.info(f"Adding {incoming_vertex.user_id} to graph")
            self._connection_graph[incoming_user_id] = incoming_vertex

        # logger.info("Clearing incoming users")
        # self._shared_data.new_users.clear()
        logger.info(f"Graphs merged, current graph\n"
                    f"{self._connection_graph.values()}")

    def _process_empty_candidates(self):
        while self._empty_candidates:
            user_id: str = self._empty_candidates.pop()
            vertex = self._connection_graph.get(user_id, None)
            if not vertex:
                # user could have been removed from the graph
                # because he disconnected
                # but this should not be possible, as I'm removing disconnected
                # users from the empty candidates set before that
                logger.info(f"{user_id} is not in the graph anymore, skipping")
                continue

            connections: IDList = \
                self._user_service.find_user_ids(
                    user_id,
                    age=vertex.mm_settings.age,
                    online_users=self._connection_graph.keys(),
                    age_difference=vertex.mm_settings.age_diff,
                    gender=vertex.mm_settings.gender)

            logger.info(f"New connections for {user_id}: {connections}")
            for connection_user_id in connections:
                connection_user_id = str(connection_user_id)
                # new fetched user already in graph
                # otherwise he's not in matchmaking -> not adding
                if reverse_vertex := self._connection_graph.get(
                        connection_user_id):
                    logger.info(f"Connecting {reverse_vertex.user_id} "
                                f"to {vertex.user_id}")
                    self._connect_vertices(reverse_vertex, vertex)

    def _reset_processed_flags(self):
        for user_id, vertex in self._connection_graph.items():
            if vertex.processed:
                # reset all processed flags
                vertex.processed = False
            elif vertex.waiting:
                # available for next round
                vertex.waiting = False


def start_matchmaker(round_length_secs: int = 5):
    logger.info("Starting matchmaker")
    bar = "-" * 100
    matchmaker = Matchmaker(MMUserService(SessionLocal()))
    while True:
        cycle_start = time.time()

        logger.info(bar)
        try:
            logger.info("Fetching new data from matchmaker server")
            response = requests.get(
                f'{settings.MATCHMAKING_SERVER_HOST}/new_round_data',
                timeout=2)
            json_data = response.json()

            incoming_data = MMRoundData.parse_obj(json_data)
            logger.info(f"New round data\n"
                        f"{incoming_data.repr_matchmaking()}")

            for user_a, user_b \
                    in matchmaker.run_matchmaking_round(incoming_data):
                logger.info(f"Sending match {user_a}, {user_b}")
                requests.post(
                    f'{settings.MATCHMAKING_SERVER_HOST}/send_match',
                    json={
                        'match': [user_a, user_b]
                    })
        except:
            logger.exception("Error during a matchmaking round")

        time_taken = time.time() - cycle_start
        sleep_time = round_length_secs - time_taken
        logger.info(
            f"Round took {time_taken}s, "
            f"time till the next cycle: {sleep_time}")
        time.sleep(max(0.0, sleep_time))
