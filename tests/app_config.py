'''
应用级配置（`CheeseAPI.__init__` 的参数及其生命周期行为）的测试

覆盖：

- 全局压缩：`compress`（协商与算法白名单）、`compress_min_length`、`compress_level`
- `logger_path`：日志文件生成与请求记录
- `keep_alive` / `keep_alive_timeout` / `keep_alive_max_requests`：裸 socket 手写 HTTP/1.1 观测连接复用与关闭
- `request_timeout`：半截请求头 / 半截请求体的处理
- `manual_modules`：模块列表覆盖自动扫描
- `workers`：多进程启动与请求分发

未覆盖：

- `exclude_modules` / `priority_modules`：两者只在「扫描 `cwd` 得到的模块列表」上生效，
  而 `tests/` 下没有带 `__init__.py` 的可加载目录（自动扫描结果为空），无法在只新增本域
  两个文件的前提下观测；`manual_modules` 会绕过这两项，也不能代替。
- `ssl_cert` / `ssl_key`、`sync_server_url`（需 redis）、`ipv6` / `dual_stack`、
  `socket_backlog` / 缓冲区大小、`logger_messages`、各 `*Proxy_Class` / `route_patterns`：
  属于其它测试域（cors / static / route / signal / scheduler）或依赖外部环境，本域不重复覆盖。
'''
APP = 'apps/config.py'

import contextlib, gzip, os, socket, subprocess, time, zlib
from pathlib import Path

import requests

from utils import HOST, Server

BIG_LENGTH: int = 12000
''' `apps/config.py` 里 `/big` 的响应体长度 '''

COMPRESS_MIN_LENGTH: int = 1024
''' `apps/config.py` 里配置的 `compress_min_length` '''

COMPRESS_LEVEL: int = 1
''' `apps/config.py` 里配置的 `compress_level`（框架默认是 6，刻意取 1 以便区分） '''

KEEP_ALIVE_TIMEOUT: float = 0.5
REQUEST_TIMEOUT: float = 1.5
KEEP_ALIVE_MAX_REQUESTS: int = 3

class RawClient:
    '''
    裸 socket 的 HTTP/1.1 客户端

    用 `requests` 观测不到「同一连接上的第 N 个请求」「连接何时被服务端关闭」「只发一半就不发」
    这些连接级行为，所以这里手写最简的请求与响应解析。
    '''

    __slots__ = ('sock', 'buffer')

    def __init__(self, port: int, timeout: float = 5.0):
        self.sock: socket.socket = socket.create_connection((HOST, port), timeout = timeout)
        self.buffer: bytes = b''

    def send(self, method: str, path: str, *, connection: str | None = None, headers: dict[str, str] | None = None, body: bytes = b''):
        ''' 发一个完整请求（`content-length` 按 `body` 给出） '''
        lines = [f'{method} {path} HTTP/1.1', f'Host: {HOST}', f'Content-Length: {len(body)}']
        if connection is not None:
            lines.append(f'Connection: {connection}')
        lines.extend(f'{key}: {value}' for key, value in (headers or {}).items())
        self.sock.sendall(('\r\n'.join(lines) + '\r\n\r\n').encode() + body)

    def send_raw(self, data: bytes):
        ''' 发任意字节；用来构造「只发一半」的请求 '''
        self.sock.sendall(data)

    def read(self, timeout: float = 5.0) -> tuple[int, dict[str, str], bytes] | None:
        ''' 读一个响应；服务端已关闭连接时返回 None '''
        self.sock.settimeout(timeout)
        try:
            while b'\r\n\r\n' not in self.buffer:
                chunk = self.sock.recv(65536)
                if not chunk:
                    return None
                self.buffer += chunk
        except (socket.timeout, ConnectionResetError):
            return None

        head, self.buffer = self.buffer.split(b'\r\n\r\n', 1)
        lines = head.decode().split('\r\n')
        headers = {}
        for line in lines[1:]:
            key, value = line.split(': ', 1)
            headers[key.lower()] = value

        length = int(headers.get('content-length', 0))
        while len(self.buffer) < length:
            try:
                chunk = self.sock.recv(65536)
            except (socket.timeout, ConnectionResetError):
                break
            if not chunk:
                break
            self.buffer += chunk

        body = self.buffer[:length]
        self.buffer = self.buffer[length:]
        return int(lines[0].split(' ')[1]), headers, body

    def wait_close(self, timeout: float = 4.0) -> bool:
        ''' 等服务端关闭连接；期间收到的字节留在 `buffer`（用于确认「没有收到响应」） '''
        self.sock.settimeout(timeout)
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                chunk = self.sock.recv(4096)
            except socket.timeout:
                return False
            except ConnectionResetError:
                return True
            if not chunk:
                return True
            self.buffer += chunk
        return False

    def close(self):
        try:
            self.sock.close()
        except Exception:
            ...

