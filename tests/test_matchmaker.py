from pytest_mock import MockerFixture

from swipe.matchmaking.matchmaker import Matchmaker, Vertex
from swipe.matchmaking.schemas import MMSettings


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
    for user in connections.keys():
        # same weight for everyone, like it's the first round
        mm.add_user(user, MMSettings(age=0, current_weight=0))

    # TODO mock user_service but meh
    def _mock_build_graph():
        for user, vertices in connections.items():
            mm.add_to_graph(user, vertices)

    mm.build_graph = _mock_build_graph

    # 2 - build graph
    mm.build_graph()

    C: Vertex = mm.get_vertex('C')
    # bidir
    assert C.connects_to('F')
    assert not C.connects_to('D')

    D: Vertex = mm.get_vertex('D')
    # bidir
    assert D.connects_to('A')

    A: Vertex = mm.get_vertex('A')
    assert A.connects_to('D')
    assert A.connects_to('G')
    assert A.connects_to('F')
    assert not A.connects_to('C')

    B: Vertex = mm.get_vertex('B')
    assert not B.connects_to('D')

    F: Vertex = mm.get_vertex('F')
    assert F.connects_to('C')
    assert F.connects_to('A')

    G: Vertex = mm.get_vertex('G')
    assert G.connects_to('A')

    possible_matches = ['A', 'C']
    match = mm.find_match('F')
    assert match in possible_matches

    possible_matches = ['F']
    match = mm.find_match('C')
    assert match in possible_matches

    possible_matches = ['A']
    match = mm.find_match('D')
    assert match in possible_matches


def test_build_graph_weighted(mocker: MockerFixture):
    user_service_mock = mocker.patch(
        'swipe.matchmaking.matchmaker.MMUserService')
    mm = Matchmaker(user_service_mock)
    connections = {
        'A': ['D', 'G', 'F', 'C'],
        'B': ['D', 'C', 'E', 'F'],
        'C': ['F', 'D', 'G'],  #
        'D': ['A', 'B'],
        'E': ['G'],
        'F': ['C', 'A', 'D'],  #
        'G': ['A', 'D', 'B']
    }

    mm.add_user('E', MMSettings(age=0, current_weight=100))  #
    mm.add_user('F', MMSettings(age=0, current_weight=40))  #
    mm.add_user('C', MMSettings(age=0, current_weight=25))  #
    mm.add_user('A', MMSettings(age=0, current_weight=5))  #
    mm.add_user('D', MMSettings(age=0, current_weight=2))  #
    mm.add_user('B', MMSettings(age=0, current_weight=1))
    mm.add_user('G', MMSettings(age=0, current_weight=0))

    # TODO mock user_service but meh
    def _mock_build_graph():
        for user, vertices in connections.items():
            mm.add_to_graph(user, vertices)

    mm.build_graph = _mock_build_graph

    # 2 - build graph
    mm.build_graph()
    potential_matches = ['D', 'G', 'F']
    A: Vertex = mm.get_vertex('A')
    assert A.connects_to('D')
    assert A.connects_to('G')
    assert A.connects_to('F')
    assert not A.connects_to('C')

    potential_matches = ['D']
    B: Vertex = mm.get_vertex('B')
    assert B.connects_to('D')

    potential_matches = ['F']
    C: Vertex = mm.get_vertex('C')
    assert C.connects_to('F')

    potential_matches = ['A', 'B']
    D: Vertex = mm.get_vertex('D')
    assert D.connects_to('A')
    assert D.connects_to('B')

    E: Vertex = mm.get_vertex('E')

    F: Vertex = mm.get_vertex('F')
    assert F.connects_to('C')
    assert F.connects_to('A')

    potential_matches = ['A']
    G: Vertex = mm.get_vertex('G')
    assert F.connects_to('A')


def test_full_matchmaking(mocker: MockerFixture):
    user_service_mock = mocker.patch(
        'swipe.matchmaking.matchmaker.MMUserService')
    mm = Matchmaker(user_service_mock)
    connections = {
        'A': ['D', 'G', 'F', 'C'],
        'B': ['D', 'C', 'E', 'F'],
        'C': ['F', 'D', 'G'],
        'D': ['A', 'B'],
        'E': ['G'],
        'F': ['C', 'A', 'D'],
        'G': ['A', 'D', 'B']
    }

    # 1- populate matchmaking pool
    mm.add_user('E', MMSettings(age=0, current_weight=100))
    mm.add_user('F', MMSettings(age=0, current_weight=40))
    mm.add_user('C', MMSettings(age=0, current_weight=25))
    mm.add_user('A', MMSettings(age=0, current_weight=5))
    mm.add_user('D', MMSettings(age=0, current_weight=2))
    mm.add_user('B', MMSettings(age=0, current_weight=1))
    mm.add_user('G', MMSettings(age=0, current_weight=0))

    # TODO mock user_service but meh
    def _mock_build_graph():
        for user, vertices in connections.items():
            mm.add_to_graph(user, vertices)

    mm.build_graph = _mock_build_graph

    # 2 - build graph
    mm.build_graph()

    # check how it's built
    # 'D', 'G', 'F'
    A: Vertex = mm.get_vertex('A')
    assert A.connects_to('D')
    assert A.connects_to('G')
    assert A.connects_to('F')
    assert not A.connects_to('C')

    # 'D'
    B: Vertex = mm.get_vertex('B')
    assert B.connects_to('D')

    # 'F'
    C: Vertex = mm.get_vertex('C')
    assert C.connects_to('F')

    # A, B
    D: Vertex = mm.get_vertex('D')
    assert D.connects_to('A')
    assert D.connects_to('B')

    E: Vertex = mm.get_vertex('E')

    # C, A
    F: Vertex = mm.get_vertex('F')
    assert F.connects_to('C')
    assert F.connects_to('A')

    # A
    G: Vertex = mm.get_vertex('G')
    assert F.connects_to('A')

    # 3 - run matchmaking
    mm.init_pools()
    # ----------------------------------------
    all_matches = list(mm.generate_matches())
    user_a, user_b = all_matches[0]
    assert user_a == 'F'
    assert user_b == 'C'

    user_a, user_b = all_matches[1]
    assert user_a == 'A'
    assert user_b == 'D'
