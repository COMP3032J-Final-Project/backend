"""
To create a new Connection Manager:
1. Create a new class that implements `WebsocketConnManager`
2. Implement the `_process_pubsub_message` method
3. Add it to app/core/websocket.py and update handlers in app/core/events.py
"""

import asyncio
import time
import uuid
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import orjson
import redis.asyncio as aioredis
from app.core.db import async_session
from app.models.project.chat import ChatMessageType, ChatMessageData
from app.models.project.websocket import (
    EventAction,
    EventScope,
    BroadcastMessage,
    BroadcastErrorMessage,
    BroadcastErrorData,
)
from app.repositories.project.chat import ChatDAO
from fastapi import WebSocket
from loguru import logger
import base64

from app.repositories.project.project import ProjectDAO
from app.repositories.user import UserDAO

from aspubsub import GeneralPurposePubSubManager, DumbBroadcaster

# logger.disable(__name__)


async def websocket_send_json(websocket: WebSocket, message: Dict):
    """Opinionated and more performant websocket.send_json"""
    serialized_message = orjson.dumps(message).decode()
    await websocket.send({"type": "websocket.send", "text": serialized_message})


class ConnectionNotInitialized(Exception):
    def __str__(self):
        return "Connection not initialized. Please initialize connection first!"


class PubSubInterface(ABC):
    @abstractmethod
    async def connect(self) -> None:
        """Connect to the pub/sub system"""
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect from the pub/sub system"""
        pass

    @abstractmethod
    async def publish(self, topic: str, message: str | bytes) -> None:
        """Publish a message to a topic"""
        pass

    @abstractmethod
    async def subscribe(self, topic: str) -> Any:
        """Subscribe to a topic"""
        pass

    @abstractmethod
    async def unsubscribe(self, topic: str) -> None:
        """Unsubscribe from a topic"""
        pass


class RedisPubSubManager(PubSubInterface):
    """
    Redis PubSub Manager that handles Redis pub/sub communication.

    Implemented as a singleton with separate Redis connections per subscription channel.
    Uses asyncio.Queue to bridge Redis messages to application code.
    """

    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(RedisPubSubManager, cls).__new__(cls)
        return cls._instance

    def __init__(
        self, redis_url: str, pool_size: Optional[int] = None, reconnect_attempts: int = 5, reconnect_delay: float = 1.0
    ):
        # Only initialize once due to singleton pattern
        if not hasattr(self, "redis_url"):
            self.redis_url = redis_url
            self.pool_size = pool_size
            self.reconnect_attempts = reconnect_attempts
            self.reconnect_delay = reconnect_delay
            self.conn = None  # Main Redis connection for publishing
            self.conn_pool = None  # Connection pool
            self.pubsubs = {}  # Channel -> PubSub instance (separate connections)
            self.listeners = {}  # Channel -> Task (background tasks listening for messages)
            self.message_queues = {}  # Channel -> Queue (async queues for message passing)
            self.callbacks = {}  # Channel -> Callback function (unused in current implementation)
            self.is_connected = False

    async def _get_redis_connection(self) -> Any:
        """Get a Redis connection from the pool"""
        if not self.conn_pool:
            # Create connection pool if it doesn't exist
            self.conn_pool = aioredis.ConnectionPool.from_url(
                self.redis_url, max_connections=self.pool_size, decode_responses=True
            )

        return aioredis.Redis(connection_pool=self.conn_pool)

    async def connect(self) -> None:
        """Connect to Redis with retry logic"""
        for attempt in range(self.reconnect_attempts):
            try:
                self.conn = await self._get_redis_connection()
                await self.conn.ping()
                self.is_connected = True
                logger.info(f"Connected to Redis at {self.redis_url} (attempt {attempt+1})")
                return
            except Exception as e:
                logger.error(f"Failed to connect to Redis (attempt {attempt+1}): {e}")
                if attempt < self.reconnect_attempts - 1:
                    await asyncio.sleep(self.reconnect_delay * (attempt + 1))  # Exponential backoff
                else:
                    raise

    async def _ensure_connected(self) -> None:
        """Ensure we have a valid Redis connection"""
        if not self.is_connected or not self.conn:
            await self.connect()
        else:
            try:
                # Check if connection is still alive
                await self.conn.ping()
            except Exception:
                logger.warning("Redis connection lost, reconnecting...")
                self.is_connected = False
                await self.connect()

    async def disconnect(self) -> None:
        # Cancel all listener tasks
        for channel, task in self.listeners.items():
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # Close all pubsub connections
        for _channel, pubsub in self.pubsubs.items():
            await pubsub.unsubscribe()
            await pubsub.aclose()

        # Close Redis connections
        if self.conn_pool:
            await self.conn_pool.aclose()

        # Clear all data structures
        self.pubsubs.clear()
        self.listeners.clear()
        self.message_queues.clear()
        self.callbacks.clear()

    async def publish(self, topic: str, message: str | bytes) -> None:
        if not self.conn:
            raise ConnectionNotInitialized()

        await self._ensure_connected()
        await self.conn.publish(topic, message)

    async def subscribe(self, topic: str) -> asyncio.Queue:
        """
        Subscribe to a topic and return a queue for receiving messages.

        Creates a dedicated Redis connection for this subscription and
        starts a background task to listen for messages.

        Returns:
            asyncio.Queue: Queue that will receive messages from this topic
        """
        if not self.conn:
            raise ConnectionNotInitialized()

        if topic in self.message_queues:
            return self.message_queues[topic]

        # Create a new queue for this topic
        message_queue = asyncio.Queue()
        self.message_queues[topic] = message_queue

        # Create a new Redis connection specifically for this subscription
        # This is necessary because Redis PubSub puts connections in a special state
        # where they can only be used for PubSub operations
        redis_conn = await aioredis.from_url(self.redis_url, decode_responses=True)
        pubsub = redis_conn.pubsub()
        self.pubsubs[topic] = pubsub

        # Subscribe to the topic
        await pubsub.subscribe(topic)

        # Start listener task
        listener_task = asyncio.create_task(self._pubsub_listener(topic, pubsub, message_queue))
        self.listeners[topic] = listener_task

        logger.debug(f"Subscribed to Redis topic: {topic}")

        return message_queue

    async def _pubsub_listener(self, topic: str, pubsub, queue: asyncio.Queue):
        """
        Listens for messages on a pubsub channel and puts them in the queue.

        Filters Redis message types to only process actual 'message' types.
        Message structure: {
            "type": "message",       # or "subscribe", "unsubscribe", etc.
            "channel": "channel-name",
            "data": "actual-message"
        }
        """
        try:
            logger.debug(f"Starting Redis PubSub listener for topic: {topic}")

            # First, signal that we're now subscribed
            await queue.put({"type": "subscribe", "channel": topic, "data": 1})

            # Then start listening for actual messages
            async for message in pubsub.listen():
                logger.debug(f"Received Redis PubSub message for topic {topic}: {message}")

                # Only process message types (skip subscribe/unsubscribe messages)
                message_type = message["type"]
                if message_type == "message":
                    # This is an actual message published by another client
                    await queue.put(message)
                elif message_type == "error":
                    logger.error(f"Error in Redis PubSub for topic {topic}: {message.get('data')}")
                else:
                    # Skip Redis protocol messages like 'subscribe' confirmations
                    logger.debug(f"Skipping Redis protocol message type: {message_type}")

        except asyncio.CancelledError:
            logger.debug(f"Redis PubSub listener for topic {topic} cancelled")
            raise
        except Exception as e:
            logger.error(f"Error in Redis PubSub listener for topic {topic}: {e}")
            # Put the error in the queue so subscribers can react
            await queue.put({"type": "error", "channel": topic, "data": str(e)})
            raise

    async def unsubscribe(self, topic: str) -> None:
        """Unsubscribe from a topic and clean up resources"""
        if topic in self.listeners:
            # Cancel the listener task
            task = self.listeners.pop(topic)
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        if topic in self.pubsubs:
            # Unsubscribe and close the pubsub connection
            pubsub = self.pubsubs.pop(topic)
            await pubsub.unsubscribe(topic)
            await pubsub.aclose()

        if topic in self.message_queues:
            # Remove the message queue
            self.message_queues.pop(topic)


class InMemoryPubSubManager(PubSubInterface):
    _instance = None
    """
    NOTE: NEVER use it in production!
    """

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(InMemoryPubSubManager, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        # Only initialize once due to singleton pattern
        if not hasattr(self, "initialized"):
            self.initialized = True
            self.topics: Dict[str, List[Tuple[float, str | bytes]]] = {}  # topic -> [(timestamp, message)]
            self.subscribers: Dict[str, List[asyncio.Queue]] = {}
            self.cleanup_task = None

    async def connect(self) -> None:
        logger.info("Connected to in-memory PubSub")
        # Start cleanup task

    async def disconnect(self) -> None:
        self.topics.clear()
        self.subscribers.clear()
        logger.info("Disconnected from in-memory PubSub")

    async def publish(self, topic: str, message: str | bytes) -> None:
        current_time = time.time()
        if isinstance(message, bytes):
            message = message.decode()

        if topic not in self.topics:
            self.topics[topic] = []

        self.topics[topic].append((current_time, message))

        if topic in self.subscribers:
            for queue in self.subscribers[topic]:
                await queue.put({"type": "message", "pattern": None, "channel": topic, "data": message})
                logger.debug(f"Published message to in-memory topic {topic}")

    async def subscribe(self, topic: str) -> asyncio.Queue:
        if topic not in self.subscribers:
            self.subscribers[topic] = []

        queue = asyncio.Queue()
        self.subscribers[topic].append(queue)

        # Simulate Redis subscribe message
        await queue.put({"type": "subscribe", "channel": topic, "data": 1})

        logger.debug(f"Subscribed to in-memory topic {topic}")
        return queue

    async def unsubscribe(self, topic: str) -> None:
        if topic in self.subscribers:
            self.subscribers.pop(topic)
            logger.debug(f"Unsubscribed from in-memory topic {topic}")


class WebsocketConnManager(ABC):
    """
    NOTE: rate limit is not tested.
    """

    def __init__(
        self,
        url: Optional[str] = None,
        batch_size: int = 10,
        batch_interval: float = 0.1,  # 10 fps
        rate_limit: Optional[int] = None,
        rate_period: float = 60.0,
    ):
        self.active_connections: Dict[str, WebSocket] = {}
        # Track which channels each client is subscribed to
        self.client_channels: Dict[str, Set[str]] = {}
        # Track active channel listeners
        self.channel_tasks: Dict[str, asyncio.Task] = {}

        # Message batching
        self.batch_size = batch_size
        self.batch_interval = batch_interval
        self.message_batches: Dict[str, List[Any]] = {}  # client_id -> messages
        self.batch_tasks: Dict[str, asyncio.Task] = {}

        # Rate limiting
        self.rate_limit = rate_limit  # Max messages per period
        self.rate_period = rate_period  # Period in seconds
        self.client_message_counts: Dict[str, List[float]] = {}  # client_id -> list of timestamps

        if url is None or url.startswith("memory://"):
            self.psm = InMemoryPubSubManager()
            logger.info("Using in-memory PubSub manager")
        elif url.startswith("redis://"):
            self.psm = RedisPubSubManager(url)
            logger.info(f"Using Redis PubSub manager with URL: {url}")
        else:
            raise ValueError(f"Unsupported URL scheme: {url}")

    async def initialize(self):
        """Initialize the connection to the PubSub backend"""
        await self.psm.connect()

    async def cleanup(self):
        """Clean up resources before shutdown"""
        await self.psm.disconnect()

    async def connect(self, client_id: str, websocket: WebSocket):
        """
        Accept a new WebSocket connection and store it
        Note before this function you must do `await websocket.accept()`
        """
        self.active_connections[client_id] = websocket
        logger.debug(f"Client {client_id} connected")

    async def disconnect(self, client_id: str, notification_channel: str | None = None):
        """Handle client disconnection"""
        if client_id in self.active_connections:
            await self._handle_disconnect(client_id, notification_channel)
            del self.active_connections[client_id]

            # Clean up batching resources
            if client_id in self.batch_tasks:
                task = self.batch_tasks.pop(client_id)
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

            if client_id in self.message_batches:
                del self.message_batches[client_id]

            # Clean up rate limiting data
            if client_id in self.client_message_counts:
                del self.client_message_counts[client_id]

            logger.debug(f"Client {client_id} disconnected")

    async def _handle_disconnect(self, client_id: str, notification_channel: str | None):
        """Default implementation for disconnect handling"""
        if notification_channel:
            await self.psm.publish(notification_channel, orjson.dumps({"action": "disconnect", "client_id": client_id}))

        # Remove client from all channels
        if client_id in self.client_channels:
            for channel in list(self.client_channels[client_id]):
                await self.unsubscribe_client_from_channel(client_id, channel)

            del self.client_channels[client_id]

    async def _subscribe_to_channel(self, channel: str) -> asyncio.Task:
        """Subscribe to a channel and start a listener task"""
        if channel in self.channel_tasks and not self.channel_tasks[channel].done():
            return self.channel_tasks[channel]

        subscriber = await self.psm.subscribe(channel)

        task = asyncio.create_task(self._listen_to_channel(channel, subscriber))

        self.channel_tasks[channel] = task
        return task

    async def subscribe_client_to_channel(self, client_id: str, channel: str):
        """Subscribe a client to a channel"""
        if client_id not in self.active_connections:
            raise Exception(f"Client {client_id} is not in active connections list.")

        if client_id not in self.client_channels:
            self.client_channels[client_id] = set()

        self.client_channels[client_id].add(channel)

        # Make sure we're listening to this channel
        await self._subscribe_to_channel(channel)

        # Notify others about new client
        await self.psm.publish(channel, orjson.dumps({"action": "join", "client_id": client_id}))

        logger.debug(f"Client {client_id} subscribed to channel {channel}")

    async def unsubscribe_client_from_channel(self, client_id: str, channel: str) -> None:
        """Unsubscribe a client from a channel"""
        if client_id in self.client_channels and channel in self.client_channels[client_id]:
            self.client_channels[client_id].remove(channel)

            # Notify others
            await self.psm.publish(channel, orjson.dumps({"action": "leave", "client_id": client_id}))

            logger.debug(f"Client {client_id} unsubscribed from channel {channel}")

            # Check if any clients are still subscribed to this channel
            has_subscribers = any(channel in self.client_channels[client_id] for client_id in self.client_channels)

            if not has_subscribers and channel in self.channel_tasks:
                logger.debug(f"No more clients subscribed to channel {channel}, stopping listener")
                self.channel_tasks[channel].cancel()
                await self.psm.unsubscribe(channel)
                del self.channel_tasks[channel]

    async def add_message_to_batch(self, client_id: str, message: Any):
        """Add a message to a client's batch"""
        if client_id not in self.message_batches:
            self.message_batches[client_id] = []
            # Start a batch processor for this client
            self.batch_tasks[client_id] = asyncio.create_task(self._process_batch(client_id))

        self.message_batches[client_id].append(message)

        # If we've reached batch size, process immediately
        if len(self.message_batches[client_id]) >= self.batch_size:
            if client_id in self.batch_tasks and not self.batch_tasks[client_id].done():
                self.batch_tasks[client_id].cancel()
            self.batch_tasks[client_id] = asyncio.create_task(self._process_batch(client_id))

    async def _process_batch(self, client_id: str):
        """Process a batch of messages for a client"""
        try:
            while True:
                # Wait for batch interval or until cancelled
                await asyncio.sleep(self.batch_interval)

                if client_id not in self.message_batches or not self.message_batches[client_id]:
                    continue

                if client_id not in self.active_connections:
                    # Client disconnected, clean up
                    if client_id in self.message_batches:
                        del self.message_batches[client_id]
                    return

                # Get the batch and clear it
                batch = self.message_batches[client_id]
                self.message_batches[client_id] = []

                if not batch:
                    continue

                # Send the batch as one message
                websocket = self.active_connections[client_id]
                await websocket_send_json(websocket, {"type": "batch", "messages": batch})

        except asyncio.CancelledError:
            # Process any remaining messages before exiting
            if client_id in self.message_batches and self.message_batches[client_id]:
                if client_id in self.active_connections:
                    batch = self.message_batches[client_id]
                    self.message_batches[client_id] = []

                    websocket = self.active_connections[client_id]
                    await websocket_send_json(websocket, {"type": "batch", "messages": batch})

        except Exception as e:
            logger.error(f"Error in batch processor for client {client_id}: {e}")

    async def _listen_to_channel(self, channel: str, subscriber: Any):
        """
        Listen for messages on a PubSub channel
        subscriber: pubsub subscriber (e.g. Redis pubsub)
        """
        try:
            while True:
                message = await subscriber.get()
                message_type = message["type"]
                logger.debug(f"Channel {channel} received message: {message}")

                # Skip errors and other non-message types
                if message_type == "error":
                    logger.error(f"Error in PubSub for channel {channel}: {message.get('data')}")
                    continue
                elif message_type != "message":
                    logger.debug(f"Skipping non-message type in channel listener: {message_type}")
                    continue

                # Process the message
                await self._process_pubsub_message(channel, message)
                subscriber.task_done()
        except asyncio.CancelledError:
            logger.debug(f"Channel listener for {channel} cancelled")
        except Exception as e:
            logger.error(f"Error in channel listener for {channel}: {e}")
            raise

    async def _check_rate_limit(self, client_id: str, current_time: float) -> bool:
        """
        Check if a client has exceeded their rate limit
        Returns True if client is within limits, False if rate limited
        """
        if not self.rate_limit:
            return True

        # Remove timestamps older than the rate period
        self.client_message_counts[client_id] = [
            t for t in self.client_message_counts[client_id] if t > current_time - self.rate_period
        ]

        return len(self.client_message_counts[client_id]) <= self.rate_limit

    async def send_message(self, channel: str, message: Any, client_id: str):
        """
        Handle a message from a client with rate limiting
        Note you you sent in `bytes` type, then the bytes is encoded using base64
        """
        if channel not in self.client_channels[client_id]:
            raise Exception(f"Client {client_id} is not in channel {channel}!")

        if self.rate_limit:
            current_time = time.time()

            if client_id not in self.client_message_counts:
                self.client_message_counts[client_id] = []

            # Add current timestamp
            self.client_message_counts[client_id].append(current_time)

            # Check rate limit
            if not await self._check_rate_limit(client_id, current_time):
                logger.warning(f"Rate limit exceeded for client {client_id}")
                # Optionally notify client they've been rate limited
                if client_id in self.active_connections:
                    websocket = self.active_connections[client_id]
                    await websocket_send_json(
                        websocket,
                        {
                            "error": "rate_limit_exceeded",
                            "message": "You are sending messages too quickly. Please slow down.",
                        },
                    )
                return

        if isinstance(message, bytes):
            message = base64.b64encode(message).decode()

        data_to_publish = orjson.dumps({"action": "send_message", "message": message, "client_id": client_id})

        await self.psm.publish(channel, data_to_publish)
        logger.debug(f"Published message to channel {channel} from client {client_id}")

    async def publish_message(self, channel: str, message: Any, client_id: str = "system"):
        """
        直接向频道发布消息，用于系统消息广播(临时)
        """
        if isinstance(message, bytes):
            message = base64.b64encode(message).decode()

        data_to_publish = orjson.dumps({"action": "send_message", "message": message, "client_id": client_id})

        await self.psm.publish(channel, data_to_publish)
        logger.debug(f"Published system message to channel {channel} from {client_id}")

    @abstractmethod
    async def _process_pubsub_message(self, channel: str, message: Any):
        """Process a MESSAGE received from the CHANNEL"""
        pass


