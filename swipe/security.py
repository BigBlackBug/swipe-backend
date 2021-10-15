import logging

from fastapi import Depends, HTTPException, Security
from fastapi.security import APIKeyHeader
from jose import jwt
from jose.constants import ALGORITHMS
from pydantic import ValidationError
from starlette import status
from starlette.requests import Request

from settings import settings
from swipe.users import models, schemas
from swipe.users.services import UserService

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


def get_current_user(user_service: UserService = Depends(),
                     token: str = Depends(get_auth_token)) -> models.User:
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
    user = user_service.get_user(token_payload.user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="User not found")

    if user.auth_info.access_token != token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail='Token has been invalidated')

    logger.debug(f'{user.id} has successfully authenticated')
    return user
