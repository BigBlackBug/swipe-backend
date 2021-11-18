import asyncio
import heapq
import json
import logging
import threading
import time
from asyncio import StreamReader, StreamWriter
from dataclasses import dataclass
from typing import Optional, Generator, Iterator
from uuid import UUID

from swipe.matchmaking.connections import MM2WSConnection
from swipe.matchmaking.schemas import Match, MMSettings
from swipe.matchmaking.services import MMUserService
from swipe.settings import settings
from swipe.swipe_server.misc.database import SessionLocal
from swipe.swipe_server.users.models import IDList

logger = logging.getLogger(__name__)

MIN_ROUND_LENGTH_SECS = 5


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


class Matchmaker:
    def __init__(self, user_service: MMUserService):
        self._user_service = user_service

        # stores settings for users who haven't found a match yet
        # item removed when a match is found and accepted
        self._mm_settings: dict[str, MMSettings] = {}

        self._current_round_pool: set[str] = set()
        self._next_round_pool: set[str] = set()

        # a -> {b->{a:True, c:False}}, c->{b:False}}
        self._connection_graph: dict[str, Vertex] = {}
        # users that are gone during current round
        self._disconnected_users = set()

        self._user_lock = threading.Lock()

    def generate_matches(self) -> Iterator[Match]:
        logger.info("Locking and initializing pools")
        with self._user_lock:
            self.init_pools()

        if len(self._current_round_pool) < 2:
            logger.info(f"Not enough users for matchmaking in current pool"
                        f"{self._current_round_pool} "
                        "moving all to the next pool")
            self._next_round_pool.update(self._current_round_pool)
            logger.info(f"Next round pool {self._next_round_pool}")
            # TODO send a signal to clients about that? like no more users?
            return

        # generate connectivity graph based on their filters
        self.build_graph()

        yield from self.run_matchmaking_round()

        logger.info("Round finished, locking and clearing settings")
        # TODO when do I clear settings?
        # with self._user_lock:
        #     for user_id in self._disconnected_users:
        #         logger.info(f"Removing {user_id} from settings")
        #         del self._mm_settings[user_id]
        logger.info("Unlocking")

    def init_pools(self):
        logger.info(f"Initializing pools, users "
                    f"in the next round pool: {self._next_round_pool}")
        self._current_round_pool = set()
        # TODO are str passed by value?
        for user in self._next_round_pool:
            if user not in self._disconnected_users:
                self._current_round_pool.add(user)

        self._next_round_pool = set()
        self._disconnected_users = set()

    def build_graph(self):
        logger.info(f"Building graph from "
                    f"current pool: {self._current_round_pool}")
        for user_id in self._current_round_pool:
            if user_id in self._disconnected_users:
                logger.info(f"Skipping {user_id} because he's gone")
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

    def run_matchmaking_round(self) -> Iterator[Match]:
        # TODO do we need a copy?
        # building a heap out of all
        with self._user_lock:
            logger.info("Locking and building current round heap")
            current_round_heap: list[HeapItem] = [
                HeapItem(user, self._mm_settings[user].current_weight)
                for user in self._current_round_pool
                if user not in self._disconnected_users
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
                self._disconnected_users.add(current_user_id)
                self._disconnected_users.add(match)
                yield current_user_id, match
            else:
                logger.info(f"No matches found for {current_user}, "
                            f"increasing weight, adding to next round pool")
                self._mm_settings[current_user_id].increase_weight()

    def remove_user(self, user_id: str):
        """
        Called when the user disconnects from the MM server, meaning
        he either accepted a match or gone from the lobby
        """
        logger.info(f"User {user_id} disconnected from server")
        with self._user_lock:
            self._disconnected_users.add(user_id)

    def add_user(self, user_id: str, mm_settings: Optional[MMSettings] = None):
        """
        Adds a user to the next round pool.
        If `mm_settings` is None, he's a returning user
        """
        logger.info(f"Adding {user_id} to next round pool, {mm_settings}")
        with self._user_lock:
            self._next_round_pool.add(user_id)
            # they might have returned before this round ended, HOW?
            if user_id in self._disconnected_users:
                self._disconnected_users.remove(user_id)

            if mm_settings:
                self._mm_settings[user_id] = mm_settings

        logger.info(f"Next round pool {self._next_round_pool}")

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
            logger.info(f"Checking {potential_match_id}")
            # if the edge is bidirectional -> we got a match
            if current_vertex.connects_to(potential_match_id) and \
                    not self._connection_graph[potential_match_id].processed:
                return potential_match_id

        return None

    def get_vertex(self, user_a):
        return self._connection_graph[user_a]


async def run_server():
    server = await asyncio.start_server(
        _request_handler, settings.MATCHMAKER_HOST, settings.MATCHMAKER_PORT)
    async with server:
        await server.serve_forever()


async def _request_handler(reader: StreamReader, writer: StreamWriter):
    logger.info("Starting the matchmaker server")
    matchmaker = Matchmaker(MMUserService(SessionLocal()))
    loop = asyncio.get_running_loop()
    loop.create_task(match_generator(writer, matchmaker))
    loop.create_task(user_event_handler(reader, matchmaker))


async def user_event_handler(reader: StreamReader, matchmaker: Matchmaker):
    logger.info("Starting user event reader")

    while True:
        event_data_raw = await reader.readline()
        if not event_data_raw:
            # TODO kill matchmaker loop
            logger.exception("Matchmaking WS server died")
            break

        user_event = json.loads(event_data_raw)

        user_id = user_event['user_id']
        if user_event['operation'] == 'connect':
            matchmaker.add_user(
                user_id, MMSettings.parse_obj(user_event['settings']))
        elif user_event['operation'] == 'reconnect':
            matchmaker.add_user(user_id)
        elif user_event['operation'] == 'disconnect':
            matchmaker.remove_user(user_id)


async def match_generator(writer: StreamWriter, matchmaker: Matchmaker):
    logger.info("Starting match generator")

    ws_connection = MM2WSConnection(writer)
    while True:
        cycle_start = time.time()

        # TODO think of a more reliable delay between matches
        logger.info("--------------------------------------------------")
        for user_a, user_b in matchmaker.generate_matches():
            await ws_connection.send_match(user_a, user_b)

        diff = int(cycle_start + MIN_ROUND_LENGTH_SECS - time.time())
        logger.info(f"Seconds till the next cycle: {diff}")
        await asyncio.sleep(diff)
