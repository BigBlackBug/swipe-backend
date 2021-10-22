import logging
from uuid import UUID

from fastapi import Depends, Body, APIRouter, HTTPException
from sqlalchemy.orm import Session
from starlette import status
from starlette.responses import Response

import swipe.dependencies
from swipe import security
from swipe.users import schemas
from swipe.users.models import User, IDList
from swipe.users.schemas import SortType
from swipe.users.services import UserService, RedisService

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    '/fetch',
    name='Fetch users according to the filter',
    response_model=list[schemas.UserOutSmall])
async def fetch_list_of_users(
        filter_params: schemas.FilterBody = Body(...),
        user_service: UserService = Depends(),
        redis_service: RedisService = Depends(),
        current_user: User = Depends(security.get_current_user)):
    """
    All fields are optional. Check default values.
    Important point - ignore_users is supposed to be used
    when fetching users for the popular list
    """
    # TODO how does sqlalchemy check equality?
    # I need to use a set here (linear searching takes a shit ton of time)
    # but I'm afraid adding __hash__ will fuck something up
    collected_user_ids: IDList = []
    ignored_user_ids = list(filter_params.ignore_users)
    age_difference = 0

    # FEED filtered by same country by default)
    # premium filtered by gender
    # premium filtered by location(whole country/my city)
    while len(collected_user_ids) <= filter_params.limit:
        # TODO cache similar requests?
        current_user_ids = user_service.find_user_ids(
            current_user, gender=filter_params.gender,
            age_difference=age_difference,
            city=filter_params.city,
            ignore_users=ignored_user_ids)

        if filter_params.online:
            current_user_ids = await redis_service.filter_online_users(
                current_user_ids)

        collected_user_ids.extend(current_user_ids)
        ignored_user_ids.extend(current_user_ids)

        if age_difference >= filter_params.max_age_difference:
            break

        # increasing search boundaries
        age_difference += 2

    collected_users = user_service.get_users(user_ids=collected_user_ids)
    if filter_params.sort == SortType.AGE_DIFFERENCE:
        # online - sort against age difference
        collected_users = sorted(
            collected_users,
            key=lambda user: \
                abs(current_user.date_of_birth - user.date_of_birth).days
        )
    else:
        # popular - sort against rating
        collected_users = sorted(collected_users,
                                 key=lambda user: user.rating, reverse=True)
    return [
        schemas.UserOutSmall.patched_from_orm(user)
        for user in collected_users[:filter_params.limit]
    ]


@router.post(
    '/{user_id}/block',
    name='Block a user',
    responses={
        204: {
            'description': 'User has been blocked',
        },
        404: {
            'description': 'User not found'
        },
        409: {
            'description': 'User is already blocked by you'
        }
    })
async def block_user(
        user_id: UUID,
        user_service: UserService = Depends(),
        db: Session = Depends(swipe.dependencies.db),
        current_user: User = Depends(security.get_current_user)):
    target_user = user_service.get_user(user_id)
    if not target_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail='Not found')

    current_user.block_user(target_user)
    db.commit()

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    '/{user_id}',
    name='Get a single user',
    response_model=schemas.UserOut)
async def fetch_user(
        user_id: UUID,
        user_service: UserService = Depends(),
        current_user: User = Depends(security.get_current_user)):
    user = user_service.get_user(user_id)
    user_out: schemas.UserOut = schemas.UserOut.patched_from_orm(user)
    return user_out
