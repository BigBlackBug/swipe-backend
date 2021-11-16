import asyncio
import heapq
import json
import logging
import time
from asyncio import StreamReader, StreamWriter
from typing import Optional
from uuid import UUID

from swipe.matchmaking.connections import MM2WSConnection
from swipe.matchmaking.schemas import Match, MMSettings
from swipe.matchmaking.services import MMUserService
from swipe.settings import settings
# keep SessionLocal import on top
from swipe.swipe_server.misc.database import SessionLocal
from swipe.swipe_server.users.models import IDList

logger = logging.getLogger(__name__)

CYCLE_LENGTH_SEC = 6


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
        return f'{self.user_id}, {self.edges}, processed:{self.processed}'


class Matchmaker:
    def __init__(self, user_service: MMUserService):
        self._user_service = user_service

        self._current_round_pool: dict[str, MMSettings] = {}
        self._next_round_pool: dict[str, MMSettings] = {}

        # self._next_round_heap: list[str] = []
        # a -> {b->{a:True, c:False}}, c->{b:False}}
        self._connection_graph: dict[str, Vertex] = {}

    def generate_matches(self) -> list[Match]:
        logger.info(
            f"Starting a matchmaking round with pool: {self._next_round_pool}")
        if len(self._next_round_pool) < 2:
            logger.info("Not enough users for matchmaking")
            # TODO send a signal about that? like no more users?
            return

        self._current_round_pool = self._next_round_pool
        # TODO might break because of concurrency?
        self._next_round_pool = {}

        current_round_heap = list(self._current_round_pool.keys())
        heapq.heapify(current_round_heap)

        # generate connectivity graph based on their filters
        for user_id, mm_settings in self._current_round_pool.items():
            # TODO increase age limit for next rounds if none were found
            connections: IDList = \
                self._user_service.find_user_ids(
                    user_id, mm_settings.age,
                    mm_settings.age_diff,
                    list(self._current_round_pool.keys()),
                    mm_settings.gender)
            logger.info(f"Found connections for {user_id}: {connections}")
            self.build_graph(user_id, connections)

        matches = []
        heap_size = len(current_round_heap)
        while heap_size:
            logger.info(f"current heap {current_round_heap}")
            # pick heap top (C)
            current_user = heapq.heappop(current_round_heap)
            heap_size -= 1

            logger.info(f"heap head: {current_user}")
            pair = self.find_match(current_user)
            if pair:
                self._connection_graph[pair[0]].processed = True
                self._connection_graph[pair[1]].processed = True
                matches.append(pair)

        for user_a, user_b in matches:
            logger.info(f"Removing {user_a}, {user_b} from MM pool")
            del self._current_round_pool[user_a]
            del self._current_round_pool[user_b]

            logger.info(f"Returning match {user_a}-{user_b}")
            yield user_a, user_b

    def remove_user(self, user_id: str):
        if user_id in self._current_round_pool:
            logger.info(
                f"Current users in MM: {self._current_round_pool}, removing {user_id}")
            del self._current_round_pool[user_id]

    def add_user(self, user_id: str, mm_settings: MMSettings):
        logger.info(f"Adding {user_id} to next round pool")
        self._next_round_pool[user_id] = mm_settings

    def build_graph(self, user_id: str, connections: list[UUID]):
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
        # put C to used
        # pick a random double connection for him (F)
        logger.info(f"Finding match for {user_id}")

        current_vertex = self._connection_graph[user_id]
        # TODO gotta go breadth first on priority queue
        # and find candidate with the most weight instead of iterating
        for potential_match, bidirectional in current_vertex.edges.items():
            logger.info(f"Checking {potential_match}")
            # if bidirectional -> got a match
            if bidirectional and \
                    not self._connection_graph[potential_match].processed:
                logger.info(f"{potential_match} is a match")
                # if such connection F exists
                # put F to 'used'
                # TODO set C,F weight to 0 for next round
                return user_id, potential_match

        logger.info(f"No matches found for {user_id}")
        # increase C weight for next round
        # increase C age diff
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
    # TODO read user identifier?
    loop.create_task(match_generator(writer, matchmaker))
    loop.create_task(user_event_handler(reader, matchmaker))


async def user_event_handler(reader: StreamReader, matchmaker: Matchmaker):
    logger.info("Starting user event reader")

    while True:
        event_data_raw = await reader.readline()
        if not event_data_raw:
            logger.info("Client died lol")
            break

        user_event = json.loads(event_data_raw)

        user_id = user_event['user_id']
        if user_event['operation'] == 'connect':
            matchmaker.add_user(
                user_id, MMSettings.parse_obj(user_event['settings']))
        elif user_event['operation'] == 'disconnect':
            matchmaker.remove_user(user_id)


async def match_generator(writer: StreamWriter, matchmaker: Matchmaker):
    logger.info("Starting match generator")

    ws_connection = MM2WSConnection(writer)
    while True:
        cycle_start = time.time()

        for user_a, user_b in matchmaker.generate_matches():
            await ws_connection.send_match(user_a, user_b)

        diff = int(cycle_start + CYCLE_LENGTH_SEC - time.time())
        logger.info(f"Seconds till the next cycle: {diff}")
        await asyncio.sleep(diff)
