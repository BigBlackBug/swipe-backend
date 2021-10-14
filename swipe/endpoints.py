from fastapi import APIRouter, Query

from settings import settings

router = APIRouter(prefix=f'{settings.API_V1_PREFIX}/swipe', tags=['swipe'])


@router.get('/')
async def hello_swipe(username: str = Query(None, )):
    return {"response": f'Hey, {username}. You suck'}
