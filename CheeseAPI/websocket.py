import base64, hashlib, asyncio, ssl, struct, json
from functools import partial
from typing import TYPE_CHECKING, AsyncIterable, Self, Callable

import redis

from CheeseAPI.response import Response

if TYPE_CHECKING:
    from CheeseAPI.request import Request
    from CheeseAPI.app import CheeseAPI

class DualMethod:
    def __init__(self, static_func, instance_func):
        self.static_func = static_func
        self.instance_func = instance_func

    def __get__(self, instance, _):
        if instance is None:
            return self.static_func
        else:
            return partial(self.instance_func, instance)

class Websocket:
    connectors: dict[str, list[Self]] = {}
    ''' 当前连接的客户端列表；该数据暂时不支持分布式环境 '''

    @staticmethod
    def _static_send(path: str, data: bytes | list | str | dict, *, websocket_key_or_keys: str | list[str] | None = None):
        WebsocketProxy._static_send(path, data, websocket_key_or_keys = websocket_key_or_keys)

    @staticmethod
    async def async_send(path: str, data: bytes | list | str | dict, *, websocket_key_or_keys: str | list[str] | None = None):
        await WebsocketProxy.async_send(path, data, websocket_key_or_keys = websocket_key_or_keys)

    @staticmethod
    def _static_close(path: str, code: int = 1000, message: str = '', *, websocket_key_or_keys: str | list[str] | None = None):
        WebsocketProxy._static_close(path, code, message, websocket_key_or_keys = websocket_key_or_keys)

    @staticmethod
    async def async_close(path: str, code: int = 1000, message: str = '', *, websocket_key_or_keys: str | list[str] | None = None):
        await WebsocketProxy.async_close(path, code, message, websocket_key_or_keys = websocket_key_or_keys)

    __slots__ = ('_request', '_key', '_subprotocols', '_subprotocol', '_proxy', 'response', '_is_running')

    def __init__(self, request: 'Request'):
        self._request: 'Request' = request

        self._proxy: 'WebsocketProxy' = request._proxy.app.WebsocketProxy_Class(request._proxy.app, self)
        self._key: str = self.request.headers.get('Sec-WebSocket-Key')
        subprotocols = self.request.headers.get('Sec-WebSocket-Protocol')
        self._subprotocols: list[str] | None = subprotocols.strip().split(',') if subprotocols else None
        self._subprotocol: str | None = None
        self.response: Response | None = None
        self._is_running: bool = False

    async def on_connect(self):
        ...

    async def on_subprotocol(self, subprotocols: list[str]) -> str | None:
        ...

    async def on_message(self, data: str | bytes):
        ...

    async def on_disconnect(self):
        ...

    async def on_ping(self):
        ...

    async def on_pong(self):
        ...

    async def ping(self):
        await self._proxy.ping()

    async def pong(self):
        await self._proxy.pong()

    async def _instance_send(self, data: bytes | list | str | dict, **kwargs):
        await self._proxy._instance_send(data, **kwargs)

    async def _instance_close(self, code: int = 1000, message: str = ''):
        await self._proxy._instance_close(code, message)

    @property
    def request(self) -> 'Request':
        return self._request

    @property
    def key(self) -> str:
        return self._key

    @property
    def subprotocols(self) -> list[str] | None:
        return self._subprotocols

    @property
    def subprotocol(self) -> str | None:
        return self._subprotocol

    @property
    def is_running(self) -> bool:
        return self._is_running

    send = DualMethod(_static_send, _instance_send)
    close = DualMethod(_static_close, _instance_close)

