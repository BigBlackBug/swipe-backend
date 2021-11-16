import datetime

import pytest
from pytest_mock import MockerFixture
from sqlalchemy.orm import Session

from swipe.matchmaking.matchmaker import Matchmaker, Vertex
from swipe.matchmaking.services import MMUserService
from swipe.swipe_server.misc.randomizer import RandomEntityGenerator
from swipe.swipe_server.users.enums import Gender
from swipe.swipe_server.users.models import User


def test_build_graph(mocker: MockerFixture):
    user_service_mock = mocker.patch(
        'swipe.matchmaking.matchmaker.MMUserService')
    mm = Matchmaker(user_service_mock)
    connections = {
        'C': ['F', 'D'],
        'A': ['D', 'G', 'F', 'C'],
        'D': ['A'],
        'B': ['D'],
        'F': ['C', 'A'],
        'G': ['A']
    }
    mm.build_graph('C', connections['C'])
    mm.build_graph('A', connections['A'])
    mm.build_graph('D', connections['D'])
    mm.build_graph('B', connections['B'])
    mm.build_graph('F', connections['F'])
    mm.build_graph('G', connections['G'])

    c_vertex: Vertex = mm.get_vertex('C')
    # bidir
    assert c_vertex.connects_to('F')
    assert not c_vertex.connects_to('D')

    d_vertex: Vertex = mm.get_vertex('D')
    # bidir
    assert d_vertex.connects_to('A')

    a_vertex: Vertex = mm.get_vertex('A')
    assert a_vertex.connects_to('D')
    assert a_vertex.connects_to('G')
    assert a_vertex.connects_to('F')
    assert not a_vertex.connects_to('C')

    b_vertex: Vertex = mm.get_vertex('B')
    assert not b_vertex.connects_to('D')

    f_vertex: Vertex = mm.get_vertex('F')
    assert f_vertex.connects_to('C')
    assert f_vertex.connects_to('A')

    g_vertex: Vertex = mm.get_vertex('G')
    assert g_vertex.connects_to('A')

    possible_matches = [('F', 'A'), ('F', 'C')]
    match = mm.find_match('F')
    assert match in possible_matches

    possible_matches = [('C', 'F')]
    match = mm.find_match('C')
    assert match in possible_matches

    possible_matches = [('D', 'A')]
    match = mm.find_match('D')
    assert match in possible_matches
