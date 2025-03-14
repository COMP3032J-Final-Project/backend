"""
To create a new Connection Manager:
1. Create a new class that implements `WebsocketConnManager`
2. Implement the `_process_pubsub_message` method
3. Add it to app/core/websocket.py and update handlers in app/core/events.py
"""

import asyncio
import time
from typing import Dict, Any, Optional, List, Set, Tuple
import orjson
from abc import ABC, abstractmethod
from fastapi import WebSocket
from loguru import logger
import redis.asyncio as aioredis

logger.disable(__name__)

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
        self,
        redis_url: str,
        pool_size: Optional[int] = None,
        reconnect_attempts: int = 5,
        reconnect_delay: float = 1.0
    ):
        # Only initialize once due to singleton pattern
        if not hasattr(self, 'redis_url'):
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
                self.redis_url, 
                max_connections=self.pool_size,
                decode_responses=True
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
            await self.conn_pool.aclose();
            
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
        listener_task = asyncio.create_task(
            self._pubsub_listener(topic, pubsub, message_queue)
        )
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
                if message["type"] == "message":
                    # This is an actual message published by another client
                    await queue.put(message)
                elif message["type"] == "error":
                    logger.error(f"Error in Redis PubSub for topic {topic}: {message.get('data')}")
                else:
                    # Skip Redis protocol messages like 'subscribe' confirmations
                    logger.debug(f"Skipping Redis protocol message type: {message['type']}")
                
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
    
    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(InMemoryPubSubManager, cls).__new__(cls)
        return cls._instance
    
    def __init__(self, max_messages_per_topic: int = 1000, message_ttl: float = 3600):
        # Only initialize once due to singleton pattern
        if not hasattr(self, 'initialized'):
            self.initialized = True
            self.topics: Dict[str, List[Tuple[float, str | bytes]]] = {}  # topic -> [(timestamp, message)]
            self.subscribers: Dict[str, List[asyncio.Queue]] = {}
            self.max_messages_per_topic = max_messages_per_topic
            self.message_ttl = message_ttl  # TTL in seconds
            self.cleanup_task = None
            
    async def connect(self) -> None:
        logger.info("Connected to in-memory PubSub")
        # Start cleanup task
        self.cleanup_task = asyncio.create_task(self._cleanup_old_messages())
        
    async def disconnect(self) -> None:
        if self.cleanup_task and not self.cleanup_task.done():
            self.cleanup_task.cancel()
            try:
                await self.cleanup_task
            except asyncio.CancelledError:
                pass
                
        self.topics.clear()
        self.subscribers.clear()
        logger.info("Disconnected from in-memory PubSub")
        
    async def _cleanup_old_messages(self):
        """Periodically clean up old messages"""
        try:
            while True:
                await asyncio.sleep(60)  # Run cleanup every minute
                current_time = time.time()
                
                for topic in list(self.topics.keys()):
                    # Remove messages older than TTL
                    self.topics[topic] = [
                        (ts, msg) for ts, msg in self.topics[topic]
                        if ts > current_time - self.message_ttl
                    ]
                    
                    # If topic has too many messages, trim it
                    if len(self.topics[topic]) > self.max_messages_per_topic:
                        # Keep only the most recent messages
                        self.topics[topic] = self.topics[topic][-self.max_messages_per_topic:]
                        
        except asyncio.CancelledError:
            logger.info("Message cleanup task cancelled")
        
    async def publish(self, topic: str, message: str | bytes) -> None:
        current_time = time.time()
        
        if topic not in self.topics:
            self.topics[topic] = []
            
        # Store message with timestamp
        self.topics[topic].append((current_time, message))
        
        # Trim if needed
        if len(self.topics[topic]) > self.max_messages_per_topic:
            self.topics[topic] = self.topics[topic][-self.max_messages_per_topic:]
        
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
    _instance = None
    
    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(WebsocketConnManager, cls).__new__(cls)
        return cls._instance
    
    def __init__(
        self,
        url: Optional[str] = None,
        batch_size: int = 10,
        batch_interval: float = 0.1,
        rate_limit: int = 100,
        rate_period: float = 60.0
    ):
        # Initialize attributes only once (singleton pattern)
        if not hasattr(self, 'initialized'):
            self.initialized = True
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
            await self.psm.publish(notification_channel, orjson.dumps({
                "action": "disconnect",
                "client_id": client_id
            }))
            
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
        
        task = asyncio.create_task(
            self._listen_to_channel(channel, subscriber)
        )
        
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
        await self.psm.publish(channel, orjson.dumps({
            "action": "join",
            "client_id": client_id
        }))
        
        logger.debug(f"Client {client_id} subscribed to channel {channel}")
        
    async def unsubscribe_client_from_channel(self, client_id: str, channel: str) -> None:
        """Unsubscribe a client from a channel"""
        if client_id in self.client_channels and channel in self.client_channels[client_id]:
            self.client_channels[client_id].remove(channel)
            
            # Notify others
            await self.psm.publish(channel, orjson.dumps({
                "action": "leave",
                "client_id": client_id
            }))
            
            logger.debug(f"Client {client_id} unsubscribed from channel {channel}")
            
            # Check if any clients are still subscribed to this channel
            has_subscribers = any(
                channel in self.client_channels[client_id]
                for client_id in self.client_channels
            )
            
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
            self.batch_tasks[client_id] = asyncio.create_task(
                self._process_batch(client_id)
            )
        
        self.message_batches[client_id].append(message)
        
        # If we've reached batch size, process immediately
        if len(self.message_batches[client_id]) >= self.batch_size:
            if client_id in self.batch_tasks and not self.batch_tasks[client_id].done():
                self.batch_tasks[client_id].cancel()
            self.batch_tasks[client_id] = asyncio.create_task(
                self._process_batch(client_id)
            )

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
                await websocket_send_json(websocket, {
                    "type": "batch",
                    "messages": batch
                })
                
        except asyncio.CancelledError:
            # Process any remaining messages before exiting
            if client_id in self.message_batches and self.message_batches[client_id]:
                if client_id in self.active_connections:
                    batch = self.message_batches[client_id]
                    self.message_batches[client_id] = []
                    
                    websocket = self.active_connections[client_id]
                    await websocket_send_json(websocket, {
                        "type": "batch",
                        "messages": batch
                    })
                    
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
                logger.debug(f"Channel {channel} received message: {message}")

                # Skip errors and other non-message types
                if message.get("type") == "error":
                    logger.error(f"Error in PubSub for channel {channel}: {message.get('data')}")
                    continue
                elif message.get("type") != "message":
                    logger.debug(f"Skipping non-message type in channel listener: {message.get('type')}")
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
        # Remove timestamps older than the rate period
        self.client_message_counts[client_id] = [
            t for t in self.client_message_counts[client_id]
            if t > current_time - self.rate_period
        ]
        
        return len(self.client_message_counts[client_id]) <= self.rate_limit
    
    async def send_message(self, channel: str, message: Any, client_id: str):
        """Handle a message from a client with rate limiting"""
        if channel not in self.client_channels[client_id]:
            raise Exception(f"Client {client_id} is not in channel {channel}!")
        
        # Add current timestamp
        current_time = time.time()
        if client_id not in self.client_message_counts:
            self.client_message_counts[client_id] = []
        self.client_message_counts[client_id].append(current_time)
        
        # Check rate limit
        if not await self._check_rate_limit(client_id, current_time):
            logger.warning(f"Rate limit exceeded for client {client_id}")
            # Optionally notify client they've been rate limited
            if client_id in self.active_connections:
                websocket = self.active_connections[client_id]
                await websocket_send_json(websocket, {
                    "error": "rate_limit_exceeded",
                    "message": "You are sending messages too quickly. Please slow down."
                })
            return
        
        data_to_publish = orjson.dumps({
            "action": "send_message",
            "message": message,
            "client_id": client_id
        })
        
        await self.psm.publish(channel, data_to_publish)
        logger.debug(f"Published message to channel {channel} from client {client_id}")
    
    @abstractmethod
    async def _process_pubsub_message(self, channel: str, message: Any):
        """Process a MESSAGE received from the CHANNEL"""
        pass


