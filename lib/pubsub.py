import asyncio
from typing import Dict, Any, Optional, List, Set, Union
import json
from abc import ABC, abstractmethod
from fastapi import WebSocket
from loguru import logger
import redis.asyncio as aioredis

logger.disable(__name__)

class ConnectionNotInitiailized(Exception):
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
    async def publish(self, topic: str, message: str) -> None:
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
    
    This class is implemented as a singleton to ensure only one instance
    manages all Redis connections across the application.
    
    Key design aspects:
    1. Creates a separate Redis connection for each subscription channel
    2. Uses asyncio.Queue to bridge Redis messages to application code
    3. Handles message filtering and processing
    """
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(RedisPubSubManager, cls).__new__(cls)
        return cls._instance

    def __init__(self, redis_url: str):
        # Only initialize once due to singleton pattern
        if not hasattr(self, 'redis_url'):
            self.redis_url = redis_url
            self.conn = None  # Main Redis connection for publishing
            self.pubsubs = {}  # Channel -> PubSub instance (separate connections)
            self.listeners = {}  # Channel -> Task (background tasks listening for messages)
            self.message_queues = {}  # Channel -> Queue (async queues for message passing)
            self.callbacks = {}  # Channel -> Callback function (unused in current implementation)
            
    async def _get_redis_connection(self) -> Any:
        return await aioredis.from_url(self.redis_url, decode_responses=True)
    
    async def connect(self) -> None:
        self.conn = await self._get_redis_connection()
        
        logger.info(f"Connected to Redis at {self.redis_url}")
        
        try:
            await self.conn.ping()
            logger.info("Successfully pinged Redis server")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise
        
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
        for channel, pubsub in self.pubsubs.items():
            await pubsub.unsubscribe()
            await pubsub.aclose()
            
        # Close main connection
        if self.conn:
            await self.conn.aclose()
            
        # Clear all data structures
        self.pubsubs.clear()
        self.listeners.clear()
        self.message_queues.clear()
        self.callbacks.clear()
        
    async def publish(self, topic: str, message: str) -> None:
        if not self.conn:
            raise ConnectionNotInitiailized()
        
        await self.conn.publish(topic, message)
        
    async def subscribe(self, topic: str) -> asyncio.Queue:
        """
        Subscribe to a topic and return a queue for receiving messages.
        
        This method:
        1. Creates a dedicated Redis connection for this subscription
        2. Sets up an asyncio.Queue to receive messages
        3. Starts a background task to listen for messages
        
        Why a separate Redis connection per subscription?
        - Redis PubSub connections enter a special state and can't be used for other commands
        - Separate connections allow independent handling of each subscription
        - Prevents blocking issues when receiving messages on multiple channels
        
        Returns:
            asyncio.Queue: Queue that will receive messages from this topic
        """
        if not self.conn:
            raise ConnectionNotInitiailized()
        
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
        
        logger.info(f"Successfully subscribed to Redis topic: {topic}")
        
        return message_queue
    
    async def _pubsub_listener(self, topic: str, pubsub, queue: asyncio.Queue):
        """
        Listens for messages on a pubsub channel and puts them in the queue.
        
        This method:
        1. Runs as a background task for each subscription
        2. Filters message types to only process actual messages
        3. Puts messages into the queue for application code to consume
        
        Why filter message types?
        - Redis PubSub sends various message types: 'subscribe', 'unsubscribe', 'message'
        - Only 'message' types contain actual data from publishers
        - Other types are Redis protocol messages that should be ignored for application logic
        
        Message structure from Redis:
        {
            "type": "message",       # or "subscribe", "unsubscribe", etc.
            "pattern": None,         # pattern if pattern-matching subscription
            "channel": "channel-name", # the channel name
            "data": "actual-message"  # the message payload
        }
        """
        try:
            logger.info(f"Starting Redis PubSub listener for topic: {topic}")
            
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
            logger.info(f"Redis PubSub listener for topic {topic} cancelled")
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
    
    def __init__(self):
        # Only initialize once due to singleton pattern
        if not hasattr(self, 'initialized'):
            self.initialized = True
            self.topics: Dict[str, List[str]] = {}
            self.subscribers: Dict[str, List[asyncio.Queue]] = {}
            
    async def connect(self) -> None:
        logger.info("Connected to in-memory PubSub")
        
    async def disconnect(self) -> None:
        self.topics.clear()
        self.subscribers.clear()
        logger.info("Disconnected from in-memory PubSub")
        
    async def publish(self, topic: str, message: str) -> None:
        if topic not in self.topics:
            self.topics[topic] = []
            
        self.topics[topic].append(message)
        
        if topic in self.subscribers:
            for queue in self.subscribers[topic]:
                await queue.put({"type": "message", "channel": topic, "data": message})
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
    
    def __init__(self, url: Optional[str] = None):
        # Initialize attributes only once (singleton pattern)
        if not hasattr(self, 'initialized'):
            self.initialized = True
            self.active_connections: Dict[str, WebSocket] = {}
            
            if url is None or url == "memory://":
                self.psm = InMemoryPubSubManager()
                logger.info("Using in-memory PubSub manager")
            elif url.startswith("redis://"):
                self.psm = RedisPubSubManager(url)
                logger.info(f"Using Redis PubSub manager with URL: {url}")
            else:
                raise ValueError(f"Unsupported URL scheme: {url}")
            
    async def initialize(self) -> None:
        """Initialize the connection to the PubSub backend"""
        await self.psm.connect()
        
    async def cleanup(self) -> None:
        """Clean up resources before shutdown"""
        await self.psm.disconnect()
        
    async def connect(self, client_id: str, websocket: WebSocket) -> None:
        """Accept a new WebSocket connection and store it"""
        await websocket.accept()
        self.active_connections[client_id] = websocket
        logger.info(f"Client {client_id} connected.")
        
    async def disconnect(self, channel: str, client_id: str) -> None:
        """Handle client disconnection"""
        if client_id in self.active_connections:
            await self._handle_disconnect(channel, client_id)
            del self.active_connections[client_id]
            logger.info(f"Client {client_id} disconnected and removed from active connections.")
            
    @abstractmethod
    async def _handle_disconnect(self, channel: str, client_id: str) -> None:
        """Implementation-specific disconnect handling"""
        pass
    
    @abstractmethod
    async def handle_web_receive_message(self, channel: str, message: str, client_id: str) -> None:
        """Handle a message received from a WebSocket"""
        pass
    
    @abstractmethod
    async def subscribe_to_channel(self, channel: str) -> asyncio.Task:
        """Subscribe to a PubSub channel and start listening for messages"""
        pass
    
    @abstractmethod
    async def _process_pubsub_message(self, channel: str, data: Any) -> None:
        """Process a message received from the PubSub system"""
        pass


class ChatRoomManager(WebsocketConnManager):
    def __init__(self, url: Optional[str] = None):
        super().__init__(url)
        # Track which channels each client is subscribed to
        if not hasattr(self, 'client_channels'):
            self.client_channels: Dict[str, Set[str]] = {}
            # Track active channel listeners
            self.channel_tasks: Dict[str, asyncio.Task] = {}
            
    async def _handle_disconnect(self, channel: str, client_id: str) -> None:
        """Notify other clients about disconnection"""
        await self.psm.publish(channel, json.dumps({
            "action": "disconnect",
            "client_id": client_id
        }))
        
        # Remove client from all channels
        if client_id in self.client_channels:
            for channel in list(self.client_channels[client_id]):
                await self._unsubscribe_client_from_channel(client_id, channel)
                
            del self.client_channels[client_id]
            
    async def handle_web_receive_message(self, channel: str, message: str, client_id: str) -> None:
        """Handle a chat message from a client"""
        data_to_publish = json.dumps({
            "action": "send_message",
            "message": message,
            "client_id": client_id
        })
        await self.psm.publish(channel, data_to_publish)
        logger.info(f"Published message to channel {channel} for client {client_id}.")
        
    async def subscribe_to_channel(self, channel: str) -> asyncio.Task:
        """Subscribe to a channel and start a listener task"""
        if channel in self.channel_tasks and not self.channel_tasks[channel].done():
            return self.channel_tasks[channel]
        
        logger.info(f"Subscribing to chat channel {channel}.")
        subscriber = await self.psm.subscribe(channel)
        
        task = asyncio.create_task(
            self._listen_to_channel(channel, subscriber)
        )
        
        self.channel_tasks[channel] = task
        return task
    
    async def subscribe_client_to_channel(self, client_id: str, channel: str) -> None:
        """Subscribe a client to a channel"""
        if client_id not in self.client_channels:
            self.client_channels[client_id] = set()
            
        self.client_channels[client_id].add(channel)
        
        # Make sure we're listening to this channel
        await self.subscribe_to_channel(channel)
        
        # Notify others about new client
        await self.psm.publish(channel, json.dumps({
            "action": "join",
            "client_id": client_id
        }))
        
        logger.info(f"Client {client_id} subscribed to channel {channel}")
        
    async def _unsubscribe_client_from_channel(self, client_id: str, channel: str) -> None:
        """Unsubscribe a client from a channel"""
        if client_id in self.client_channels and channel in self.client_channels[client_id]:
            self.client_channels[client_id].remove(channel)
            
            # Notify others
            await self.psm.publish(channel, json.dumps({
                "action": "leave",
                "client_id": client_id
            }))
            
            logger.info(f"Client {client_id} unsubscribed from channel {channel}")
            
            # Check if any clients are still subscribed to this channel
            has_subscribers = any(
                client_id in self.client_channels and 
                channel in self.client_channels[client_id]
                for client_id in self.client_channels
            )
            
            if not has_subscribers and channel in self.channel_tasks:
                logger.info(f"No more clients subscribed to channel {channel}, stopping listener")
                self.channel_tasks[channel].cancel()
                await self.psm.unsubscribe(channel)
                del self.channel_tasks[channel]
                
    async def _listen_to_channel(self, channel: str, subscriber: Any) -> None:
        """Listen for messages on a PubSub channel"""
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
            logger.info(f"Channel listener for {channel} was cancelled")
        except Exception as e:
            logger.error(f"Error in channel listener for {channel}: {e}")
            raise
        
    async def _process_pubsub_message(self, channel: str, data: Any) -> None:
        """Process a message from the PubSub system"""
        try:
            # We should already be filtering for message types in the listener
            # but double-check here just in case
            if data["type"] != "message":
                logger.debug(f"Skipping non-message type in process_pubsub: {data['type']}")
                return
            
            message_data = data["data"]
            logger.debug(f"Processing message data: {message_data}")
            
            if isinstance(message_data, str):
                try:
                    message = json.loads(message_data)
                    logger.debug(f"Parsed JSON message: {message}")
                except json.JSONDecodeError:
                    logger.error(f"Invalid JSON message: {message_data}")
                    return
            else:
                message = message_data
                logger.debug(f"Using non-string message data: {message}")
                
            action = message.get("action")
            client_id = message.get("client_id")
            
            if action == "send_message":
                # Forward to all subscribed clients
                chat_message = message.get("message")
                
                for cid, channels in self.client_channels.items():
                    if channel in channels and cid in self.active_connections:
                        websocket = self.active_connections[cid]
                        await websocket.send_text(json.dumps({
                            "type": "chat",
                            "channel": channel,
                            "from": client_id,
                            "message": chat_message
                        }))
                        
                logger.info(f"Forwarded chat message from {client_id} to all clients in channel {channel}")
                
            elif action == "join":
                # Notify about new member
                for cid, channels in self.client_channels.items():
                    if channel in channels and cid in self.active_connections and cid != client_id:
                        websocket = self.active_connections[cid]
                        await websocket.send_text(json.dumps({
                            "type": "join",
                            "channel": channel,
                            "client_id": client_id
                        }))
                        
                logger.info(f"Notified clients about {client_id} joining channel {channel}")
                
            elif action == "leave" or action == "disconnect":
                # Notify about member leaving
                for cid, channels in self.client_channels.items():
                    if channel in channels and cid in self.active_connections and cid != client_id:
                        websocket = self.active_connections[cid]
                        await websocket.send_text(json.dumps({
                            "type": "leave",
                            "channel": channel,
                            "client_id": client_id
                        }))
                        
                logger.info(f"Notified clients about {client_id} leaving channel {channel}")
                
        except Exception as e:
            logger.error(f"Error processing pubsub message: {e}")
            raise


class CRDTManager(WebsocketConnManager):
    def __init__(self, url: Optional[str] = None):
        super().__init__(url)
        # Track which documents each client is editing
        if not hasattr(self, 'client_documents'):
            self.client_documents: Dict[str, Set[str]] = {}
            # Track active document listeners
            self.document_tasks: Dict[str, asyncio.Task] = {}
            
    async def _handle_disconnect(self, document_id: str, client_id: str) -> None:
        """Notify other clients about disconnection"""
        await self.psm.publish(f"doc:{document_id}", json.dumps({
            "action": "disconnect",
            "client_id": client_id
        }))
        
        # Remove client from all documents
        if client_id in self.client_documents:
            for doc_id in list(self.client_documents[client_id]):
                await self._unsubscribe_client_from_document(client_id, doc_id)
                
            del self.client_documents[client_id]
            
    async def handle_web_receive_message(self, document_id: str, message: str, client_id: str) -> None:
        """Handle a CRDT operation from a client"""
        try:
            # Parse the CRDT operation
            operation = json.loads(message)
            
            # Publish the operation to all clients editing this document
            data_to_publish = json.dumps({
                "action": "crdt_op",
                "operation": operation,
                "client_id": client_id
            })
            
            await self.psm.publish(f"doc:{document_id}", data_to_publish)
            logger.info(f"Published CRDT operation to document {document_id} from client {client_id}.")
            
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON operation from client {client_id}: {message}")
            
    async def subscribe_to_channel(self, document_id: str) -> asyncio.Task:
        """Subscribe to a document channel and start a listener task"""
        channel = f"doc:{document_id}"
        
        if document_id in self.document_tasks and not self.document_tasks[document_id].done():
            return self.document_tasks[document_id]
        
        logger.info(f"Subscribing to document channel {channel}.")
        subscriber = await self.psm.subscribe(channel)
        
        task = asyncio.create_task(
            self._listen_to_channel(document_id, subscriber)
        )
        
        self.document_tasks[document_id] = task
        return task
    
    async def subscribe_client_to_document(self, client_id: str, document_id: str) -> None:
        """Subscribe a client to a document"""
        if client_id not in self.client_documents:
            self.client_documents[client_id] = set()
            
        self.client_documents[client_id].add(document_id)
        
        # Make sure we're listening to this document
        await self.subscribe_to_channel(document_id)
        
        # Notify others about new client
        await self.psm.publish(f"doc:{document_id}", json.dumps({
            "action": "join_document",
            "client_id": client_id
        }))
        
        logger.info(f"Client {client_id} subscribed to document {document_id}")
        
    async def _unsubscribe_client_from_document(self, client_id: str, document_id: str) -> None:
        """Unsubscribe a client from a document"""
        if client_id in self.client_documents and document_id in self.client_documents[client_id]:
            self.client_documents[client_id].remove(document_id)
            
            # Notify others
            await self.psm.publish(f"doc:{document_id}", json.dumps({
                "action": "leave_document",
                "client_id": client_id
            }))
            
            logger.info(f"Client {client_id} unsubscribed from document {document_id}")
            
            # Check if any clients are still subscribed to this document
            has_subscribers = any(
                client_id in self.client_documents and 
                document_id in self.client_documents[client_id]
                for client_id in self.client_documents
            )
            
            if not has_subscribers and document_id in self.document_tasks:
                logger.info(f"No more clients subscribed to document {document_id}, stopping listener")
                self.document_tasks[document_id].cancel()
                await self.psm.unsubscribe(f"doc:{document_id}")
                del self.document_tasks[document_id]
                
    async def _listen_to_channel(self, document_id: str, subscriber: Any) -> None:
        """Listen for messages on a PubSub channel"""
        channel = f"doc:{document_id}"
        try:
            # Both in-memory and Redis implementation now use Queue
            while True:
                message = await subscriber.get()
                logger.debug(f"Document {document_id} received message: {message}")
                
                # Skip errors and other non-message types
                if message.get("type") == "error":
                    logger.error(f"Error in PubSub for document {document_id}: {message.get('data')}")
                    continue
                elif message.get("type") != "message":
                    logger.debug(f"Skipping non-message type in document listener: {message.get('type')}")
                    continue
                
                # Process the message
                await self._process_pubsub_message(document_id, message)
                
                # Mark task as done if queue supports it
                if hasattr(subscriber, 'task_done'):
                    subscriber.task_done()
        except asyncio.CancelledError:
            logger.info(f"Document listener for {document_id} was cancelled")
        except Exception as e:
            logger.error(f"Error in document listener for {document_id}: {e}")
            raise
        
    async def _process_pubsub_message(self, document_id: str, data: Any) -> None:
        """Process a message from the PubSub system"""
        try:
            # Allow subscribe messages to pass through for initial connection
            if data["type"] == "subscribe":
                logger.info(f"Subscription confirmed for document {document_id}")
                return
                
            if data["type"] != "message":
                logger.debug(f"Skipping message with type {data['type']} for document {document_id}")
                return  # Skip other non-message types
            
            message_data = data["data"]
            if isinstance(message_data, str):
                try:
                    message = json.loads(message_data)
                except json.JSONDecodeError:
                    logger.error(f"Invalid JSON message for document {document_id}: {message_data}")
                    return
            else:
                message = message_data
                
            action = message.get("action")
            client_id = message.get("client_id")
            
            if action == "crdt_op":
                # Forward to all other clients editing this document
                operation = message.get("operation")
                
                for cid, documents in self.client_documents.items():
                    if document_id in documents and cid in self.active_connections and cid != client_id:
                        websocket = self.active_connections[cid]
                        await websocket.send_text(json.dumps({
                            "type": "crdt_op",
                            "document_id": document_id,
                            "from": client_id,
                            "operation": operation
                        }))
                        
                logger.info(f"Forwarded CRDT operation from {client_id} for document {document_id}")
                
            elif action == "join_document":
                # Notify about new collaborator
                for cid, documents in self.client_documents.items():
                    if document_id in documents and cid in self.active_connections and cid != client_id:
                        websocket = self.active_connections[cid]
                        await websocket.send_text(json.dumps({
                            "type": "collaborator_joined",
                            "document_id": document_id,
                            "client_id": client_id
                        }))
                        
                logger.info(f"Notified clients about {client_id} joining document {document_id}")
                
            elif action == "leave_document" or action == "disconnect":
                # Notify about collaborator leaving
                for cid, documents in self.client_documents.items():
                    if document_id in documents and cid in self.active_connections and cid != client_id:
                        websocket = self.active_connections[cid]
                        await websocket.send_text(json.dumps({
                            "type": "collaborator_left",
                            "document_id": document_id,
                            "client_id": client_id
                        }))
                        
                logger.info(f"Notified clients about {client_id} leaving document {document_id}")
                
        except Exception as e:
            logger.error(f"Error processing pubsub message for document {document_id}: {e}")
            raise





class MockWebSocket:
    def __init__(self, client_id: str):
        self.client_id = client_id
        self.messages = []
        
    async def accept(self) -> None:
        logger.info(f"Mock WebSocket for client {self.client_id} accepted")
        
    async def send_text(self, message: str) -> None:
        self.messages.append(message)
        logger.info(f"Sent message to mock client {self.client_id}: {message}")
        
    async def receive_text(self) -> str:
        return json.dumps({"test": "data"})  # Default test response


# NOTE, in test, we uses `sleep` to artificially wait for operations to finish before
# checking results. Whereas in real world, we don't need to do so
    
async def test_chat_room():
    """Test the ChatRoomManager functionality"""
    logger.info("Testing ChatRoomManager")
        
    manager = ChatRoomManager("redis://localhost:7890")
    await manager.initialize()
        
    # Give connection time to fully establish
    await asyncio.sleep(0.5)
        
    # Create mock WebSockets
    client1 = MockWebSocket("user1")
    client2 = MockWebSocket("user2")
    client3 = MockWebSocket("user3")
        
    # Connect clients
    await manager.connect("user1", client1)
    await manager.connect("user2", client2)
    await manager.connect("user3", client3)
        
    # Subscribe clients to channels
    await manager.subscribe_client_to_channel("user1", "general")
    await asyncio.sleep(0.2)  # Give more time for subscription to complete
        
    await manager.subscribe_client_to_channel("user2", "general") 
    await asyncio.sleep(0.2)
        
    await manager.subscribe_client_to_channel("user3", "random")
    await asyncio.sleep(0.2)
        
    await manager.subscribe_client_to_channel("user1", "random")
    await asyncio.sleep(0.2)
        
    # Send messages
    await manager.handle_web_receive_message("general", "Hello from user1!", "user1")
    await asyncio.sleep(0.5)  # Give more time for message processing
        
    await manager.handle_web_receive_message("general", "Hi user1, this is user2!", "user2")
    await asyncio.sleep(0.5)
        
    await manager.handle_web_receive_message("random", "Anyone in random channel?", "user3")
        
    # Wait longer for messages to be processed
    await asyncio.sleep(1.0)
    
    # Print client message counts
    logger.info(f"Client user1 received {len(client1.messages)} messages")
    logger.info(f"Client user2 received {len(client2.messages)} messages")
    logger.info(f"Client user3 received {len(client3.messages)} messages")
    
    # Unsubscribe and disconnect
    await manager._unsubscribe_client_from_channel("user1", "general")
    await manager.disconnect("general", "user3")
    
    # Give time for cleanup
    await asyncio.sleep(0.3)
    
    await manager.cleanup()
    logger.info("ChatRoomManager test completed")


async def test_crdt_manager():
    """Test the CRDTManager functionality"""
    logger.info("Testing CRDTManager")
        
    manager = CRDTManager("redis://localhost:6379")
    await manager.initialize()
        
    # Give connection time to fully establish
    await asyncio.sleep(0.5)
        
    # Create mock WebSockets
    client1 = MockWebSocket("user1")
    client2 = MockWebSocket("user2")
        
    # Connect clients
    await manager.connect("user1", client1)
    await manager.connect("user2", client2)
        
    # Subscribe clients to documents
    await manager.subscribe_client_to_document("user1", "doc1")
    await asyncio.sleep(0.3)  # Give more time for subscription to complete
        
    await manager.subscribe_client_to_document("user2", "doc1")
    await asyncio.sleep(0.3)
        
    # Send CRDT operations
    insert_op = json.dumps({
        "type": "insert",
        "position": 0,
        "content": "Hello, world!"
    })
        
    delete_op = json.dumps({
        "type": "delete",
        "position": 5,
        "count": 7
    })
        
    await manager.handle_web_receive_message("doc1", insert_op, "user1")
    await asyncio.sleep(0.5)  # Give more time for message propagation
        
    await manager.handle_web_receive_message("doc1", delete_op, "user2")
        
    # Wait longer for messages to be processed
    await asyncio.sleep(1.0)
    
    # Print client message counts
    logger.info(f"Client user1 received {len(client1.messages)} messages")
    for i, msg in enumerate(client1.messages):
        logger.info(f"  Message {i+1}: {msg}")
        
    logger.info(f"Client user2 received {len(client2.messages)} messages")
    for i, msg in enumerate(client2.messages):
        logger.info(f"  Message {i+1}: {msg}")
        
    # Disconnect clients
    await manager.disconnect("doc1", "user1")
    await asyncio.sleep(0.2)
    
    await manager.disconnect("doc1", "user2")
    
    # Give time for cleanup
    await asyncio.sleep(0.3)
    
    await manager.cleanup()
    logger.info("CRDTManager test completed")



async def main():
    """Run tests for both manager types"""
    logger.enable(__name__)
    logger.info("Starting tests")
    
    # await test_chat_room()
    # await asyncio.sleep(1.0)  # Add delay between tests
    await test_crdt_manager()
    
    logger.info("All tests completed")

if __name__ == "__main__":
    asyncio.run(main())

