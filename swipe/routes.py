from fastapi import APIRouter, Query

router = APIRouter(prefix='/swipe', tags=['swipe'])


@router.get('/')
async def hello_swipe(username: str = Query(None, )):
    return {"response": f'Hey, {username}. You suck'}
