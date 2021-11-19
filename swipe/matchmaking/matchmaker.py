import heapq
import logging
import threading
from dataclasses import dataclass
from typing import Optional, Iterator
from uuid import UUID

from swipe.matchmaking.schemas import Match, MMSettings
from swipe.matchmaking.services import MMUserService
from swipe.swipe_server.users.models import IDList

logger = logging.getLogger('matchmaker')


class Vertex:
    def __init__(self, user_id):
        self.user_id = user_id
        self.processed = False
        self.edges: dict[str, bool] = {}

    def connect(self, user_id: str, bidirectional: bool = False):
        self.edges[user_id] = bidirectional

    def connects_to(self, user_id: str) -> Optional[bool]:
        return self.edges.get(user_id)

    def __repr__(self):
        return f'{self.user_id}, {self.edges}, processed: {self.processed}'


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


class MMSharedData:
    def __init__(self, incoming_users: dict[str, Optional[MMSettings]],
                 removed_users: dict[str, bool],
                 wait_list: list[str],
                 user_lock: threading.Lock):
        self.incoming_users = incoming_users
        self.disconnected_users = removed_users
        self.wait_list = wait_list
        self.user_lock = user_lock

    def add_user(self, user_id: str, mm_settings: Optional[MMSettings] = None):
        """
        Adds a user to the next round pool.
        If `mm_settings` is None, he's a returning user
        """
        with self.user_lock:
            logger.info(
                f"Adding {user_id} to next round pool, "
                f"new settings: {mm_settings}")
            if user_id in self.disconnected_users:
                logger.info(f"{user_id} is back before the round ended, "
                            f"okay, let's make him skip one round")
                self.wait_list.append(user_id)
            else:
                self.incoming_users[user_id] = mm_settings

        logger.info(f"All incoming users: {self.incoming_users}, "
                    f"skipping a round: {self.wait_list}")

    def remove_user(self, user_id: str, remove_settings: bool):
        """
        Called when the user disconnects from the MM server, meaning
        he either accepted a match or gone from the lobby
        """
        logger.info(f"Adding {user_id} to disconnected "
                    f"and removing from wait list")
        with self.user_lock:
            self.disconnected_users[user_id] = remove_settings
            if user_id in self.wait_list:
                # TODO make it a dict
                self.wait_list.remove(user_id)


