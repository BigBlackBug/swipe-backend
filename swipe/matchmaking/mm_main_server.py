import asyncio
import json
import logging
import multiprocessing as mp
import time
from asyncio import StreamReader, StreamWriter
from multiprocessing import Process

from aiopipe import aiopipe, AioPipeWriter, AioPipeReader

from swipe.matchmaking.matchmaker import MMSharedData, Matchmaker
from swipe.matchmaking.schemas import MMSettings
from swipe.matchmaking.services import MMUserService
from swipe.settings import settings
from swipe.swipe_server.misc.database import SessionLocal

logger = logging.getLogger('matchmaking.main_server')
user_event_logger = logging.getLogger('matchmaking.user_events')

MIN_ROUND_LENGTH_SECS = 5

manager = mp.Manager()
incoming_data = MMSharedData(
    incoming_users=manager.dict(),
    removed_users=manager.dict(),
    wait_list=manager.dict(),
    user_lock=manager.Lock())
mm_writer: AioPipeWriter
mm_reader: AioPipeReader
# pipe between matchmaker process and the matchmaker main server
mm_reader, mm_writer = aiopipe()


async def run_server():
    server = await asyncio.start_server(
        _request_handler, settings.MATCHMAKER_HOST, settings.MATCHMAKER_PORT)

    # writes to a shared memory
    global mm_writer
    with mm_writer.detach() as mm_writer:
        # generates matches
        proc = Process(target=match_generator, args=(mm_writer,))
        proc.start()

    async with server:
        await server.serve_forever()
    proc.join()


async def _request_handler(mm_server_reader: StreamReader,
                           mm_server_writer: StreamWriter):
    loop = asyncio.get_running_loop()
    # reads from the mm server and writes to shared incoming data
    loop.create_task(user_event_handler(mm_server_reader))
    # reads from the mm pipe and writes to the mm server
    loop.create_task(match_sender(mm_server_writer))


async def user_event_handler(reader: StreamReader):
    user_event_logger.info("Starting user event reader")

    while True:
        event_data_raw = await reader.readline()
        if not event_data_raw:
            # TODO kill matchmaker loop
            user_event_logger.exception("Matchmaking WS server died")
            break

        user_event = json.loads(event_data_raw)

        user_id = user_event['user_id']
        if user_event['operation'] == 'connect':
            mm_settings = MMSettings.parse_obj(user_event['settings'])

            user_event_logger.info(
                f"Connecting {user_id} to matchmaking, "
                f"settings: {mm_settings}")
            incoming_data.add_user(user_id, mm_settings)
        elif user_event['operation'] == 'reconnect':
            user_event_logger.info(f"{user_id} got a decline, "
                                   f"adding him to next round pool")
            incoming_data.add_user(user_id)
        elif user_event['operation'] == 'disconnect':
            user_event_logger.info(f"Removing {user_id} from matchmaking")
            incoming_data.remove_user(user_id, user_event['remove_settings'])


def match_generator(mm_ws_writer: AioPipeWriter):
    logger.info("Starting match generator")

    matchmaker = Matchmaker(incoming_data, MMUserService(SessionLocal()))
    loop = asyncio.new_event_loop()

    async def _send_matches(_mm_ws_writer):
        async with _mm_ws_writer.open() as _mm_ws_writer:
            while True:
                cycle_start = time.time()

                # TODO think of a more reliable delay between matches
                logger.info(
                    "--------------------------------------------------")
                try:
                    for user_a, user_b in matchmaker.run_matchmaking_round():
                        logger.info(f"Sending match '{user_a}', '{user_b}' "
                                    f"to ws handler")
                        _mm_ws_writer.write(json.dumps({
                            'match': [user_a, user_b]
                        }).encode('utf-8'))
                        _mm_ws_writer.write(b'\n')
                        await _mm_ws_writer.drain()
                except:
                    logger.exception("Error during a matchmaking round")

                time_taken = time.time() - cycle_start
                sleep_time = MIN_ROUND_LENGTH_SECS - time_taken
                logger.info(
                    f"Round took {time_taken}s, "
                    f"time till the next cycle: {sleep_time}")
                await asyncio.sleep(sleep_time)

    loop.run_until_complete(_send_matches(mm_ws_writer))


async def match_sender(mm_server_writer: StreamWriter):
    logger.info("Starting match sender")

    global mm_reader
    async with mm_reader.open() as mm_reader:
        while True:
            msg = await mm_reader.readline()
            if not msg:
                # TODO Yep, no handler
                raise Exception("Matchmaking process is GONE")

            logger.info(f"Got match from matchmaker {msg}"
                        "sending to matchmaker server")

            mm_server_writer.write(msg)
            await mm_server_writer.drain()
