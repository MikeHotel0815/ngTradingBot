"""
Redis Client for ngTradingBot
Handles caching, command queue, and pub/sub
"""

import redis
import json
import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)

class RedisClient:
    def __init__(self, url=None):
        """Initialize Redis connection"""
        self.url = url or os.getenv('REDIS_URL')
        if not self.url:
            raise ValueError("REDIS_URL environment variable is required")
        self.client = None
        self.pubsub = None
        self.connect()

    def connect(self):
        """Connect to Redis"""
        try:
            self.client = redis.from_url(
                self.url,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_keepalive=True
            )
            self.client.ping()
            logger.info(f"Connected to Redis at {self.url}")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise

    def disconnect(self):
        """Disconnect from Redis"""
        if self.client:
            self.client.close()
            logger.info("Disconnected from Redis")

    # ========================================================================
    # COMMAND QUEUE
    # ========================================================================

    def push_command(self, account_id, command_data):
        """
        Push command to account's command queue
        RPUSH for FIFO queue
        """
        queue_key = f"commands:account:{account_id}"
        command_json = json.dumps(command_data)
        self.client.rpush(queue_key, command_json)

        # Set expiry on queue to prevent buildup
        self.client.expire(queue_key, 3600)  # 1 hour

        # Publish notification for instant delivery
        self.client.publish(f"commands:notify:{account_id}", "new_command")

        logger.info(f"Pushed command {command_data.get('id')} to queue for account {account_id}")

    def pop_command(self, account_id):
        """
        Pop command from account's command queue
        LPOP for FIFO
        Returns dict or None
        """
        queue_key = f"commands:account:{account_id}"
        command_json = self.client.lpop(queue_key)

        if command_json:
            return json.loads(command_json)
        return None

    def get_pending_commands(self, account_id):
        """Get all pending commands without removing them"""
        queue_key = f"commands:account:{account_id}"
        commands_json = self.client.lrange(queue_key, 0, -1)
        return [json.loads(cmd) for cmd in commands_json]

    def clear_command_queue(self, account_id):
        """Clear all commands for an account"""
        queue_key = f"commands:account:{account_id}"
        self.client.delete(queue_key)

    # ========================================================================
    # ACCOUNT STATE CACHING
    # ========================================================================

    def cache_account_state(self, account_id, state_data, ttl=300):
        """
        Cache account state (balance, equity, margin, etc.)
        TTL default: 5 minutes
        """
        cache_key = f"account:state:{account_id}"
        self.client.setex(
            cache_key,
            ttl,
            json.dumps(state_data)
        )

    def get_account_state(self, account_id):
        """Get cached account state"""
        cache_key = f"account:state:{account_id}"
        state_json = self.client.get(cache_key)

        if state_json:
            return json.loads(state_json)
        return None

    def update_account_field(self, account_id, field, value):
        """Update a single field in account state"""
        cache_key = f"account:state:{account_id}"

        # Get current state
        state = self.get_account_state(account_id) or {}

        # Update field
        state[field] = value
        state['last_update'] = datetime.utcnow().isoformat()

        # Save back
        self.cache_account_state(account_id, state)

    # ========================================================================
    # TICK DATA BUFFERING
    # ========================================================================

    def buffer_tick(self, account_id, symbol, tick_data):
        """
        Buffer tick data for batch processing
        Uses Redis list with TTL (5 minutes)
        """
        buffer_key = f"ticks:buffer:{account_id}:{symbol}"
        tick_json = json.dumps(tick_data)

        # Add to buffer
        self.client.rpush(buffer_key, tick_json)

        # Set TTL (5 minutes - prevents unbounded growth)
        self.client.expire(buffer_key, 300)

    def get_tick_buffer(self, account_id, symbol, clear=True):
        """
        Get all buffered ticks for symbol
        Optionally clear buffer after reading
        """
        buffer_key = f"ticks:buffer:{account_id}:{symbol}"

        if clear:
            # Atomic get and delete
            pipe = self.client.pipeline()
            pipe.lrange(buffer_key, 0, -1)
            pipe.delete(buffer_key)
            results = pipe.execute()
            ticks_json = results[0]
        else:
            ticks_json = self.client.lrange(buffer_key, 0, -1)

        return [json.loads(tick) for tick in ticks_json]

    def get_buffer_size(self, account_id, symbol):
        """Get number of ticks in buffer"""
        buffer_key = f"ticks:buffer:{account_id}:{symbol}"
        return self.client.llen(buffer_key)

    def buffer_ticks_batch(self, account_id, ticks):
        """
        Buffer multiple ticks at once (more efficient)

        Args:
            account_id: Account ID
            ticks: List of tick dicts with 'symbol' field
        """
        if not ticks:
            return

        # Group ticks by symbol
        by_symbol = {}
        for tick in ticks:
            symbol = tick.get('symbol')
            if symbol:
                if symbol not in by_symbol:
                    by_symbol[symbol] = []
                by_symbol[symbol].append(tick)

        # Use pipeline for efficiency
        pipe = self.client.pipeline()

        for symbol, symbol_ticks in by_symbol.items():
            buffer_key = f"ticks:buffer:{account_id}:{symbol}"

            # Add all ticks for this symbol
            for tick in symbol_ticks:
                pipe.rpush(buffer_key, json.dumps(tick))

            # Set TTL (5 minutes)
            pipe.expire(buffer_key, 300)

        # Execute all commands at once
        pipe.execute()

    def get_all_buffered_symbols(self, account_id):
        """Get list of symbols that have buffered ticks"""
        pattern = f"ticks:buffer:{account_id}:*"
        keys = self.client.keys(pattern)

        # Extract symbol names
        symbols = []
        prefix = f"ticks:buffer:{account_id}:"
        for key in keys:
            if key.startswith(prefix):
                symbol = key[len(prefix):]
                symbols.append(symbol)

        return symbols

    def get_all_buffers(self, account_id, clear=True):
        """
        Get all buffered ticks for all symbols
        Returns dict: {symbol: [ticks]}
        """
        symbols = self.get_all_buffered_symbols(account_id)

        result = {}
        for symbol in symbols:
            ticks = self.get_tick_buffer(account_id, symbol, clear=clear)
            if ticks:
                result[symbol] = ticks

        return result

    def get_total_buffer_size(self, account_id):
        """Get total number of buffered ticks across all symbols"""
        symbols = self.get_all_buffered_symbols(account_id)
        total = 0

        for symbol in symbols:
            total += self.get_buffer_size(account_id, symbol)

        return total

    # ========================================================================
    # PUB/SUB
    # ========================================================================

    def publish_command_response(self, command_id, response_data):
        """Publish command response for WebSocket broadcast"""
        channel = f"command:response:{command_id}"
        self.client.publish(channel, json.dumps(response_data))

    def publish_account_update(self, account_id, update_data):
        """Publish account update for WebSocket broadcast"""
        channel = f"account:updates:{account_id}"
        self.client.publish(channel, json.dumps(update_data))

    def subscribe_to_channel(self, channel):
        """Subscribe to a pub/sub channel"""
        if not self.pubsub:
            self.pubsub = self.client.pubsub()
        self.pubsub.subscribe(channel)
        return self.pubsub

    # ========================================================================
    # STATISTICS & MONITORING
    # ========================================================================

    def increment_counter(self, key, amount=1):
        """Increment a counter"""
        return self.client.incr(key, amount)

    def get_counter(self, key):
        """Get counter value"""
        val = self.client.get(key)
        return int(val) if val else 0

    def set_with_expiry(self, key, value, ttl):
        """Set key with TTL"""
        self.client.setex(key, ttl, value)

    def get(self, key):
        """Get key"""
        return self.client.get(key)

    def delete(self, key):
        """Delete key"""
        return self.client.delete(key)

    def keys(self, pattern):
        """Get keys matching pattern"""
        return self.client.keys(pattern)

    def flushall(self):
        """Clear all Redis data (use with caution!)"""
        self.client.flushall()
        logger.warning("Redis flushed - all data cleared")


# Global Redis instance
_redis_client = None

def get_redis():
    """Get global Redis client instance"""
    global _redis_client
    if _redis_client is None:
        _redis_client = RedisClient()
    return _redis_client

def init_redis(url=None):
    """Initialize Redis client"""
    global _redis_client
    _redis_client = RedisClient(url)
    return _redis_client