@contextlib.contextmanager
def extra_server(**environment: str):
    '''
    用额外环境变量起第二个被测服务进程

    `tests/apps/config.py` 的配置项可用环境变量覆盖，这样「`keep_alive = False`」「关压缩」
    这类与主配置互斥的取值也能被断言到；用完恢复环境。
    '''
    previous = {key: os.environ.get(key) for key in environment}
    os.environ.update(environment)
    try:
        with Server(app = APP) as server:
            yield server
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

def http(server, path: str, **kwargs):
    ''' 需要响应头时用这个（`Server.get()` 只返回响应文本） '''
    return requests.get(f'{server.url}{path}', timeout = 10, **kwargs)

def plain_big(server) -> str:
    ''' 拿 `/big` 的未压缩响应体（`identity` 不在应用级 `compress` 白名单里，不会被压缩） '''
    return server.get('/big', headers = {'accept-encoding': 'identity'})

def log_text(port: int) -> str:
    ''' 读被测服务进程按 `logger_path` 写出的日志文件 '''
    try:
        return Path(f'/tmp/cheeseapi_test_log_{port}.log').read_text(encoding = 'utf-8')
    except Exception:
        return ''

def wait_log(port: int, needle: str, timeout: float = 5.0) -> str:
    ''' 等日志落盘（日志由后台线程写文件，请求结束后不会立刻可见） '''
    deadline = time.time() + timeout
    text = ''
    while time.time() < deadline:
        text = log_text(port)
        if needle in text:
            return text
        time.sleep(0.2)
    return text

def process_table() -> list[tuple[int, int]]:
    ''' 读一遍系统进程表，返回 `(pid, ppid)` 列表（`workers > 1` 起的子进程只有操作系统能看到） '''
    result = subprocess.run(['ps', '-eo', 'pid=,ppid='], capture_output = True, text = True).stdout
    items = [line.split() for line in result.splitlines()]
    return [(int(item[0]), int(item[1])) for item in items if len(item) == 2]

#### 全局压缩 ####

def case_compress_gzip(t, server):
    ''' 应用级 `compress` 对超过阈值的响应做 gzip '''
    plain = plain_big(server)
    t.check('compress：`identity` 时不压缩，拿到原文', len(plain) == BIG_LENGTH, f'长度 {len(plain)}')

    client = RawClient(server.port)
    client.send('GET', '/big', headers = {'Accept-Encoding': 'gzip'})
    response = client.read()
    client.close()

    t.check('compress：`Accept-Encoding: gzip` 时响应带 content-encoding: gzip', response is not None and response[1].get('content-encoding') == 'gzip', f'响应头 {response[1] if response else None}')
    t.check('compress：gzip 响应体是真正的 gzip 流且解压后与原文一致', response is not None and response[2][:2] == b'\x1f\x8b' and gzip.decompress(response[2]).decode() == plain, f'前两字节 {response[2][:2] if response else None}')
    t.check('compress：压缩后 content-length 小于原始长度', response is not None and int(response[1]['content-length']) < BIG_LENGTH, f'content-length {response[1].get("content-length") if response else None}')

def case_compress_min_length(t, server):
    ''' `compress_min_length` 控制压缩阈值 '''
    health = http(server, '/health', headers = {'accept-encoding': 'gzip'})
    under = http(server, '/under', headers = {'accept-encoding': 'gzip'})
    exact = http(server, '/exact', headers = {'accept-encoding': 'gzip'})
    big = http(server, '/big', headers = {'accept-encoding': 'gzip'})

    t.check('compress_min_length：很短的响应体不压缩', health.text == 'ok' and health.headers.get('content-encoding') is None, f'content-encoding {health.headers.get("content-encoding")!r}')
    t.check(f'compress_min_length：长度为 {COMPRESS_MIN_LENGTH - 1} 的响应体不压缩', under.text == 'y' * (COMPRESS_MIN_LENGTH - 1) and under.headers.get('content-encoding') is None, f'content-encoding {under.headers.get("content-encoding")!r}，长度 {len(under.text)}')
    t.check('compress_min_length：长度超过阈值的响应体压缩', big.text == 'compress-me ' * 1000 and big.headers.get('content-encoding') == 'gzip', f'content-encoding {big.headers.get("content-encoding")!r}，长度 {len(big.text)}')

    t.check(
        f'compress_min_length：长度恰好等于阈值（{COMPRESS_MIN_LENGTH}）的响应体也压缩',
        exact.headers.get('content-encoding') == 'gzip' and int(exact.headers['content-length']) < COMPRESS_MIN_LENGTH,
        f'content-encoding {exact.headers.get("content-encoding")!r}，content-length {exact.headers.get("content-length")}'
    )

