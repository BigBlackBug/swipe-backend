import datetime

from sqlalchemy.orm import Session

from swipe.matchmaking.services import MMUserService
from swipe.swipe_server.misc.randomizer import RandomEntityGenerator


def test_fetch(randomizer: RandomEntityGenerator, session: Session):
    default_user = randomizer.generate_random_user()
    default_user.date_of_birth = datetime.date.today().replace(year=2000)

    user_chat_1 = randomizer.generate_random_user()
    user_chat_1.date_of_birth = datetime.date.today().replace(year=2000)
    user_chat_2 = randomizer.generate_random_user()
    user_chat_2.date_of_birth = datetime.date.today().replace(year=2000)

    user_no_chat_3 = randomizer.generate_random_user()
    user_no_chat_3.date_of_birth = datetime.date.today().replace(year=2000)
    user_no_chat_4 = randomizer.generate_random_user()
    user_no_chat_4.date_of_birth = datetime.date.today().replace(year=2000)
    user_no_chat_5 = randomizer.generate_random_user()
    user_no_chat_5.date_of_birth = datetime.date.today().replace(year=2000)

    randomizer.generate_random_chat(default_user, user_chat_1)
    randomizer.generate_random_chat(default_user, user_chat_2)
    session.commit()

    user_service = MMUserService(session)
    result = user_service.find_user_ids(
        default_user.id, age=default_user.age,
        age_difference=10, online_users=[
            str(user_chat_1.id), str(user_chat_2.id),
            str(user_no_chat_3.id), str(user_no_chat_4.id),
            str(user_no_chat_5.id),
        ])
    assert set(result) == {str(user_no_chat_3.id), str(user_no_chat_4.id),
                           str(user_no_chat_5.id), }
