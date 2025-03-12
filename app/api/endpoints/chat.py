import anyio
from fastapi import Request
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from broadcaster import Broadcast
from starlette.templating import Jinja2Templates

router = APIRouter()

# @router.get("/redis-test")
# async def redis_test(request: Request):
#     value = await request.app.state.redis.set('name', 'value')
#     return {"result": value}


# 使用内存后端，仅测试
broadcast = Broadcast("memory://")
templates = Jinja2Templates(directory="temp/templates")


async def chatroom_ws_receiver(websocket: WebSocket):
    """
    从 websocket 接收消息，并发布到 'chatroom' 频道
    """
    async for message in websocket.iter_text():
        await broadcast.publish(channel="chatroom", message=message)


async def chatroom_ws_sender(websocket: WebSocket):
    """
    订阅 'chatroom' 频道，并将收到的消息发送给 websocket 客户端
    """
    async with broadcast.subscribe(channel="chatroom") as subscriber:
        async for event in subscriber:
            await websocket.send_text(event.message)


@router.get("/", response_class=HTMLResponse, summary="聊天室首页")
async def homepage(request: Request):
    """
    返回聊天室首页页面
    """
    return templates.TemplateResponse("index.html", {"request": request})


@router.websocket("/ws")
async def chatroom_ws(websocket: WebSocket):
    """
    WebSocket 聊天室端点
    """
    await websocket.accept()
    try:
        async with anyio.create_task_group() as task_group:
            # 启动接收任务
            async def run_receiver() -> None:
                await chatroom_ws_receiver(websocket)
                task_group.cancel_scope.cancel()

            task_group.start_soon(run_receiver)
            # 发送消息
            await chatroom_ws_sender(websocket)
    except WebSocketDisconnect:
        pass