def case_compress_negotiation(t, server):
    ''' 应用级 `compress` 决定协商结果：白名单与优先级都按应用配置，而不是客户端列出的顺序 '''
    plain = plain_big(server)

    def fetch(accept_encoding: str) -> tuple[str | None, str]:
        response = http(server, '/big', headers = {'accept-encoding': accept_encoding})
        return response.headers.get('content-encoding'), response.text

    encoding, text = fetch('deflate')
    t.check('compress：白名单内的 deflate 会被使用，且解压后内容一致', encoding == 'deflate' and text == plain, f'content-encoding {encoding!r}')

    encoding, text = fetch('br')
    t.check('compress：不在应用级白名单内的 br 不会被使用，响应为原文', encoding is None and text == plain, f'content-encoding {encoding!r}')

    encoding, _ = fetch('deflate, gzip')
    t.check('compress：客户端同时接受 gzip 与 deflate 时，按应用级 compress 顺序取 gzip', encoding == 'gzip', f'content-encoding {encoding!r}')

    encoding, _ = fetch('*')
    t.check('compress：`Accept-Encoding: *` 取应用级 compress 的首个算法 gzip', encoding == 'gzip', f'content-encoding {encoding!r}')

def case_compress_level(t, server):
    ''' 应用级 `compress_level` 真正作用到压缩结果上 '''
    plain = plain_big(server).encode()
    gzipped = http(server, '/big', headers = {'accept-encoding': 'gzip'})
    level_6 = gzip.compress(plain, 6)

    t.check(
        f'compress_level：gzip 使用应用级 compress_level={COMPRESS_LEVEL}（应为 {len(gzip.compress(plain, COMPRESS_LEVEL))} 字节）',
        gzipped.headers.get('content-length') == str(len(gzip.compress(plain, COMPRESS_LEVEL))),
        f'content-length {gzipped.headers.get("content-length")}'
    )
    t.check(
        'compress_level：压缩结果不等于框架默认等级 6 的结果',
        gzipped.headers.get('content-length') != str(len(level_6)),
        f'content-length {gzipped.headers.get("content-length")}，level 6 为 {len(level_6)}'
    )

    deflated = http(server, '/big', headers = {'accept-encoding': 'deflate'})
    t.check(
        f'compress_level：deflate 同样使用应用级 compress_level={COMPRESS_LEVEL}',
        deflated.headers.get('content-length') == str(len(zlib.compress(plain, COMPRESS_LEVEL))) and deflated.headers.get('content-length') != str(len(zlib.compress(plain, 6))),
        f'content-length {deflated.headers.get("content-length")}'
    )

def case_compress_disabled(t, server):
    ''' 应用级 `compress = []` 时任何响应都不压缩 '''
    with extra_server(CHEESE_TEST_COMPRESS = '') as plain_server:
        for accept_encoding in ('gzip', 'deflate', '*'):
            response = http(plain_server, '/big', headers = {'accept-encoding': accept_encoding})
            t.check(f'compress 为空时：`Accept-Encoding: {accept_encoding}` 也不压缩', response.headers.get('content-encoding') is None and len(response.text) == BIG_LENGTH, f'content-encoding {response.headers.get("content-encoding")!r}，长度 {len(response.text)}')

#### logger_path ####

def case_logger_path(t, server):
    ''' `logger_path` 生成日志文件并写入启动与请求记录 '''
    path = Path(f'/tmp/cheeseapi_test_log_{server.port}.log')
    text = wait_log(server.port, '(START)')

    t.check('logger_path：按配置的路径生成日志文件', path.exists(), f'路径 {path}')
    t.check('logger_path：日志包含启动记录', '(START)' in text, text[:80])

    server.get('/health')
    server.get('/big', headers = {'accept-encoding': 'identity'})
    text = wait_log(server.port, '/big')
    http_lines = [line for line in text.splitlines() if '(HTTP)' in line]
    t.check('logger_path：逐条追加请求记录（方法、路径与状态码）', len(http_lines) >= 2 and 'GET /health' in text and 'GET /big' in text and 'returned 200' in text, http_lines[:2])

