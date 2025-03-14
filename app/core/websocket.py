from lib.pubsub import DumbBroadcaster, ChatRoomManager, CursorTrackingBroadcaster
from app.core.config import settings

dumb_broadcaster = DumbBroadcaster(settings.PUB_SUB_BACKEND_URL)
cursor_tracking_broadcaster = CursorTrackingBroadcaster(settings.PUB_SUB_BACKEND_URL)
chatroom_manager = ChatRoomManager(settings.PUB_SUB_BACKEND_URL)