class ChatRoomManager(WebsocketConnManager):
    # NOTE leave it blank now. You can look into previous git commits to
    # get its original code
    async def _process_pubsub_message(self, channel: str, message: Any):
        pass


class DumbBroadcaster(WebsocketConnManager):
    """Simple broadcaster that forwards messages to all subscribed clients"""
    async def _process_pubsub_message(self, channel: str, message: Any):
        # Get message data once
        message_data = message["data"]
        
        # Parse JSON only once if it's a string
        if isinstance(message_data, str):
            try:
                parsed_message = orjson.loads(message_data)
            except orjson.JSONDecodeError:
                logger.warning(f"Failed to parse message as JSON: {message_data[:100]}")
                return
        else:
            parsed_message = message_data
        
        # Parse nested message if needed
        nested_message = parsed_message.get("message", None)
        if isinstance(nested_message, str):
            try:
                parsed_message["message"] = orjson.loads(nested_message)
            except orjson.JSONDecodeError:
                return
        
        # Get clients subscribed to this channel
        client_ids = [
            cid
            for cid, channels in self.client_channels.items()
            if channel in channels # client as subscribed this channel
        ]
        
        if not client_ids:  # No clients to send to
            return
        
        # Serialize the message once instead of for each client
        serialized_message = orjson.dumps(parsed_message)
        
        # Send to all subscribed clients
        send_tasks = []
        for cid in client_ids:
            if cid in self.active_connections:
                websocket = self.active_connections[cid]
                if hasattr(self, 'batch_size') and self.batch_size > 1:
                    await self.add_message_to_batch(cid, parsed_message)
                else:
                    send_tasks.append(
                        websocket.send_bytes(serialized_message)
                    )
        
        # Wait for all sends to complete if not batching
        if send_tasks:
            await asyncio.gather(*send_tasks)

                
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


