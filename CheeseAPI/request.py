import socket, asyncio, urllib.parse, hashlib, base64, json, re
from typing import TYPE_CHECKING, Literal, Callable, AsyncIterable

from CheeseAPI.response import Response
from CheeseAPI.file import File

if TYPE_CHECKING:
    from CheeseAPI.app import CheeseAPI
    from CheeseAPI.websocket import Websocket

HTTP_METHOD_TYPE = Literal['CONNECT', 'DELETE', 'GET', 'HEAD', 'OPTIONS', 'PATCH', 'POST', 'PUT', 'TRACE', 'WEBSOCKET']

class Request:
    __slots__ = ('_proxy', '_ip', '_method', '_path', '_params', '_headers', '_query', '_body', '_json', '_form', '_files', '_cookies', '_full_path', '_ranges', '_fn', '_file')

    def __init__(self, app: 'CheeseAPI', client_socket: socket.socket, addr: tuple[str, int]):
        self._proxy: RequestProxy = app.RequestProxy_Class(app, self, client_socket)

        self._ip: str = addr[0]
        self._method: HTTP_METHOD_TYPE | None = None
        self._path: str | None = None
        self._params: dict[str, str] | None = None
        self._headers: dict[str, str] | None = None
        self._query: dict[str, str] | None = None
        self._body: bytes | str | None = None
        self._json: dict | list | None = None
        self._form: dict[str, str] | None = None
        self._files: dict[str, File] | None = None
        self._file: File | None = None
        self._cookies: dict[str, str] | None = None
        self._full_path: str | None = None
        self._ranges: list[tuple[int, int | None]] | None = None
        self._fn: Callable | AsyncIterable | 'Websocket' | None = None

    async def recv_body(self, get_all: bool = False) -> bool | Response:
        '''
        若在路由中设置了 `auto_recv_body = False`，则需要手动调用此方法接收请求体

        - Args:
            - get_all: 是否接收完整请求体。若设置为 `False`，则在接收到部分请求体后立即返回 `False`，直到完整请求体接收完毕才返回 `True`

        - Returns:
            - True: 表示请求体已完整接收
            - False: 表示请求体未完整接收（仅在 `get_all = False` 时可能返回此值）
            - Response: 表示在接收请求体时发生错误，需立即返回此响应
        '''

        return await self._proxy.recv_body(get_all = get_all)

    async def parse_body(self):
        ''' 若在路由中设置了 `auto_recv_body = False`，则需要手动调用此方法解析请求体 '''

        await self._proxy.parse_body()

    @property
    def ip(self) -> str:
        return self._ip

    @property
    def method(self) -> HTTP_METHOD_TYPE | None:
        return self._method

    @property
    def path(self) -> str | None:
        return self._path

    @property
    def params(self) -> dict[str, str] | None:
        return self._params

    @property
    def headers(self) -> dict[str, str] | None:
        return self._headers

    @property
    def query(self) -> dict[str, str] | None:
        return self._query

    @property
    def body(self) -> bytes | str | None:
        return self._body

    @property
    def json(self) -> dict | list | None:
        return self._json

    @property
    def form(self) -> dict[str, str] | None:
        return self._form

    @property
    def files(self) -> dict[str, bytes] | None:
        return self._files

    @property
    def file(self) -> File | None:
        return self._file

    @property
    def cookies(self) -> dict[str, str] | None:
        return self._cookies

    @property
    def full_path(self) -> str | None:
        return self._full_path

    @property
    def ranges(self) -> list[tuple[int, int | None]] | None:
        return self._ranges

    @property
    def fn(self) -> Callable | AsyncIterable | 'Websocket' | None:
        return self._fn

