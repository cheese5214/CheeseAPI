# **Websocket**

```python
from CheeseAPI import CheeseAPI, Websocket, Response

app = CheeseAPI()
# app = CheeseAPI(sync_server_url = 'redis://0.0.0.0:6379/0', workers = os.cpu_count()) 分布式需要配置 sync_server_url 以共享数据

@app.route.websocket('/')
class DefaultWebsocket(Websocket):
    async def on_connect(self):
        ...

    async def on_message(self, message: str | bytes):
        ...

    async def on_disconnect(self):
        ...
```

## **`connector: dict[str, list[Self]]`**

当前连接的客户端列表；该数据暂时不支持分布式环境

## **`def send(path: str, data: bytes | list | str | dict, *, websocket_key_or_keys: str | list[str] | None = None)`**

向指定路径的客户端发送数据；若未指定 `websocket_key_or_keys` 则向所有连接的客户端发送数据

## **`async def async_send(path: str, data: bytes | list | str | dict, *, websocket_key_or_keys: str | list[str] | None = None)`**
向指定路径的客户端发送数据；若未指定 `websocket_key_or_keys` 则向所有连接的客户端发送数据

## **`def close(path: str, code: int = 1000, message: str = '', *, websocket_key_or_keys: str | list[str] | None = None)`**

关闭指定路径的客户端连接；若未指定 `websocket_key_or_keys` 则关闭所有连接的客户端

## **`async def async_close(path: str, code: int = 1000, message: str = '', *, websocket_key_or_keys: str | list[str] | None = None)`**

关闭指定路径的客户端连接；若未指定 `websocket_key_or_keys` 则关闭所有连接的客户端

## **`self.request: Request`**

## **`self.key: str`**

## **`self.subprotocols: list[str] | None`**

## **`self.subprotocol: str | None`**

## **`self.is_running: bool`**

## **`async def on_connect(self)`**

## **`async def on_subprotocol(self, subprotocols: list[str]) -> str | None`**

## **`async def on_message(self, data: str | bytes)`**

## **`async def on_disconnect(self)`**

## **`async def on_ping(self)`**

## **`async def on_pong(self)`**

## **`async def ping(self)`**

## **`async def pong(self)`**

## **`async def send(self, data: bytes | list | str | dict)`**

## **`async def close(self, code: int = 1000, message: str = '')`**