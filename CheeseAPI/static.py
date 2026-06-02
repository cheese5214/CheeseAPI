from typing import Callable, TYPE_CHECKING

if TYPE_CHECKING:
    import redis

websocket_sync_server: dict[str, 'redis.asyncio.Redis'] | None = None
websocket_sync_servers: tuple['redis.ConnectionPool', 'redis.asyncio.ConnectionPool'] | None = None
websocket_data_encode: Callable | None = None
websocket_data_decode: Callable | None = None
scheduler_sync_servers: tuple['redis.ConnectionPool', 'redis.asyncio.ConnectionPool'] | None = None