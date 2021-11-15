import asyncio
import json
import logging
import random
import time
from asyncio import StreamReader, StreamWriter

from swipe.matchmaking.connections import MMServerConnection
from swipe.matchmaking.schemas import Match
from swipe.settings import settings

logger = logging.getLogger(__name__)
# TODO all connected users again, gotta be a set
matchmaking_pool: list = []

CYCLE_LENGTH_SEC = 7


async def run_server():
    server = await asyncio.start_server(
        request_handler, settings.MATCHMAKER_HOST, settings.MATCHMAKER_PORT)
    logger.info(f'Starting the matchmaker server')
    async with server:
        await server.serve_forever()


async def request_handler(reader: StreamReader, writer: StreamWriter):
    loop = asyncio.get_running_loop()
    loop.create_task(match_generator(writer))
    loop.create_task(user_event_handler(reader))


async def generate_matches() -> list[Match]:
    logger.info(f"Generating matches from {matchmaking_pool}")
    await asyncio.sleep(random.randint(1, 3))
    if len(matchmaking_pool) < 2:
        return []
    # TODO a real Matchmaking huh
    return [tuple(random.sample(matchmaking_pool, 2))]  # noqa


async def user_event_handler(reader: StreamReader):
    logger.info("Starting user event reader")

    while True:
        event_data_raw = await reader.readline()
        if not event_data_raw:
            logger.info("Client died lol")
            break

        user_event = json.loads(event_data_raw)

        logger.info(f"Current users in MM: {matchmaking_pool}, "
                    f"got new user event {user_event}")
        user_id = user_event['user_id']
        if user_event['operation'] == 'connect':
            logger.info(f"Adding {user_id} to MM pool")
            matchmaking_pool.append(user_id)
        elif user_event['operation'] == 'disconnect':
            if user_id in matchmaking_pool:
                logger.info(f"Removing {user_id} from MM pool")
                matchmaking_pool.remove(user_id)


async def match_generator(writer: StreamWriter):
    logger.info("Starting match generator")

    mm_server = MMServerConnection(writer)
    while True:
        cycle_start = time.time()

        matches: list[Match] = await generate_matches()
        logger.info(f"Generated matches: {matches}")
        for user_a, user_b in matches:
            logger.info(f"Removing {user_a}, {user_b} from MM pool")
            matchmaking_pool.remove(user_a)
            matchmaking_pool.remove(user_b)

            logger.info(f"Sending match to ws handler")
            await mm_server.send_match(user_a, user_b)

        diff = int(cycle_start + CYCLE_LENGTH_SEC - time.time())
        logger.info(f"Seconds till the next cycle: {diff}")
        await asyncio.sleep(diff)