class ProjectGeneralManager(WebsocketConnManager):
    """
    Project General Manager
    使用event_type和event_scope来区分消息类型
    """

    def __init__(self, url: Optional[str] = None, **kwargs):
        super().__init__(url, **kwargs)

        # 中介
        self.mediator = ClientMessageMediator(self)

        # 处理器
        self.chat_handler = ChatHandler(self.mediator)
        self.project_handler = ProjectHandler(self.mediator)

    async def _process_pubsub_message(self, channel: str, message: Any) -> None:
        try:
            # 检查并解析message
            if message["type"] != "message":
                raise ValueError(f"Skipping non-message type in process_pubsub: {message['type']}")

            message_data = message["data"]

            if isinstance(message_data, str):
                try:
                    parsed_data = orjson.loads(message_data)
                    logger.debug(f"Parsed JSON message: {parsed_data}")
                except orjson.JSONDecodeError:
                    raise ValueError(f"Invalid JSON message: {message_data}")
            else:
                parsed_data = message_data
                logger.debug(f"Using non-string message data: {parsed_data}")

            action = parsed_data.get("action")
            client_id = parsed_data.get("client_id")
            client_message = parsed_data.get("message", {})

            # 检查当前project是否存在
            async with async_session() as db:
                project = await ProjectDAO.get_project_by_id(uuid.UUID(channel), db)
                if not project:
                    raise ValueError(f"Project not found: {channel}")

            # 处理action
            if action in ["join", "leave", "disconnect"]:
                if action == "join":
                    logger.info(f"Client {client_id} joined channel {channel}")
                elif action == "leave":
                    logger.info(f"Client {client_id} left channel {channel}")
                elif action == "disconnect":
                    logger.info(f"Client {client_id} disconnected from channel {channel}")
                return

            if action == "send_message":
                # 解析client_message
                logger.info(f"Client Message Type: {type(client_message)}")
                if isinstance(client_message, str):
                    try:
                        client_message = orjson.loads(client_message)
                        logger.debug(f"Parsed nested JSON message: {client_message}")
                    except orjson.JSONDecodeError:
                        raise ValueError(f"Invalid nested JSON message format: {client_message}")

                event_type = client_message.get("event_type")  # EventType枚举
                event_scope = client_message.get("event_scope")  # EventScope枚举
                data = client_message.get("data", {})

                if not event_type or not event_scope or not data:
                    raise ValueError(f"Missing event_type or event_scope or data in message: {parsed_data}")

                # 分发消息
                event_scope = EventScope(event_scope)
                event_type = EventAction(event_type)
                await self.mediator.dispatch_message(channel, event_scope, event_type, client_id, data)
        except Exception as e:
            if client_id and action:
                await self._send_error_message(channel, client_id, 500, f"Error in process_pubsub_message: {e}", action)
            else:
                logger.error(f"Error in process_pubsub_message: {e}")

    async def _send_error_message(
        self, channel: str, client_id: str, code: int, message: str, original_action: Optional[str] = None
    ):
        """
        发送错误消息给客户端
        """
        logger.error(message)

        error_data = BroadcastErrorData(code=code, message=message, original_action=original_action)
        message = BroadcastErrorMessage(channel=channel, client_id=client_id, data=error_data)

        if client_id in self.active_connections:
            websocket = self.active_connections[client_id]
            await websocket.send_json(message.model_dump(mode="json"))
            logger.debug(f"Sent error message to client {client_id}")
        else:
            logger.warning(f"Catch error message from {client_id} but no connection found")


