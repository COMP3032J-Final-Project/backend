from lib.pubsub import DumbBroadcaster, CursorTrackingBroadcaster, ProjectGeneralManager
from app.core.config import settings

dumb_broadcaster = DumbBroadcaster(settings.PUB_SUB_BACKEND_URL)
cursor_tracking_broadcaster = CursorTrackingBroadcaster(settings.PUB_SUB_BACKEND_URL)
project_general_manager = ProjectGeneralManager(settings.PUB_SUB_BACKEND_URL)