class RequestProxy:
    __slots__ = ('app', 'request', 'client_socket', 'buffer', 'protocol')

    def __init__(self, app: 'CheeseAPI', request: Request, client_socket: socket.socket):
        self.app: 'CheeseAPI' = app
        self.request: Request = request

        self.client_socket: socket.socket = client_socket
        self.buffer: bytes = b''
        self.protocol: Literal['HTTP/1.0', 'HTTP/1.1'] | None = None

    async def recv_headers(self, keep_alive: bool) -> Response | None:
        loop = asyncio.get_event_loop()
        while b'\r\n\r\n' not in self.buffer:
            data = await asyncio.wait_for(loop.sock_recv(self.client_socket, self.app.socket_receive_buffer_size), self.app.keep_alive_timeout if keep_alive else self.app.request_timeout)

            if not data:
                raise ConnectionAbortedError()

            self.buffer += data

    async def parse_headers(self):
        header_data, self.buffer = self.buffer.split(b'\r\n\r\n', 1)
        lines = header_data.decode().split('\r\n')

        base_info = lines[0].split(' ')
        self.request._method = base_info[0]
        if base_info[1].startswith('//'):
            base_info[1] = base_info[1][1:]
        self.request._full_path = base_info[1]
        full_path = urllib.parse.urlparse(base_info[1])
        self.request._path = full_path.path
        self.request._query = dict(urllib.parse.parse_qsl(full_path.query))
        self.protocol = base_info[2] if len(base_info) > 2 else 'HTTP/1.1'

        self.request._headers = {}
        for line in lines[1:]:
            key, value = line.split(': ', 1)
            self.request.headers[key.lower()] = value

        if 'cookie' in self.request.headers:
            self.request._cookies = {}
            for cookie in self.request.headers['cookie'].split(';'):
                key, value = cookie.strip().split('=', 1)
                self.request.cookies[key] = value

        if 'x-real-ip' in self.request.headers:
            self.request._ip = self.request.headers['x-real-ip']
        elif 'x-forwarded-for' in self.request.headers:
            self.request._ip = self.request.headers['x-forwarded-for'].split(',')[0].strip()

        if 'range' in self.request.headers:
            self.request._ranges = []
            for range_part in self.request.headers['range'][6:].split(','):
                range_part = range_part.strip()
                if '-' in range_part:
                    start, end = range_part.split('-', 1)
                    self.request.ranges.append((int(start) if start else 0, int(end) if end else None))

        if 'upgrade' in self.request.headers and self.request.headers['upgrade'] == 'websocket':
            self.request._method = 'WEBSOCKET'

    async def recv_body(self, get_all: bool = False) -> bool | Response | None:
        loop = asyncio.get_event_loop()

        content_length = self.request.headers.get('content-length')
        if content_length:
            self.request._body = self.buffer
            self.buffer = b''
            content_length = int(content_length)
            while len(self.request._body) < content_length:
                data = None
                try:
                    data = await asyncio.wait_for(loop.sock_recv(self.client_socket, self.app.socket_receive_buffer_size), self.app.request_timeout)
                    self.request._body += data
                except asyncio.TimeoutError:
                    raise
                if not data:
                    raise ConnectionAbortedError()
            return True

        is_chunked = self.request.headers.get('transfer-encoding') == 'chunked'
        if is_chunked:
            if self.request._body is None:
                self.request._body = b''

            while True:
                while b'\r\n' not in self.buffer:
                    try:
                        data = await asyncio.wait_for(loop.sock_recv(self.client_socket, self.app.socket_receive_buffer_size), self.app.request_timeout)
                    except asyncio.TimeoutError:
                        raise ConnectionAbortedError()
                    self.buffer += data

                chunk_size, self.buffer = self.buffer.split(b'\r\n', 1)
                try:
                    chunk_size = int(chunk_size.decode().split(';')[0], 16)
                except:
                    return Response(status = 400)

                if chunk_size == 0:
                    if self.request.headers.get('trailer'):
                        while b'\r\n\r\n' not in self.buffer:
                            try:
                                data = await asyncio.wait_for(loop.sock_recv(self.client_socket, self.app.socket_receive_buffer_size), self.app.request_timeout)
                            except asyncio.TimeoutError:
                                return Response(status = 408)
                            if not data:
                                raise ConnectionAbortedError()
                            self.buffer += data

                        trailer, self.buffer = self.buffer.split(b'\r\n\r\n', 1)
                        if trailer and trailer.startswith('content-md5: ') and trailer[13:] not in (base64.b64encode(hashlib.md5(self.request._body).digest()).decode(), hashlib.md5(self.request._body).hexdigest()):
                            return Response(status = 400)

                    self.buffer = b''
                    return True

                chunk_size = chunk_size + 2
                while len(self.buffer) < chunk_size:
                    data = await asyncio.wait_for(loop.sock_recv(self.client_socket, self.app.socket_receive_buffer_size), self.app.request_timeout)
                    if not data:
                        raise ConnectionAbortedError()
                    self.buffer += data

                self.request._body += self.buffer[:chunk_size - 2]
                self.buffer = self.buffer[chunk_size:]
                if not get_all:
                    return False

    async def parse_body(self):
        if self.request.body is None:
            return

        content_type = self.request.headers.get('content-type')
        if content_type == 'text/plain' or content_type is None:
            self.request._body = self.request.body.decode()
        elif content_type == 'application/json':
            self.request._json = json.loads(self.request.body)
        elif content_type == 'application/x-www-form-urlencoded':
            self.request._form = {
                key: value[0] for key, value in urllib.parse.parse_qs(self.request.body.decode()).items()
            }
        elif content_type.startswith('multipart/form-data'):
            for part in self.request.body.split(f'--{content_type.split("boundary=")[1].strip()}'.encode()):
                if part == b'' or part == b'--\r\n':
                    continue

                headers, data = part.split(b'\r\n\r\n', 1)
                if data.endswith(b'\r\n'):
                    data = data[:-2]

                name = None
                filename = None
                for line in headers.decode().strip().split('\r\n'):
                    if line.startswith('content-disposition:'):
                        name_match = re.search(r'name="([^"]*)"', line)
                        if name_match:
                            name = name_match.group(1)

                        filename_match = re.search(r'filename="([^"]*)"', line)
                        if filename_match:
                            filename = filename_match.group(1)
                        break

                if name:
                    if filename:
                        if self.request._files is None:
                            self.request._files = {}
                        self.request._files[name] = File(filename, data)
                    else:
                        if self.request._form is None:
                            self.request._form = {}
                        self.request._form[name] = data.decode()

        if self.request.headers.get('content-disposition'):
            match = re.search(r'filename="([^"]*)"', self.request.headers['content-disposition'])
            if match:
                self.request._file = File(match.group(1), self.request.body)