class ClientMessageMediator:
    """
    用户消息处理中介
    """

    def __init__(self, connection_manager: WebsocketConnManager):
        self.connection_manager = connection_manager
        self.handlers = {}

    def register_handler(self, event_scope: EventScope, event_type: EventAction, handler: Callable):
        """注册处理器"""
        self.handlers[(event_scope, event_type)] = handler

    async def dispatch_message(
        self, channel: str, event_scope: EventScope, event_type: EventAction, client_id: str, data: Any
    ):
        """分发消息"""
        handler_key = (event_scope, event_type)
        if handler_key in self.handlers:
            await self.handlers[handler_key](channel, event_scope, event_type, client_id, data)
        else:
            raise ValueError(f"No handler found for event_scope: {event_scope}, event_type: {event_type}")

    async def broadcast_message(self, broadcast_message: BroadcastMessage, channel: str) -> None:
        """广播消息"""
        for cid, channels in self.connection_manager.client_channels.items():
            if channel in channels and cid in self.connection_manager.active_connections:
                websocket = self.connection_manager.active_connections[cid]
                await websocket.send_json(broadcast_message.model_dump(mode="json"))
        logger.debug(f"Broadcast message to all clients in channel {channel}")


class ClientMessageHandler(ABC):
    """
    消息处理基类
    """

    def __init__(self, mediator: ClientMessageMediator):
        self.mediator = mediator
        self._register_handlers()

    @abstractmethod
    def _register_handlers(self):
        pass

    async def _broadcast_message(self, broadcast_message: BroadcastMessage, channel: str):
        await self.mediator.broadcast_message(broadcast_message, channel)


