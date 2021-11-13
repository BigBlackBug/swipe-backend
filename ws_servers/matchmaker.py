import os
import sys

# TODO WTF
sys.path.insert(1, os.path.join(sys.path[0], '..'))
import config

config.configure_logging()
import asyncio
import json
import logging
import random
import time
from asyncio import StreamReader, StreamWriter

from aiopipe import AioPipeReader, AioPipeWriter

from ws_servers.schemas import Match
from ws_servers.services import WSPipe

logger = logging.getLogger(__name__)
# TODO all connected users again, gotta be a set
mm_connected_users: list = []

CYCLE_LENGTH_SEC = 7


def main(reader_pipe: AioPipeReader, writer_pipe: AioPipeWriter):
    logger.info('Starting the matchmaking process')
    mm_loop = asyncio.new_event_loop()
    mm_loop.create_task(mm_user_event_handler(reader_pipe))
    mm_loop.create_task(mm_match_generator(writer_pipe))
    mm_loop.run_forever()


async def generate_matches() -> list[Match]:
    logger.info(f"generating matches from {mm_connected_users}")
    await asyncio.sleep(random.randint(1, 3))
    if len(mm_connected_users) < 2:
        return []
    # TODO a real Matchmaking huh
    return [tuple(random.sample(mm_connected_users, 2))]  # noqa


async def mm_user_event_handler(reader_pipe: AioPipeReader):
    logger.info("Starting user event reader")
    reader: StreamReader
    async with reader_pipe.open() as reader:
        while True:
            user_event_raw = await reader.readline()
            if not user_event_raw:
                logger.info("main process died wtf")
                break

            user_event = json.loads(user_event_raw)

            logger.info(f"Current users in MM: {mm_connected_users}, "
                        f"got new user event {user_event}")
            user_id = user_event['user_id']
            if user_event['operation'] == 'connect':
                logger.info(f"Adding {user_id} to MM pool")
                mm_connected_users.append(user_id)
            elif user_event['operation'] == 'disconnect':
                if user_id in mm_connected_users:
                    logger.info(f"Removing {user_id} from MM pool")
                    mm_connected_users.remove(user_id)


async def mm_match_generator(pusher_pipe: AioPipeWriter):
    writer: StreamWriter
    async with pusher_pipe.open() as writer:
        ws_pipe = WSPipe(writer)
        while True:
            cycle_start = time.time()
            # generate matches of tuples
            matches: list[Match] = await generate_matches()
            logger.info(f"Generated matches: {matches}")
            for user_a, user_b in matches:
                logger.info(f"Removing {user_a}, {user_b} from MM pool")
                mm_connected_users.remove(user_a)
                mm_connected_users.remove(user_b)

                logger.info(f"Sending match to ws handler")
                ws_pipe.send_match(user_a, user_b)

            diff = int(cycle_start + CYCLE_LENGTH_SEC - time.time())
            logger.info(f"Seconds till the next cycle: {diff}")
            await asyncio.sleep(diff)
