import os
import sys

# TODO WTF
sys.path.insert(1, os.path.join(sys.path[0], '..'))
from swipe import config

config.configure_logging()
import asyncio

from swipe.matchmaking import matchmaker

if __name__ == '__main__':
    asyncio.run(matchmaker.run_server())