class ChatHandler(ClientMessageHandler):
    def _register_handlers(self):
        self.mediator.register_handler(EventScope.CHAT, EventAction.MESSAGE_SENT, self.handle_message_sent)
        # TODO 添加其他message_type

    async def handle_message_sent(
        self, channel: str, event_scope: EventScope, event_type: EventAction, client_id: str, data: Any
    ):
        """
        处理发送消息事件
        """
        try:
            # 提取消息数据
            message_type = data.get("message_type", "text")
            message_type = ChatMessageType(message_type)
            content = data.get("content")
            current_time = datetime.now()

            if not content:
                raise ValueError("Content is required")

            # 获取用户信息和项目信息
            async with async_session() as db:
                if client_id == "system":
                    user_info = {"id": "system", "username": "system", "email": ""}
                else:
                    # 获取用户信息
                    user = await UserDAO.get_user_by_id(uuid.UUID(client_id), db)
                    if not user:
                        raise ValueError(f"User not found: {client_id}")
                    user_info = {"id": str(user.id), "username": user.username, "email": user.email}

                    # 获取项目信息
                    project = await ProjectDAO.get_project_by_id(uuid.UUID(channel), db)
                    if not project:
                        raise ValueError(f"Project not found: {channel}")

                # 创建聊天消息数据
                chat_message = ChatMessageData(
                    message_type=message_type, content=content, timestamp=current_time, user=user_info
                )

                sent_message = BroadcastMessage(
                    event_type=event_type,
                    event_scope=event_scope,
                    channel=channel,
                    client_id=client_id,
                    data=chat_message.model_dump(mode="json"),
                )

                # 广播消息给所有客户端
                await self._broadcast_message(sent_message, channel)

                # 将消息保存到数据库
                if client_id != "system":
                    try:
                        await ChatDAO.create_chat_message(
                            message_type=message_type,
                            content=content,
                            room_id=project.chat_room.id,
                            sender_id=uuid.UUID(client_id),
                            created_at=current_time,
                            db=db,
                        )
                        logger.info(f"Chat message from {client_id} stored in database")
                    except Exception as e:
                        raise ValueError(f"Failed to store chat message: {e}")

        except Exception as e:
            logger.error(f"Error handling chat message: {e}")
            raise


