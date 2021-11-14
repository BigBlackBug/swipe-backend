import os
import sys

# TODO WTF
sys.path.insert(1, os.path.join(sys.path[0], '..'))
from swipe.matchmaking import server as matchmaking_server

if __name__ == '__main__':
    matchmaking_server.start_server()
