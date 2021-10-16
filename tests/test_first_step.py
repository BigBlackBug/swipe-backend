from typing import Dict

from requests import Response
from starlette.testclient import TestClient

from settings import settings


def test_get_me(client: TestClient,
                test_user_auth_headers: Dict[str, str]) -> None:
    response: Response = client.get(
        f"{settings.API_V1_PREFIX}/me", headers=test_user_auth_headers
    )
    assert response.status_code == 200