class ProjectHandler(ClientMessageHandler):
    def _register_handlers(self):
        self.mediator.register_handler(EventScope.PROJECT, EventAction.PROJECT_UPDATED, self.handle_project_updated)
        self.mediator.register_handler(EventScope.PROJECT, EventAction.PROJECT_DELETED, self.handle_project_deleted)

    async def handle_project_updated(
        self, channel: str, event_scope: EventScope, event_type: EventAction, client_id: str, data: Any
    ):
        # try:
        #     updated_message = ClientMessage(
        #         event_type=event_type,
        #         event_scope=event_scope,
        #         channel=channel,
        #         client_id=client_id,
        #         data=data,
        #     )
        #     await self._broadcast_message(updated_message, channel)
        # except Exception as e:
        #     logger.error(f"Error handling project updated: {e}")
        #     raise
        pass

    async def handle_project_deleted(
        self, channel: str, event_scope: EventScope, event_type: EventAction, client_id: str, data: Any
    ):
        try:
            deleted_message = BroadcastMessage(
                event_type=event_type,
                event_scope=event_scope,
                channel=channel,
                client_id=client_id,
                data=data,
            )
            await self._broadcast_message(deleted_message, channel)
        except Exception as e:
            logger.error(f"Error handling project deleted: {e}")
            raise


