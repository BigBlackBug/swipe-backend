import logging
from uuid import UUID

from fastapi import Depends, HTTPException, Security
from fastapi.security import APIKeyHeader
from jose import jwt
from jose.constants import ALGORITHMS
from pydantic import ValidationError
from starlette import status

from swipe.settings import settings
from swipe.swipe_server.users import schemas
from swipe.swipe_server.users.services import UserService

logger = logging.getLogger(__name__)

auth_header_dep = APIKeyHeader(
    name='Authorization', auto_error=True,
    description='Standard header with a Bearer token')


def get_auth_token(auth_header: str = Security(auth_header_dep)) -> str:
    scheme, _, token = auth_header.partition(' ')
    if scheme == auth_header:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail='Invalid Authorization header')
    if scheme.lower() != 'bearer':
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail='Invalid Authorization scheme')
    return token


def auth_user_id(user_service: UserService = Depends(),
                 token: str = Depends(get_auth_token)) -> UUID:
    try:
        payload = jwt.decode(
            token, settings.SWIPE_SECRET_KEY, algorithms=[ALGORITHMS.HS256, ]
        )
        token_payload = schemas.JWTPayload(**payload)
    except (jwt.JWTError, ValidationError) as e:
        logger.exception("Error validating token")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail='Error validating token',
        )

    auth_info = user_service.check_token(token_payload.user_id, token)
    if not auth_info:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail='No user found with provided token')

    return UUID(hex=token_payload.user_id)