#### keep_alive ####

def case_keep_alive_reuse(t, server):
    ''' 同一连接上复用请求，响应头宣告 keep-alive 参数 '''
    client = RawClient(server.port)
    responses = []
    for _ in range(KEEP_ALIVE_MAX_REQUESTS):
        client.send('GET', '/health', connection = 'keep-alive')
        responses.append(client.read(3.0))
    client.close()

    t.check(f'keep-alive：同一连接上连续 {KEEP_ALIVE_MAX_REQUESTS} 个请求都返回 200 与本体', all(response is not None and response[0] == 200 and response[2] == b'ok' for response in responses), repr([response[0] if response else None for response in responses]))

    headers = responses[0][1] if responses[0] else {}
    t.check('keep-alive：响应头保持连接且宣告 keep-alive 参数', headers.get('connection') == 'keep-alive' and f'timeout={KEEP_ALIVE_TIMEOUT}' in headers.get('keep-alive', '') and f'max={KEEP_ALIVE_MAX_REQUESTS}' in headers.get('keep-alive', ''), f'connection {headers.get("connection")!r}，keep-alive {headers.get("keep-alive")!r}')

def case_keep_alive_max_requests(t, server):
    ''' 超过 `keep_alive_max_requests` 后连接被关闭 '''
    client = RawClient(server.port)
    for _ in range(KEEP_ALIVE_MAX_REQUESTS):
        client.send('GET', '/health', connection = 'keep-alive')
        client.read(3.0)

    client.send('GET', '/health', connection = 'keep-alive')
    overflow = client.read(2.0)
    t.check(
        f'keep_alive_max_requests：第 {KEEP_ALIVE_MAX_REQUESTS + 1} 个请求超出上限被关闭',
        overflow is None,
        f'第 {KEEP_ALIVE_MAX_REQUESTS + 1} 个请求得到 {overflow[0] if overflow else None}，而响应头宣告 max={KEEP_ALIVE_MAX_REQUESTS}'
    )

    try:
        client.send('GET', '/health', connection = 'keep-alive')
        sent = True
    except OSError:
        sent = False
    closure = client.wait_close(2.0)
    received = client.buffer
    client.close()
    t.check('keep_alive_max_requests：达到上限后服务端关闭连接', closure and ((not sent) or received == b''), f'closed {closure}，sent {sent}，收到 {received!r}')

def case_keep_alive_timeout(t, server):
    ''' 空闲超过 `keep_alive_timeout` 后连接被服务端关闭 '''
    client = RawClient(server.port)
    client.send('GET', '/health', connection = 'keep-alive')
    first = client.read(3.0)
    t.check('keep_alive_timeout：首个请求正常响应并保持连接', first is not None and first[0] == 200 and first[1].get('connection') == 'keep-alive', f'响应 {first[0] if first else None}')

    start = time.time()
    closed = client.wait_close(timeout = 3.0)
    elapsed = time.time() - start
    client.close()

    t.check('keep_alive_timeout：空闲后服务端关闭连接', closed, f'关闭耗时 {elapsed:.2f}s')
    t.check(f'keep_alive_timeout：空闲关闭由 keep_alive_timeout（{KEEP_ALIVE_TIMEOUT}s）而非 request_timeout（{REQUEST_TIMEOUT}s）触发', elapsed < REQUEST_TIMEOUT - 0.2, f'耗时 {elapsed:.2f}s')

def case_connection_close(t, server):
    ''' 请求头带 `Connection: close` 时响应后立即关闭 '''
    client = RawClient(server.port)
    client.send('GET', '/health', connection = 'close')
    response = client.read(3.0)
    closed = client.wait_close(2.0)
    client.close()

    t.check('Connection: close：响应头为 close 且不再宣告 keep-alive', response is not None and response[1].get('connection') == 'close' and 'keep-alive' not in response[1], f'响应头 {response[1] if response else None}')
    t.check('Connection: close：响应后服务端立即关闭连接', closed, f'closed {closed}')

def case_keep_alive_disabled(t, server):
    ''' 应用级 `keep_alive = False` 时即使客户端要求保持连接也不复用 '''
    with extra_server(CHEESE_TEST_KEEP_ALIVE = '0') as plain_server:
        t.check('keep_alive=False：服务仍能正常响应', plain_server.get('/health') == 'ok')

        client = RawClient(plain_server.port)
        client.send('GET', '/health', connection = 'keep-alive')
        response = client.read(3.0)
        closed = client.wait_close(2.0)
        client.close()

        t.check('keep_alive=False：请求 keep-alive 时响应头仍是 close', response is not None and response[1].get('connection') == 'close' and 'keep-alive' not in response[1], f'响应头 {response[1] if response else None}')
        t.check('keep_alive=False：一次请求后连接即关闭', closed, f'closed {closed}')

