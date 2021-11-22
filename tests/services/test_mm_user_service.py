from sqlalchemy.orm import Session

from swipe.matchmaking.services import MMUserService
from swipe.swipe_server.misc.randomizer import RandomEntityGenerator
from swipe.swipe_server.users.models import User


def test_update_blacklist(session: Session, default_user: User,
                          randomizer: RandomEntityGenerator):
    user_1 = randomizer.generate_random_user()
    user_service = MMUserService(session)
    user_service.update_blacklist(
        blocker_id=str(default_user.id), blocked_user_id=str(user_1.id))

    session.refresh(user_1)
    session.refresh(default_user)

    assert user_1 in default_user.blacklist
    assert default_user in user_1.blocked_by