# ==============================================================================
# Testing
# ==============================================================================


class MockWebSocket:
    def __init__(self, client_id: str):
        self.client_id = client_id
        self.messages = []

    async def send(self, data: Any):
        self.messages.append(data)
        logger.debug(f"Sent data to mock client {self.client_id}")

    async def send_json(self, data: Any):
        await self.send(data)


# NOTE: In tests, we use `sleep` to wait for async operations to complete


# async def test_chat_room():
#     """Test the ChatRoomManager functionality"""
#     logger.info("Testing ChatRoomManager")
#     user_1 = "921546678b304366b75224aacd6f6bc9"
#     user_2 = "af7b77929cb64fa1994c1ce2a5be62a8"
#     user_3 = "dcc6219460d643e99340163b6b1fc6c4"
#
#     # manager = ChatRoomManager("redis://localhost:6379")
#     manager = ChatRoomManager("memory://localhost:6379")
#     await manager.initialize()
#
#     await asyncio.sleep(0.5)
#
#     client1 = MockWebSocket(user_1)
#     client2 = MockWebSocket(user_2)
#     # client3 = MockWebSocket(user_3)
#
#     await manager.connect("921546678b304366b75224aacd6f6bc9", client1)  # pyright: ignore[reportArgumentType]
#     await manager.connect("af7b77929cb64fa1994c1ce2a5be62a8", client2)  # pyright: ignore[reportArgumentType]
#     # await manager.connect("dcc6219460d643e99340163b6b1fc6c4", client3)  # pyright: ignore[reportArgumentType]
#
#     await manager.subscribe_client_to_channel(user_1, "22813a3306104ddc93b8c513d3cc281d")
#     await asyncio.sleep(0.2)
#     await manager.subscribe_client_to_channel(user_2, "22813a3306104ddc93b8c513d3cc281d")
#     await asyncio.sleep(0.2)
#     # await manager.subscribe_client_to_channel("user3", "22813a3306104ddc93b8c513d3cc281d")
#     # await asyncio.sleep(0.2)
#     # await manager.subscribe_client_to_channel("user1", "22813a3306104ddc93b8c513d3cc281d")
#     # await asyncio.sleep(0.2)
#
#     await manager.send_message("22813a3306104ddc93b8c513d3cc281d", "Hello from user1!", user_1)
#     await asyncio.sleep(0.5)
#     await manager.send_message("22813a3306104ddc93b8c513d3cc281d", "Hi user1, this is user2!", user_2)
#     await asyncio.sleep(0.5)
#     # await manager.send_message("random", "Anyone in random channel?", "user3")
#     # await asyncio.sleep(0.5)
#
#     logger.info(f"Client user1 received {len(client1.messages)} messages")
#     logger.info(f"Client user2 received {len(client2.messages)} messages")
#     # logger.info(f"Client user3 received {len(client3.messages)} messages")
#
#     await manager.unsubscribe_client_from_channel(user_1, "22813a3306104ddc93b8c513d3cc281d")
#     await manager.disconnect(user_2, notification_channel="22813a3306104ddc93b8c513d3cc281d")
#
#     await asyncio.sleep(0.3)
#     await manager.cleanup()
#     logger.info("ChatRoomManager test completed")