#### request_timeout ####

def case_request_timeout_body(t, server):
    ''' 请求体只发一半时，`request_timeout` 后返回 408 '''
    client = RawClient(server.port)
    client.send_raw(f'POST /echo HTTP/1.1\r\nHost: {HOST}\r\nContent-Length: 100\r\n\r\nabcde'.encode())
    start = time.time()
    response = client.read(5.0)
    elapsed = time.time() - start
    client.close()

    t.check('request_timeout：半截请求体最终返回 408', response is not None and response[0] == 408, f'响应 {response[0] if response else None}')
    t.check(f'request_timeout：半截请求体的等待时间由 request_timeout（{REQUEST_TIMEOUT}s）决定', elapsed >= REQUEST_TIMEOUT - 0.4, f'耗时 {elapsed:.2f}s')

def case_request_timeout_headers(t, server):
    ''' 请求头只发一半时，`request_timeout` 后服务端结束该连接 '''
    client = RawClient(server.port)
    client.send_raw(f'GET /health HTTP/1.1\r\nHost: {HOST}\r\n'.encode())

    start = time.time()
    closed = client.wait_close(timeout = 5.0)
    elapsed = time.time() - start
    received = client.buffer
    client.close()

    t.check('request_timeout：请求头不完整时服务端不返回响应而直接关连接', closed and received == b'', f'closed {closed}，收到 {received!r}')
    t.check(f'request_timeout：新连接的等待时间由 request_timeout（{REQUEST_TIMEOUT}s）而非 keep_alive_timeout（{KEEP_ALIVE_TIMEOUT}s）决定', elapsed >= REQUEST_TIMEOUT - 0.4, f'耗时 {elapsed:.2f}s')

#### 模块加载 ####

def case_manual_modules(t, server):
    ''' `manual_modules` 覆盖 `cwd` 自动扫描（按配置的列表加载，并把列表写进日志） '''
    with extra_server(CHEESE_TEST_MANUAL_MODULES = 'ghost_module') as plain_server:
        text = wait_log(plain_server.port, '(LOADED)')
        t.check('manual_modules：加载记录来自配置的模块列表', '(LOADING)' in text and 'ghost_module' in text, [line for line in text.splitlines() if 'ghost_module' in line][:1])
        t.check('manual_modules：加载完成后汇总的就是该列表', '(LOADED)' in text and 'ghost_module' in text.split('(LOADED)')[1], f'LOADED 段 {text.split("(LOADED)")[1][:60] if "(LOADED)" in text else None}')
        t.check('manual_modules：列表里的模块不存在时不影响服务启动与请求', plain_server.get('/health') == 'ok')

#### workers ####

def case_workers(t, server):
    ''' `workers > 1` 时起多个工作子进程，请求由子进程处理 '''
    with extra_server(CHEESE_TEST_WORKERS = '2') as plain_server:
        t.check('workers=2：服务正常响应', plain_server.get('/health') == 'ok')

        pids = {int(plain_server.get('/pid')) for _ in range(8)}
        launcher = plain_server.process.pid
        t.check('workers=2：请求由工作子进程处理，而不是启动进程', pids.isdisjoint({launcher}), f'launcher {launcher}，处理请求的进程 {sorted(pids)}')

        children = [pid for pid, parent in process_table() if parent == launcher]
        t.check('workers=2：启动了多个工作子进程', len(children) >= 2, f'launcher {launcher} 的子进程 {sorted(children)}')

CASES = [
    ('全局压缩 gzip', case_compress_gzip),
    ('全局压缩 compress_min_length', case_compress_min_length),
    ('全局压缩 compress 协商', case_compress_negotiation),
    ('全局压缩 compress_level', case_compress_level),
    ('compress 置空', case_compress_disabled),
    ('logger_path 日志', case_logger_path),
    ('keep-alive 连接复用', case_keep_alive_reuse),
    ('keep-alive 最大请求数', case_keep_alive_max_requests),
    ('keep-alive 空闲超时', case_keep_alive_timeout),
    ('Connection: close', case_connection_close),
    ('keep_alive=False', case_keep_alive_disabled),
    ('request_timeout 半截请求体', case_request_timeout_body),
    ('request_timeout 半截请求头', case_request_timeout_headers),
    ('manual_modules', case_manual_modules),
    ('workers', case_workers)
]
