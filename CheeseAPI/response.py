import socket, asyncio, datetime, json, zlib, gzip, os, mimetypes, uuid, math
from typing import TYPE_CHECKING, TypedDict, Literal, AsyncIterable

import brotli, zstandard

from CheeseAPI.file import File

if TYPE_CHECKING:
    from CheeseAPI.app import CheeseAPI
    from CheeseAPI.request import Request
    from CheeseAPI.websocket import Websocket

HTTP_STATUS = {
    100: 'Continue',
    101: 'Switching Protocols',
    102: 'Processing',
    200: 'OK',
    201: 'Created',
    202: 'Accepted',
    203: 'Non-Authoritative Information',
    204: 'No Content',
    205: 'Reset Content',
    206: 'Partial Content',
    207: 'Multi-Status',
    208: 'Already Reported',
    226: 'IM Used',
    300: 'Multiple Choices',
    301: 'Moved Permanently',
    302: 'Found',
    303: 'See Other',
    304: 'Not Modified',
    305: 'Use Proxy',
    307: 'Temporary Redirect',
    308: 'Permanent Redirect',
    400: 'Bad Request',
    401: 'Unauthorized',
    402: 'Payment Required',
    403: 'Forbidden',
    404: 'Not Found',
    405: 'Method Not Allowed',
    406: 'Not Acceptable',
    407: 'Proxy Authentication Required',
    408: 'Request Timeout',
    409: 'Conflict',
    410: 'Gone',
    411: 'Length Required',
    412: 'Precondition Failed',
    413: 'Payload Too Large',
    414: 'URI Too Long',
    415: 'Unsupported Media Type',
    416: 'Range Not Satisfiable',
    417: 'Expectation Failed',
    418: 'I\'m a teapot',
    421: 'Misdirected Request',
    422: 'Unprocessable Entity',
    423: 'Locked',
    424: 'Failed Dependency',
    425: 'Too Early',
    426: 'Upgrade Required',
    428: 'Precondition Required',
    429: 'Too Many Requests',
    431: 'Request Header Fields Too Large',
    451: 'Unavailable For Legal Reasons',
    500: 'Internal Server Error',
    501: 'Not Implemented',
    502: 'Bad Gateway',
    503: 'Service Unavailable',
    504: 'Gateway Timeout',
    505: 'HTTP Version Not Supported',
    506: 'Variant Also Negotiates',
    507: 'Insufficient Storage',
    508: 'Loop Detected',
    510: 'Not Extended',
    511: 'Network Authentication Required'
}
NO_BODY_STATUS = (100, 101, 102, 204, 304)
PREVIEWABLE_TYPES = ('text/plain', 'text/html', 'text/css', 'text/javascript', 'application/json', 'application/xml', 'text/xml', 'image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'image/svg+xml', 'image/webp', 'image/bmp', 'video/mp4', 'video/webm', 'video/ogg', 'audio/mpeg', 'audio/ogg', 'audio/wav', 'audio/webm', 'application/pdf')
MERGE_TYPES = {
    'audio/x-wav': 'audio/wav',
    'audio/vnd.wave': 'audio/wav'
}

class Cookie(TypedDict):
    value: str
    expires: datetime.datetime | None
    max_age: int | None
    domain: str | None
    secure: bool | None
    http_only: bool | None

class Response:
    __slots__ = ('status', '_proxy', 'body', 'headers', 'cookies', 'high_precision_date', 'compress', 'compress_level')

    def __init__(self, body: dict | list | str | bytes | AsyncIterable | None = None, status: int = 200, headers: dict[str, str] | None = None, *, high_precision_date: bool = False, compress: Literal['gzip', 'deflate', 'br', 'zstd'] | None = None, compress_level: int | None = None):
        '''
        - Args
            - body: 当为 `AsyncIterable` 时，自动使用 chunked 传输编码
            - headers: 若某些特殊 headers 被设置，则不会被框架自动处理
            - high_precision_date: 是否使用高精度时间戳
            - compress: 强制使用的压缩算法，若不指定则根据请求头自动协商
            - compress_level: 压缩等级；每种算法的取值范围不同，请参考相应文档
        '''

        self.status: int = status
        self.body: dict | list | str | bytes | AsyncIterable | None = body
        self.headers: dict[str, str] = headers if headers is not None else {}
        self.cookies: dict[str, Cookie] = {}
        self.high_precision_date: bool = high_precision_date
        self.compress: Literal['gzip', 'deflate', 'br', 'zstd'] | None = compress
        self.compress_level: int | None = compress_level

        self._proxy: ResponseProxy | None = None

    def set_cookie(self, key: str, value: str, expires: datetime.datetime | None = None, max_age: int | None = None, domain: str | None = None, secure: bool | None = None, http_only: bool | None = None):
        self.cookies[key] = {
            'value': value,
            'expires': expires,
            'max_age': max_age,
            'domain': domain,
            'secure': secure,
            'http_only': http_only
        }

class RedirectResponse(Response):
    def __init__(self, location: str, status: Literal[301, 302, 303, 307, 308] = 302, headers: dict[str, str] | None = None, body: bytes | str | list | dict | None = None):
        if headers is None:
            headers = {}
        headers['location'] = location

        super().__init__(status, body, headers)

class FileResponse(Response):
    __slots__ = ('file', 'preview', 'transmission_type', 'chunked_size')

    def __init__(self, file_path_or_file: str | File, *, status: int = 200, headers: dict[str, str] | None = None , preview: bool = True, transmission_type: Literal['CONTENT_LENGTH', 'CHUNKED'] = 'CONTENT_LENGTH', chunked_size: int | None = None, compress: Literal['gzip', 'deflate', 'br', 'zstd'] | None = None, compress_level: int | None = None):
        '''
        - Args
            - preview: 优先预览文件
            - transmission_type: 传输方式，'CONTENT_LENGTH' 使用 Content-Length 头，'CHUNKED' 使用分块传输编码
            - chunked_size: 分块传输时每块的大小
        '''

        super().__init__(status = status, headers = headers, compress = compress, compress_level = compress_level)

        self.file: File = File(file_path_or_file) if isinstance(file_path_or_file, str) else file_path_or_file
        self.preview: bool = preview
        self.transmission_type: Literal['CONTENT_LENGTH', 'CHUNKED'] = transmission_type
        self.chunked_size: int | None = chunked_size

class ResponseProxy:
    __slots__ = ('app', 'response', 'request', 'websocket')

    def __init__(self, app: 'CheeseAPI', response: Response):
        self.app: 'CheeseAPI' = app
        self.response: Response = response
        self.response._proxy = self

        self.request: 'Request' | None = None
        self.websocket: 'Websocket' | None = None

    async def send(self, client_socket: socket.socket):
        loop = asyncio.get_event_loop()
        no_body = self.response.status in NO_BODY_STATUS or (self.request and self.request.method == 'HEAD')

        status, headers, body = await self.get_status(self.response.status, self.response.headers, self.response.body)
        status, headers, body = await self.get_headers(status, headers, body)
        gen = self.get_body(status, headers, body)
        if not no_body:
            status, headers, data = await anext(gen)

        bytes = [f'HTTP/1.1 {status} {HTTP_STATUS[status]}']
        bytes.extend(f'{key}: {value}' for key, value in headers.items())
        bytes.extend(['', ''])
        bytes = '\r\n'.join(bytes).encode()
        if not no_body:
            if self.response.headers.get('transfer-encoding') == 'chunked':
                bytes += hex(len(data)).encode() + b'\r\n' + data + b'\r\n'
            else:
                bytes += data
        await loop.sock_sendall(client_socket, bytes)

        if not no_body:
            if self.response.headers.get('transfer-encoding') == 'chunked':
                async for _, _, data in gen:
                    await loop.sock_sendall(client_socket, hex(len(data)).encode() + b'\r\n' + data + b'\r\n')
                await loop.sock_sendall(client_socket, b'0\r\n\r\n')
            elif self.request.ranges:
                async for _, _, data in gen:
                    await loop.sock_sendall(client_socket, data)

        if self.request.method != 'WEBSOCKET':
            self.app.printer.response(self.request, self.response)

    async def get_status(self, status: int, headers: dict[str, str], body: dict | list | str | bytes | None) -> tuple[int, dict[str, str], dict | list | str | bytes | None]:
        if isinstance(self.response, FileResponse):
            if self.request.headers.get('range') is not None:
                max_range = -1
                for range in self.request.ranges:
                    if range[1] is not None:
                        max_range = max(max_range, range[1])
                max_range += 1
                if self.response.file._data is not None:
                    if len(self.response.file.data) < max_range:
                        status = 416
                else:
                    if os.path.getsize(self.response.file.path) < max_range:
                        status = 416

        return status, headers, body

    async def file_response_chunked_body(self) -> AsyncIterable[bytes]:
        self.response: FileResponse
        if self.response.file._data is None:
            with open(self.response.file.path, 'rb') as f:
                while True:
                    chunk = f.read(self.response.chunked_size)
                    if not chunk:
                        break

                    yield chunk
        else:
            for i in range(0, len(self.response.file.data), self.response.chunked_size):
                yield self.response.file.data[i:i + self.response.chunked_size]

    async def get_headers(self, status: int, headers: dict[str, str], body: dict | list | str | bytes | None) -> tuple[int, dict[str, str], dict | list | str | bytes | None]:
        if isinstance(self.response, FileResponse):
            if self.response.transmission_type == 'CONTENT_LENGTH':
                body = self.response.file.data
            elif self.response.transmission_type == 'CHUNKED':
                body = self.file_response_chunked_body()

            if 'content-type' not in headers and 'content-disposition' not in headers:
                mime_type = mimetypes.guess_type(self.response.file.name)[0] or 'application/octet-stream'
                if mime_type in MERGE_TYPES:
                    mime_type = MERGE_TYPES[mime_type]
                headers['content-type'] = f'{mime_type}; charset=utf-8'
                headers['content-disposition'] = f'{"inline" if self.response.preview and mime_type in PREVIEWABLE_TYPES else "attachment"}; filename="{self.response.file.name}"'

        if isinstance(self.response.body, AsyncIterable):
            if 'transfer-encoding' not in headers:
                headers['transfer-encoding'] = 'chunked'

        if 'date' not in headers:
            now = datetime.datetime.now(datetime.timezone.utc)
            headers['date'] = (now.strftime('%a, %d %b %Y %H:%M:%S.') + f'{now.microsecond:06d} GMT') if self.response.high_precision_date else now.strftime('%a, %d %b %Y %H:%M:%S GMT')

        if 'connection' not in headers:
            if self.app.keep_alive and self.request and ((self.request._proxy.protocol == 'HTTP/1.1' and self.request.headers.get('connection', '') != 'close') or (self.request._proxy.protocol == 'HTTP/1.0' and self.request.headers.get('connection', '') == 'keep-alive')):
                headers['connection'] = 'keep-alive'
                headers['keep-alive'] = f'timeout={self.app.keep_alive_timeout}, max={self.app.keep_alive_max_requests}'
            else:
                headers['connection'] = 'close'

        if self.request.ranges:
            if status == 206:
                headers.setdefault('accept-ranges', 'bytes')
        else:
            encodings = []
            encoding_quality = False
            if self.app.compress and self.request and self.request.headers and self.request.headers.get('accept-encoding'):
                for encoding in self.request.headers.get('accept-encoding').split(','):
                    encoding_split = encoding.strip().split(';')
                    if len(encoding_split) == 1:
                        encoding_split.append(1)
                    else:
                        encoding_quality = True
                        encoding_split[1] = float(encoding_split[1].split('=')[1])
                    encodings.append(encoding_split)
                encodings.sort(key = lambda x: float(x[1]), reverse = True)
                encodings = [encoding[0] for encoding in encodings]

            if self.response.compress is not None:
                headers.setdefault('content-encoding', self.response.compress)
            elif encodings:
                if encoding_quality is True:
                    for encoding in encodings:
                        if encoding in self.app.compress:
                            headers.setdefault('content-encoding', encoding)
                            break
                        if encoding == '*':
                            headers.setdefault('content-encoding', self.app.compress[0])
                            break
                else:
                    if encodings[0] == '*':
                        headers.setdefault('content-encoding', self.app.compress[0])
                    else:
                        for encoding in self.app.compress:
                            if encoding in encodings:
                                headers.setdefault('content-encoding', encoding)
                                break

        if self.response.cookies and 'set-cookie' not in headers:
            cookies = []
            for key, cookie in self.response.cookies.items():
                _cookie = f'{key}={cookie["value"]}'
                if cookie['expires'] is not None:
                    _cookie += f'; Expires={cookie["expires"].strftime("%a, %d %b %Y %H:%M:%S GMT")}'
                if cookie['max_age'] is not None:
                    _cookie += f'; Max-Age={cookie["max_age"]}'
                if cookie['domain'] is not None:
                    _cookie += f'; Domain={cookie["domain"]}'
                if cookie['secure']:
                    _cookie += '; Secure'
                if cookie['http_only']:
                    _cookie += '; HttpOnly'
                cookies.append(_cookie)
            headers['set-cookie'] = ', '.join(cookies)

        return status, headers, body

    async def get_body(self, status: int, headers: dict[str, str], body: dict | list | str | bytes | AsyncIterable | None) -> AsyncIterable[tuple[int, dict[str, str], bytes]]:
        if type(self.response) is FileResponse and self.request.ranges and status != 416:
            if self.response.file._data is None:
                handler = open(self.response.file.path, 'rb')
            if len(self.request.ranges) == 1:
                if self.response.file._data is not None:
                    size = len(self.response.file.data)
                    data = self.response.file.data[self.request.ranges[0][0] or 0:self.request.ranges[0][1] or len(self.response.file.data) + 1]
                else:
                    size = os.path.getsize(self.response.file.path)
                    handler.seek(self.request.ranges[0][0] or 0)
                    data = handler.read((self.request.ranges[0][1] or size) - (self.request.ranges[0][0]))
                    handler.close()
                headers['content-length'] = str(len(data))
                headers['content-range'] = f'bytes {self.request.ranges[0][0]}-{(self.request.ranges[0][1] or size) - 1}/{size}'
                yield status, headers, data
            else:
                boundary = uuid.uuid4().hex
                content_type = headers['content-type']
                headers['content-type'] = f'multipart/byteranges; boundary={boundary}'
                if self.response.file._data is not None:
                    size = len(self.response.file.data)
                else:
                    size = os.path.getsize(self.response.file.path)

                content_length = 0
                for range in self.request.ranges:
                    content_length += 2 + 32 + 2 + 14 + len(content_type) + 2 + 21 + (1 if range[0] == 0 else int(math.log10(range[0]))) + 1 + 1 + int(math.log10(range[1] or size)) + 1 + 1 + int(math.log10(size)) + 1 + 4 + (range[1] or size) - range[0] + 1
                headers['content-length'] = str(content_length)

                for range in self.request.ranges:
                    data = [b'--', boundary.encode(), b'\r\n', b'content-type: ', content_type.encode(), b'\r\n', b'content-range: bytes ', str(range[0]).encode(), b'-', str(range[1] or size).encode(), b'/', str(size).encode() + b'\r\n\r\n']
                    if self.response.file._data is not None:
                        data.append(self.response.file.data[range[0]:range[1] or size + 1])
                    else:
                        handler.seek(range[0])
                        data.append(handler.read((range[1] or size) - (range[0])))
                    yield status, headers, b''.join(data)
                if self.response.file._data is None:
                    handler.close()
                yield status, headers, b'--' + boundary.encode() + b'--'
        else:
            if isinstance(body, AsyncIterable):
                data = await anext(body)
            else:
                data = body

            if isinstance(data, (dict, list)):
                data = json.dumps(data).encode()
                headers.setdefault('content-type', 'application/json; charset=utf-8')
            elif isinstance(data, str):
                data = data.encode()
                headers.setdefault('content-type', 'text/plain; charset=utf-8')
            elif data is None:
                data = HTTP_STATUS[status].encode()
                headers.setdefault('content-type', 'text/plain; charset=utf-8')
            elif isinstance(data, bytes):
                headers.setdefault('content-type', 'application/octet-stream; charset=utf-8')

            if isinstance(body, AsyncIterable) is False:
                headers['content-length'] = str(len(data))

            status, headers, data = await self.get_encode_body(status, headers, data)
            if isinstance(body, AsyncIterable) is False:
                headers['content-length'] = str(len(data))
            yield status, headers, data

            if isinstance(body, AsyncIterable):
                async for data in body:
                    if isinstance(data, (dict, list)):
                        data = json.dumps(data).encode()
                    elif isinstance(data, str):
                        data = data.encode()
                    status, headers, data = await self.get_encode_body(status, headers, data)
                    yield status, headers, data

    async def get_encode_body(self, status: int, headers: dict[str, str], body: bytes) -> tuple[int, dict[str, str], bytes]:
        content_length = headers.get('content-length')
        if content_length and int(content_length) < self.app.compress_min_length:
            if 'content-encoding' in headers:
                del headers['content-encoding']

        if 'content-encoding' in headers and 'content-length' in headers and (int(headers['content-length']) > self.app.compress_min_length or self.response.compress is not None):
            compress_level = self.response.compress_level if self.response.compress_level is not None else self.app.compress_level
            if headers['content-encoding'] == 'gzip':
                body = gzip.compress(body, compress_level)
            elif headers['content-encoding'] == 'deflate':
                body = zlib.compress(body, level = compress_level)
            elif headers['content-encoding'] == 'br':
                body = brotli.compress(body, quality = compress_level)
            elif headers['content-encoding'] == 'zstd':
                body = zstandard.ZstdCompressor(level = compress_level).compress(body)

            headers['content-length'] = str(len(body))
        else:
            if 'content-encoding' in headers:
                del headers['content-encoding']

        return status, headers, body