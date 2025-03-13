from lib.pubsub import CRDTManager, ChatRoomManager
from app.core.config import settings

crdt_manager = CRDTManager(settings.PUB_SUB_BACKEND_URL)
chatroom_manager = ChatRoomManager(settings.PUB_SUB_BACKEND_URL)
