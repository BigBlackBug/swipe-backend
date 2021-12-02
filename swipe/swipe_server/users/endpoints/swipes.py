import logging
import time
from datetime import datetime
from uuid import UUID

from fastapi import Depends, Body, HTTPException, APIRouter
from starlette import status
from starlette.responses import Response

from swipe.settings import constants
from swipe.swipe_server.misc import security
from swipe.swipe_server.users.redis_services import RedisSwipeReaperService
from swipe.swipe_server.users.services import UserService

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    '',
    name='Add swipes',
    status_code=status.HTTP_201_CREATED)
async def add_swipes(
        swipes: int = Body(...),
        reason: str = Body(...),
        user_id: UUID = Depends(security.auth_user_id),
        user_service: UserService = Depends(UserService)
):
    raise HTTPException(
        status_code=status.HTTP_418_IM_A_TEAPOT,
        detail='Not implemented YET'
    )
    # user_service.add_swipes(user_id, swipes)
    # logger.info(f'{swipes} swipes have been added. Reason {reason}')
    # return Response(status_code=status.HTTP_201_CREATED)


@router.get(
    '/status',
    name='Return timestamp when free swipes can be reaped',
    responses={
        200: {
            'description': 'null in case the swipes can be reaped right now',
            "content": {
                "application/json": {
                    "example": {
                        "reap_timestamp": '2021-10-02T15:57:44'
                    }
                }
            },
        }
    })
async def get_free_swipe_status(
        user_id: UUID = Depends(security.auth_user_id),
        redis_swipe: RedisSwipeReaperService = Depends()):
    reap_timestamp = await redis_swipe.get_swipe_reap_timestamp(user_id)
    return {
        'reap_timestamp': reap_timestamp
    }


@router.post(
    '/reap',
    name='Reap free swipes',
    responses={
        409: {
            'description': 'Free swipes are not available at the moment'
        },
        200: {
            'description': 'Returns the current amount of swipes and the '
                           'timestamp when new swipes can be reaped',
            "content": {
                "application/json": {
                    "example": {
                        "swipes": "100500",
                        "reap_timestamp": 1500
                    }
                }
            },
        }
    })
async def get_free_swipes(
        user_id: UUID = Depends(security.auth_user_id),
        user_service: UserService = Depends(UserService),
        redis_swipe: RedisSwipeReaperService = Depends()):
    reap_timestamp: datetime = \
        await redis_swipe.get_swipe_reap_timestamp(user_id)

    if reap_timestamp:
        diff = int(reap_timestamp.timestamp() - time.time())
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Free swipes will be available "
                   f"in {diff} seconds")

    new_swipes = user_service.add_swipes(
        user_id, constants.FREE_SWIPES_PER_TIME_PERIOD)
    reap_timestamp: datetime = \
        await redis_swipe.reset_swipe_reap_timestamp(user_id)

    return {
        'swipes': new_swipes,
        'reap_timestamp': reap_timestamp.isoformat()
    }
