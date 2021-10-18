from requests import Response
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from settings import settings
from swipe.users import models, enums


def test_auth_new_user(client: TestClient) -> None:
    response: Response = client.post(
        f"{settings.API_V1_PREFIX}/auth", json={
            'auth_provider': 'google',
            'provider_token': 'supertoken',
            'provider_user_id': 'superid'
        }
    )
    assert response.status_code == 201
    assert response.json().get('access_token')
    assert response.json().get('user_id')


def test_auth_existing_user(client: TestClient, session: Session) -> None:
    auth_info = models.AuthInfo(auth_provider=enums.AuthProvider.SNAPCHAT,
                                provider_token='token',
                                provider_user_id='userid')
    user = models.User(auth_info=auth_info)
    session.add(user)
    session.commit()

    response: Response = client.post(
        f"{settings.API_V1_PREFIX}/auth", json={
            'auth_provider': 'snapchat',
            'provider_token': 'token',
            'provider_user_id': 'userid'
        }
    )
    assert response.status_code == 200
    assert response.json().get('access_token')
    assert response.json().get('user_id')
