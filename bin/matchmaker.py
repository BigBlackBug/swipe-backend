import os
import sys

# TODO WTF
sys.path.insert(1, os.path.join(sys.path[0], '..'))
import asyncio

from swipe.matchmaking import matchmaker

if __name__ == '__main__':
    asyncio.run(matchmaker.run_server())