class WebsocketProxy:
    sync_server: dict[str, redis.asyncio.Redis] | None = None
    sync_servers: tuple[redis.Redis, redis.asyncio.Redis] | None = None
    data_encode: Callable | None = None
    data_decode: Callable | None = None

    @staticmethod
    def _static_send(path: str, data: bytes | list | str | dict, *, websocket_key_or_keys: str | list[str] | None = None):
        if WebsocketProxy.sync_servers is not None:
            data = json.dumps({
                'data': data,
                'key': websocket_key_or_keys,
                'event': 'send'
            }).encode()
            if WebsocketProxy.data_encode is not None:
                data = WebsocketProxy.data_encode(data)
            WebsocketProxy.sync_servers[0].publish(path, data)
        elif path in Websocket.connectors:
            if websocket_key_or_keys is None:
                for connector in Websocket.connectors[path]:
                    connector.send(data)
            elif isinstance(websocket_key_or_keys, str):
                for connector in Websocket.connectors[path]:
                    if connector.key == websocket_key_or_keys:
                        connector.send(data)
                        break
            elif isinstance(websocket_key_or_keys, list):
                for connector in Websocket.connectors[path]:
                    if connector.key in websocket_key_or_keys:
                        connector.send(data)

    @staticmethod
    async def async_send(path: str, data: bytes | list | str | dict, *, websocket_key_or_keys: str | list[str] | None = None):
        if WebsocketProxy.sync_servers is not None:
            data = json.dumps({
                'data': data,
                'key': websocket_key_or_keys,
                'event': 'send'
            }).encode()
            if WebsocketProxy.data_encode is not None:
                data = WebsocketProxy.data_encode(data)
            await WebsocketProxy.sync_servers[1].publish(path, data)
        elif path in Websocket.connectors:
            if websocket_key_or_keys is None:
                tasks = [connector.send(data) for connector in Websocket.connectors[path]]
            elif isinstance(websocket_key_or_keys, str):
                tasks = [connector.send(data) for connector in Websocket.connectors[path] if connector.key == websocket_key_or_keys]
            elif isinstance(websocket_key_or_keys, list):
                tasks = [connector.send(data) for connector in Websocket.connectors[path] if connector.key in websocket_key_or_keys]
            await asyncio.gather(*tasks)

    @staticmethod
    def _static_close(path: str, code: int = 1000, message: str = '', *, websocket_key_or_keys: str | list[str] | None = None):
        if WebsocketProxy.sync_servers is not None:
            data = json.dumps({
                'key': websocket_key_or_keys,
                'event': 'close'
            }).encode()
            if WebsocketProxy.data_encode is not None:
                data = WebsocketProxy.data_encode(data)
            WebsocketProxy.sync_servers[0].publish(path, data)
        elif path in Websocket.connectors:
            if websocket_key_or_keys is None:
                for connector in Websocket.connectors[path]:
                    connector.close(code, message)
            elif isinstance(websocket_key_or_keys, str):
                for connector in Websocket.connectors[path]:
                    if connector.key == websocket_key_or_keys:
                        connector.close(code, message)
                        break
            elif isinstance(websocket_key_or_keys, list):
                for connector in Websocket.connectors[path]:
                    if connector.key in websocket_key_or_keys:
                        connector.close(code, message)

    @staticmethod
    async def async_close(path: str, code: int = 1000, message: str = '', *, websocket_key_or_keys: str | list[str] | None = None):
        if WebsocketProxy.sync_servers is not None:
            data = json.dumps({
                'key': websocket_key_or_keys,
                'event': 'close'
            }).encode()
            if WebsocketProxy.data_encode is not None:
                data = WebsocketProxy.data_encode(data)
            await WebsocketProxy.sync_servers[1].publish(path, data)
        elif path in Websocket.connectors:
            if websocket_key_or_keys is None:
                tasks = [connector.close(code, message) for connector in Websocket.connectors[path]]
            elif isinstance(websocket_key_or_keys, str):
                tasks = [connector.close(code, message) for connector in Websocket.connectors[path] if connector.key == websocket_key_or_keys]
            elif isinstance(websocket_key_or_keys, list):
                tasks = [connector.close(code, message) for connector in Websocket.connectors[path] if connector.key in websocket_key_or_keys]
            await asyncio.gather(*tasks)

    def __init__(self, app: 'CheeseAPI', websocket: Websocket):
        self.app: 'CheeseAPI' = app
        self.websocket: Websocket = websocket

        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None

    async def running(self) -> AsyncIterable[Response]:
        try:
            await self.connect()
            await self.message()
            await self.disconnect()
        except Exception as e:
            await self.app.printer.websocket_error(self.websocket, e)

    async def get_response(self) -> Response:
        headers = {
            'Upgrade': 'websocket',
            'Connection': 'Upgrade',
            'Sec-WebSocket-Accept': base64.b64encode(hashlib.sha1(f'{self.websocket.key}258EAFA5-E914-47DA-95CA-C5AB0DC85B11'.encode('utf-8')).digest()).decode('utf-8')
        }
        if self.websocket.subprotocols:
            subprotocol = await self.websocket.on_subprotocol(self.websocket.subprotocols)
            if subprotocol:
                self.websocket._subprotocol = subprotocol
                headers['Sec-WebSocket-Protocol'] = subprotocol
        response = self.app.ResponseProxy_Class(self.app, Response(status = 101, headers = headers)).response
        response._proxy.websocket = self.websocket
        return response

    async def connect(self) -> AsyncIterable[Response]:
        Websocket.connectors.setdefault(self.websocket.request.path, []).append(self.websocket)
        if self.app.sync_server_url:
            if WebsocketProxy.sync_server is None:
                WebsocketProxy.sync_server = {}
            if self.websocket.request.path not in WebsocketProxy.sync_server:
                WebsocketProxy.sync_server[self.websocket.request.path] = redis.asyncio.Redis.from_url(self.app.sync_server_url)
                asyncio.create_task(self.sync_server_running())

        loop = asyncio.get_running_loop()
        self.reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(self.reader)
        if isinstance(self.websocket.request._proxy.client_socket, ssl.SSLSocket):
            await loop.sock_sendall(self.websocket.request._proxy.client_socket, b'')
        transport, _ = await loop.connect_accepted_socket(lambda: protocol, self.websocket.request._proxy.client_socket)
        self.writer = asyncio.StreamWriter(transport, protocol, self.reader, loop)
        self.websocket._is_running = True

        self.app.printer.websocket_connect(self.websocket)
        await self.websocket.on_connect()

    async def sync_server_running(self):
        if self.app.sync_server_url.startswith('redis'):
            pubsub = WebsocketProxy.sync_server[self.websocket.request.path].pubsub()
            await pubsub.subscribe(self.websocket.request.path)
            async for message in pubsub.listen():
                if message['type'] != 'message':
                    continue

                connectors = Websocket.connectors.get(self.websocket.request.path)
                if not connectors:
                    continue

                message = message['data']
                if WebsocketProxy.data_decode is not None:
                    message = WebsocketProxy.data_decode(message)
                message = json.loads(message.decode())
                if isinstance(message['key'], list):
                    connectors = [connector for connector in connectors if connector.key in message['key']]
                elif isinstance(message['key'], str):
                    connectors = [connector for connector in connectors if connector.key == message['key']]
                else:
                    connectors = [connector for connector in connectors]

                if connectors:
                    if message['event'] == 'send':
                        for connector in connectors:
                            asyncio.create_task(connector.send(message['data']))
                    elif message['event'] == 'close':
                        for connector in connectors:
                            asyncio.create_task(connector.close())

    async def message(self):
        while True:
            opcode, data = await self.decode()
            if opcode is None:
                break

            if opcode == 0x1:
                try:
                    await self.websocket.on_message(data.decode())
                except Exception as e:
                    await self.app.printer.websocket_message_error(e, self.websocket)
            elif opcode == 0x2:
                try:
                    await self.websocket.on_message(data)
                except Exception as e:
                    await self.app.printer.websocket_message_error(e, self.websocket)
            elif opcode == 0x8:
                break
            elif opcode == 0x9:
                await self.websocket.on_ping()
            elif opcode == 0xA:
                await self.websocket.on_pong()

    async def disconnect(self):
        self.websocket._is_running = False
        Websocket.connectors[self.websocket.request.path].remove(self.websocket)
        self.app.printer.websocket_disconnect(self.websocket)
        await self.websocket.on_disconnect()
        if self.writer:
            self.writer.close()
            await self.writer.wait_closed()

    def encode(self, opcode: int, data: bytes) -> bytes:
        _bytes = bytearray()
        _bytes.append(0x80 | opcode)

        length = len(data)
        if length < 126:
            _bytes.append(length)
        elif length < 65536:
            _bytes.append(126)
            _bytes.extend(struct.pack('!H', length))
        else:
            _bytes.append(127)
            _bytes.extend(struct.pack('!Q', length))

        return bytes(_bytes) + data

    async def decode(self) -> tuple[int, bytes]:
        full_payload = b''
        opcode = None
        try:
            while True:
                try:
                    header = await asyncio.wait_for(self.reader.readexactly(2), self.app.request_timeout)
                except asyncio.exceptions.IncompleteReadError:
                    return opcode, full_payload

                fin = bool(header[0] & 0x80)
                if opcode is None:
                    opcode = header[0] & 0x0F
                payload_length = header[1] & 0x7F
                if payload_length == 126:
                    extended = await asyncio.wait_for(self.reader.readexactly(2), self.app.request_timeout)
                    payload_length = struct.unpack('!H', extended)[0]
                elif payload_length == 127:
                    extended = await asyncio.wait_for(self.reader.readexactly(8), self.app.request_timeout)
                    payload_length = struct.unpack('!Q', extended)[0]

                mask = b''
                if bool(header[1] & 0x80):
                    mask = await asyncio.wait_for(self.reader.readexactly(4), self.app.request_timeout)

                payload = await asyncio.wait_for(self.reader.readexactly(payload_length), self.app.request_timeout)
                if mask:
                    payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))

                full_payload += payload

                if fin:
                    return opcode, full_payload
        except asyncio.TimeoutError:
            return opcode, full_payload

    async def _instance_send(self, data: bytes | list | str | dict, **kwargs):
        if isinstance(data, str):
            self.writer.write(self.encode(0x1, data.encode()))
        elif isinstance(data, bytes):
            self.writer.write(self.encode(0x2, data))
        else:
            self.writer.write(self.encode(0x1, json.dumps(data).encode()))
        await self.writer.drain()

    async def _instance_close(self, code: int = 1000, message: str = ''):
        self.writer.write(self.encode(0x8, struct.pack('!H', code) + message.encode('utf-8')))
        await self.writer.drain()

    async def ping(self):
        self.writer.write(self.encode(0x9, b''))
        await self.writer.drain()

    async def pong(self):
        self.writer.write(self.encode(0xA, b''))
        await self.writer.drain()