async def test_dumbbroadcaster():
    """Test the DumbBroadcaster functionality"""
    logger.info("Testing DumbBroadcaster")

    # manager = DumbBroadcaster("redis://localhost:6379")
    manager = DumbBroadcaster("memory://localhost:6379")
    await manager.initialize()

    await asyncio.sleep(0.5)

    client1 = MockWebSocket("user1")
    client2 = MockWebSocket("user2")

    await manager.connect("user1", client1)  # pyright: ignore[reportArgumentType]
    await manager.connect("user2", client2)  # pyright: ignore[reportArgumentType]

    await manager.subscribe_client_to_channel("user1", "doc1")
    await asyncio.sleep(0.3)
    await manager.subscribe_client_to_channel("user2", "doc1")
    await asyncio.sleep(0.3)

    insert_op = {"type": "insert", "position": 0, "content": "Hello, world!"}

    delete_op = {"type": "delete", "position": 5, "count": 7}

    await manager.send_message("doc1", insert_op, "user1")
    await asyncio.sleep(0.5)
    await manager.send_message("doc1", delete_op, "user2")
    await asyncio.sleep(0.5)

    logger.info(f"Client user1 received {len(client1.messages)} messages")
    for i, msg in enumerate(client1.messages):
        logger.info(f"  Message {i+1}: {msg}")

    logger.info(f"Client user2 received {len(client2.messages)} messages")
    for i, msg in enumerate(client2.messages):
        logger.info(f"  Message {i+1}: {msg}")

    await manager.disconnect("user1", notification_channel="doc1")
    await asyncio.sleep(0.2)
    await manager.disconnect("user2", notification_channel="doc1")
    await asyncio.sleep(0.3)

    await manager.cleanup()
    logger.info("DumbBroadcaster test completed")


async def main():
    """Run tests for both manager types"""
    logger.enable(__name__)
    logger.info("Starting tests")

    # await test_chat_room()
    # await test_dumbbroadcaster()

    logger.info("Tests completed")


if __name__ == "__main__":
    asyncio.run(main())