class Matchmaker:
    def __init__(self, incoming_data: MMSharedData,
                 user_service: MMUserService):
        self._user_service = user_service

        self.incoming_data = incoming_data
        # stores settings for users who haven't found a match yet
        # item removed when a match is found and accepted
        self._mm_settings: dict[str, MMSettings] = {}

        self._current_round_pool: set[str] = set()

        # a -> {b->{a:True, c:False}}, c->{b:False}}
        self._connection_graph: dict[str, Vertex] = {}

    def run_matchmaking_round(self) -> Iterator[Match]:
        logger.info("Round started")
        with self.incoming_data.user_lock:
            self.init_pools()

        if len(self._current_round_pool) < 2:
            with self.incoming_data.user_lock:
                logger.info(
                    f"Not enough users for matchmaking in current pool "
                    f"{self._current_round_pool} "
                    "moving all to the next pool")
                for user_id in self._current_round_pool:
                    self.incoming_data.incoming_users[user_id] \
                        = self._mm_settings[user_id]

                logger.info(f"Flushing wait_list {self.incoming_data.wait_list}")
                for user_id in self.incoming_data.wait_list:
                    self.incoming_data.incoming_users[user_id] \
                        = self._mm_settings[user_id]
                self.incoming_data.wait_list[:] = []

                logger.info(f"Next round pool "
                            f"{self.incoming_data.incoming_users}")
            # TODO send a signal to clients about that? like no more users?
            return

        # generate connectivity graph based on their filters
        self.build_graph()

        yield from self.generate_matches()

        with self.incoming_data.user_lock:
            logger.info(f"Flushing wait_list {self.incoming_data.wait_list}")
            for user_id in self.incoming_data.wait_list:
                self.incoming_data.incoming_users[user_id] \
                    = self._mm_settings[user_id]
            self.incoming_data.wait_list[:] = []

    def init_pools(self):
        logger.info(
            f"Initializing pools, \n"
            f"users in the next round pool: "
            f"{self.incoming_data.incoming_users}, \n"
            f"disconnected users {self.incoming_data.disconnected_users}, \n"
            f"settings {self._mm_settings},\n"
            f"wait list {self.incoming_data.wait_list}")

        self._current_round_pool = set()
        for user, mm_settings in self.incoming_data.incoming_users.items():
            # True if the user is gone for good and I should remove his settings
            user_removed = self.incoming_data.disconnected_users.get(user)
            if user_removed is None:
                # he's still here
                self._current_round_pool.add(user)
                if mm_settings:
                    # it's a new dude, so his settings are not stored
                    self._mm_settings[user] = mm_settings
            else:
                # user's gone for good
                if user_removed:
                    logger.info(
                        f"{user} has disconnected from the lobby, "
                        f"removing his settings, removing from wait list"
                        f"and excluding from the current pool")
                    if user in self.incoming_data.wait_list:
                        self.incoming_data.wait_list.remove(user)

                    self._mm_settings.pop(user, None)
                else:
                    logger.info(
                        f"{user} has received a match and has disconnected "
                        f"from matchmaking, "
                        f"not including him in the current pool")

        self.incoming_data.incoming_users.clear()
        self.incoming_data.disconnected_users.clear()

    def build_graph(self):
        logger.info(f"Building graph from "
                    f"current pool: {self._current_round_pool}")
        for user_id in self._current_round_pool:
            if user_id in self.incoming_data.disconnected_users:
                logger.info(f"Skipping {user_id} because he's gone "
                            f"from the current round")
                continue

            mm_settings = self._mm_settings[user_id]
            # TODO cache the fuck out of it, including queries and blacklists
            logger.info(f"Fetching connections for {user_id}, "
                        f"settings:{mm_settings}")
            connections: IDList = \
                self._user_service.find_user_ids(
                    user_id,
                    age=mm_settings.age,
                    age_difference=mm_settings.age_diff,
                    online_users=self._current_round_pool,
                    gender=mm_settings.gender)

            if not connections:
                logger.info(f"No connections found for {user_id}, "
                            f"increasing age diff")
                # increasing age diff for next rounds if none were found
                mm_settings.increase_age_diff()
            else:
                logger.info(f"Found {len(connections)} connections "
                            f"for {user_id}: {connections}")

            self.add_to_graph(user_id, connections)

    def generate_matches(self) -> Iterator[Match]:
        # TODO do we need a copy?
        # building a heap out of all
        with self.incoming_data.user_lock:
            logger.info("Locking and building current round heap")
            current_round_heap: list[HeapItem] = [
                HeapItem(user, self._mm_settings[user].current_weight)
                for user in self._current_round_pool
                if user not in self.incoming_data.disconnected_users
            ]
            heapq.heapify(current_round_heap)
        logger.info("Lock released")

        heap_size = len(current_round_heap)
        while heap_size:
            logger.info(f"Current heap {current_round_heap}")
            # pick heap top
            current_user = heapq.heappop(current_round_heap)
            current_user_id = current_user.user_id
            heap_size -= 1

            logger.info(f"Got heap head: {current_user}")
            if self._connection_graph[current_user_id].processed:
                logger.info(f"{current_user_id} already got a match this round")
                continue

            # traverses connection graph
            match: str = self.find_match(current_user_id)
            if match:
                logger.info(f"Found match {match} for {current_user_id}")
                # set both weights to 0 for next round
                self._mm_settings[current_user_id].reset_weight()
                self._mm_settings[match].reset_weight()
                # mark both as processed, so they are skipped next iteration
                self._connection_graph[current_user_id].processed = True
                self._connection_graph[match].processed = True

                # remove both from next round
                logger.info(f"Adding {match} and {current_user_id} "
                            f"to disconnected")
                with self.incoming_data.user_lock:
                    self.incoming_data.disconnected_users[
                        current_user_id] = False
                    self.incoming_data.disconnected_users[match] = False
                yield current_user_id, match
            else:
                logger.info(f"No matches found for {current_user}, "
                            f"increasing weight, adding to next round pool")
                self.incoming_data.incoming_users[current_user_id] \
                    = self._mm_settings[current_user_id]

                self._mm_settings[current_user_id].increase_weight()

    def add_to_graph(self, user_id: str, connections: list[UUID]):
        vertex = Vertex(user_id)
        for connection_user_id in connections:
            # TODO stupid UUID
            connection_user_id = str(connection_user_id)
            if reverse_vertex := self._connection_graph.get(connection_user_id):
                if reverse_vertex.connects_to(user_id) is not None:
                    # make it bidirectional
                    vertex.connect(connection_user_id, True)
                    reverse_vertex.connect(user_id, True)
                else:
                    vertex.connect(connection_user_id)
            else:
                vertex.connect(connection_user_id)
        self._connection_graph[user_id] = vertex

    def find_match(self, user_id: str):
        logger.info(f"Looking for match for {user_id}")

        current_vertex = self._connection_graph[user_id]
        # getting candidate with the most weight
        potential_edges = sorted(
            current_vertex.edges.keys(),
            key=lambda x: self._mm_settings[x].current_weight,
            reverse=True)
        for potential_match_id in potential_edges:
            vertex_processed = \
                self._connection_graph[potential_match_id].processed
            logger.info(f"Checking {potential_match_id}, "
                        f"processed: {vertex_processed}")
            # if the edge is bidirectional -> we got a match
            if not vertex_processed and \
                    current_vertex.connects_to(potential_match_id):
                return potential_match_id

        return None

    def get_vertex(self, user_a):
        return self._connection_graph[user_a]