# NOTE: In tests, we use `sleep` to wait for async operations to complete
    
async def test_chat_room():
    """Test the ChatRoomManager functionality"""
    logger.info("Testing ChatRoomManager")
            
    manager = ChatRoomManager("redis://localhost:6379")
    await manager.initialize()
            
    await asyncio.sleep(0.5)
            
    client1 = MockWebSocket("user1")
    client2 = MockWebSocket("user2")
    client3 = MockWebSocket("user3")
            
    await manager.connect("user1", client1) # pyright: ignore[reportArgumentType]
    await manager.connect("user2", client2) # pyright: ignore[reportArgumentType]
    await manager.connect("user3", client3) # pyright: ignore[reportArgumentType]
            
    await manager.subscribe_client_to_channel("user1", "general")
    await asyncio.sleep(0.2)
    await manager.subscribe_client_to_channel("user2", "general") 
    await asyncio.sleep(0.2)
    await manager.subscribe_client_to_channel("user3", "random")
    await asyncio.sleep(0.2)
    await manager.subscribe_client_to_channel("user1", "random")
    await asyncio.sleep(0.2)
            
    await manager.send_message("general", "Hello from user1!", "user1")
    await asyncio.sleep(0.5)
    await manager.send_message("general", "Hi user1, this is user2!", "user2")
    await asyncio.sleep(0.5)
    await manager.send_message("random", "Anyone in random channel?", "user3")
    await asyncio.sleep(0.5)
        
    logger.info(f"Client user1 received {len(client1.messages)} messages")
    logger.info(f"Client user2 received {len(client2.messages)} messages")
    logger.info(f"Client user3 received {len(client3.messages)} messages")
        
    await manager.unsubscribe_client_from_channel("user1", "general")
    await manager.disconnect("user3", notification_channel="general")
        
    await asyncio.sleep(0.3)
    await manager.cleanup()
    logger.info("ChatRoomManager test completed")


async def test_dumbbroadcaster():
    """Test the DumbBroadcaster functionality"""
    logger.info("Testing DumbBroadcaster")
            
    manager = DumbBroadcaster("redis://localhost:6379")
    await manager.initialize()
            
    await asyncio.sleep(0.5)
            
    client1 = MockWebSocket("user1")
    client2 = MockWebSocket("user2")
            
    await manager.connect("user1", client1) # pyright: ignore[reportArgumentType]
    await manager.connect("user2", client2) # pyright: ignore[reportArgumentType]
            
    await manager.subscribe_client_to_channel("user1", "doc1")
    await asyncio.sleep(0.3)
    await manager.subscribe_client_to_channel("user2", "doc1")
    await asyncio.sleep(0.3)
            
    insert_op = {
        "type": "insert",
        "position": 0,
        "content": "Hello, world!"
    }
            
    delete_op = {
        "type": "delete",
        "position": 5,
        "count": 7
    }
            
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
    await test_dumbbroadcaster()
        
    logger.info("Tests completed")

if __name__ == "__main__":
    asyncio.run(main())

