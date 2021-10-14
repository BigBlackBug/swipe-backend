import logging
from uuid import UUID

from fastapi import Depends, HTTPException
from jose import jwt
from jose.constants import ALGORITHMS
from pydantic import ValidationError
from starlette import status
from starlette.requests import Request

from settings import settings
from swipe.users import models, schemas
from swipe.users.services import UserService

logger = logging.getLogger(__name__)


def get_auth_token(request: Request) -> str:
    auth_header: str = request.headers.get('Authorization')
    if not auth_header:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail='No Authorization header found')
    scheme, _, token = auth_header.partition(' ')
    if scheme == auth_header:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail='Invalid Authorization header')
    if scheme.lower() != 'bearer':
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail='Invalid Authorization scheme')
    return token


def get_current_user(user_service: UserService = Depends(),
                     token: str = Depends(get_auth_token)
                     ) -> models.User:
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[ALGORITHMS.HS256, ]
        )
        token_payload = schemas.JWTPayload(**payload)
    except (jwt.JWTError, ValidationError) as e:
        logger.exception("Could not validate token")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail='Could not validate token',
        )
    user = user_service.get_user(token_payload.user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # TODO payload.provider_token is most likely temporary
    if token_payload.provider_token != user.auth_info.payload['provider_token']:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail='Invalid token, user_ids on the auth provider do not match')
    logger.debug(f'{user.id} has successfully authorized')
    return user


def create_access_token(payload: schemas.CreateUserIn,
                        user_id: UUID) -> str:
    encoded_jwt = jwt.encode(
        schemas.JWTPayload(**payload.dict(), user_id=user_id).dict(),
        settings.SECRET_KEY,
        algorithm=ALGORITHMS.HS256)
    return encoded_jwt
