from lib.pubsub import DumbBroadcaster, ChatRoomManager
from app.core.config import settings

dumb_broadcaster = DumbBroadcaster(settings.PUB_SUB_BACKEND_URL)
chatroom_manager = ChatRoomManager(settings.PUB_SUB_BACKEND_URL)
