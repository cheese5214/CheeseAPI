'''
测试公共工具

- `Tester`：断言收集与汇总
- `Server`：以**子进程**启动被测应用，并提供 HTTP / WebSocket 客户端

为什么服务要跑在子进程：
`app.start()` 内部会调用 `signal.signal(...)` 注册信号处理器，而 Python 只允许在主线程注册信号，
因此原来的 `threading.Thread(target = app.start)` 写法在 Python 3.13 上会直接
`ValueError: signal only works in main thread`，服务根本没起来但测试还照跑。
'''
import base64, json, os, socket, struct, subprocess, sys, time
from pathlib import Path

import requests

HOST = '127.0.0.1'
TESTS_DIR = Path(__file__).parent
PROJECT_ROOT = TESTS_DIR.parent

''' 让 `import CheeseAPI` 命中本仓库源码。
    site-packages 里可能装着旧版 CheeseAPI（如 1.7.x），必须插到 sys.path 最前面才不会被它顶掉 '''
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

class Tester:
    ''' 极简断言收集器 '''

    __slots__ = ('results', 'known_issues')

    def __init__(self):
        self.results: list[tuple[str, bool, str]] = []
        self.known_issues: list[tuple[str, str]] = []

    def check(self, name: str, condition, detail: str = '') -> bool:
        condition = bool(condition)
        self.results.append((name, condition, detail))
        print(f'  {"PASS" if condition else "FAIL"}  {name}' + (f'  | {detail}' if detail else ''))
        return condition

    def known_issue(self, name: str, condition, detail: str = '') -> bool:
        '''
        已知缺陷：写法与 `check` 一致，但断言的是「正确行为」

        当前实现不满足时记为「已知缺陷」（不算失败，保持套件绿色）；
        一旦实现被修好，这里会变成 FAIL，提醒把该用例转成正式断言。
        '''
        if condition:
            self.results.append((f'{name}（已修复，请转为正式断言）', False, detail))
            print(f'  FAIL  {name}  | 已满足预期，请把它从已知缺陷转为 check：{detail}')
            return True

        self.known_issues.append((name, detail))
        print(f'  KNOWN {name}' + (f'  | {detail}' if detail else ''))
        return False

    @property
    def failed(self) -> list[tuple[str, bool, str]]:
        return [result for result in self.results if not result[1]]

    @property
    def summary(self) -> str:
        text = f'{len(self.results) - len(self.failed)}/{len(self.results)} passed'
        if self.known_issues:
            text += f'，已知缺陷 {len(self.known_issues)} 项'
        return text

def free_port() -> int:
    ''' 取一个空闲端口，避免与现场/本地已占用的端口（如默认 5214）冲突 '''
    with socket.socket() as s:
        s.bind((HOST, 0))
        return s.getsockname()[1]

class Server:
    '''
    被测应用的服务进程

    用法：
    ```python
    with Server() as server:
        server.get('/health')
    ```
    '''

    def __init__(self, app: str = 'apps/basic.py', port: int | None = None):
        '''
        - Args
            - app: 测试应用（相对于 `tests/` 的路径），每个测试域用自己的应用文件，互不干扰
            - port: 指定端口；不传则自动取一个空闲端口
        '''
        self.app: str = app
        self.port: int = port or free_port()
        self.state_path: str = f'/tmp/cheeseapi_test_state_{self.port}.json'
        self.warn_path: str = f'/tmp/cheeseapi_test_warn_{self.port}.txt'
        self.log_path: str = f'/tmp/cheeseapi_test_server_{self.port}.log'
        self.process: subprocess.Popen | None = None
        self._log = None

    @property
    def url(self) -> str:
        return f'http://{HOST}:{self.port}'

    def start(self, timeout: float = 30.0):
        for path in (self.state_path, self.warn_path):
            if os.path.exists(path):
                os.remove(path)

        self._log = open(self.log_path, 'w', encoding = 'utf-8')

        # 独立进程组：CheeseAPI 停止时会 `os.killpg(os.getpgid(os.getpid()), SIGINT)` 杀掉整个进程组，
        # 测试进程与它同组会被一起带走
        environment = dict(
            os.environ,
            # 让应用文件能 import 到 tests/ 下的公共工具（utils / apputils）
            PYTHONPATH = os.pathsep.join(filter(None, [str(TESTS_DIR), os.environ.get('PYTHONPATH', '')])),
            CHEESE_TEST_PORT = str(self.port),
            CHEESE_TEST_STATE = self.state_path,
            CHEESE_TEST_WARN = self.warn_path
        )

        self.process = subprocess.Popen(
            [sys.executable, '-u', str(TESTS_DIR / self.app)],
            cwd = str(TESTS_DIR),
            start_new_session = True,
            stdout = self._log,
            stderr = subprocess.STDOUT,
            env = environment
        )

        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if self.get('/health') == 'ok':
                    return self
            except Exception:
                time.sleep(0.3)

        raise RuntimeError(f'服务启动失败（app={self.app}），日志见 {self.log_path}\n{self.log()}')

    def stop(self):
        if self._log is not None:
            self._log.close()
            self._log = None

        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout = 10)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.process = None

    def __enter__(self):
        return self.start()

    def __exit__(self, *_):
        self.stop()

    def log(self) -> str:
        try:
            return Path(self.log_path).read_text(encoding = 'utf-8')
        except Exception:
            return ''

    def state(self) -> dict:
        ''' 读取服务进程内的连接计数等状态 '''
        try:
            return json.loads(Path(self.state_path).read_text(encoding = 'utf-8'))
        except Exception:
            return {}

    def warnings(self) -> str:
        ''' 读取服务进程内捕获的运行时告警 '''
        try:
            return Path(self.warn_path).read_text(encoding = 'utf-8')
        except Exception:
            return ''

    def get(self, path: str, **kwargs) -> str:
        response = requests.get(f'{self.url}{path}', timeout = 10, **kwargs)
        return response.text

    def post(self, path: str, **kwargs):
        return requests.post(f'{self.url}{path}', timeout = 10, **kwargs)

    def wait_state(self, key: str, value, timeout: float = 10.0) -> bool:
        ''' 等待服务进程内的某个计数达到期望值 '''
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.state().get(key) == value:
                return True
            time.sleep(0.2)
        return False

class WebsocketClient:
    '''
    裸 socket 实现的 WebSocket 客户端

    不用 `websockets` 库是为了能精确控制断开方式（`abort()` 发 RST 模拟异常掉线），
    避免依赖库版本差异影响“异常断连”这一关键用例
    '''

    __slots__ = ('sock',)

    def __init__(self, port: int, path: str = '/ws'):
        self.sock = socket.create_connection((HOST, port), timeout = 10)

        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((
            f'GET {path} HTTP/1.1\r\n'
            f'Host: {HOST}:{port}\r\n'
            'Upgrade: websocket\r\n'
            'Connection: Upgrade\r\n'
            f'Sec-WebSocket-Key: {key}\r\n'
            'Sec-WebSocket-Version: 13\r\n\r\n'
        ).encode())

        buffer = b''
        while b'\r\n\r\n' not in buffer:
            chunk = self.sock.recv(4096)
            if not chunk:
                break
            buffer += chunk

        status = buffer.split(b'\r\n')[0]
        if b'101' not in status:
            raise RuntimeError(f'WebSocket 握手失败：{status!r}')

    def send(self, text: str):
        payload = text.encode()
        mask = os.urandom(4)
        masked = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))

        if len(payload) < 126:
            header = bytes([0x81, 0x80 | len(payload)])
        else:
            header = bytes([0x81, 0x80 | 126]) + struct.pack('!H', len(payload))

        self.sock.sendall(header + mask + masked)

    def recv(self, timeout: float = 10.0):
        ''' 读取一帧；返回 str（文本帧）或 bytes（其他帧），超时返回 None '''
        self.sock.settimeout(timeout)
        try:
            header = self.sock.recv(2)
        except socket.timeout:
            return None

        if len(header) < 2:
            return None

        opcode = header[0] & 0x0F
        length = header[1] & 0x7F
        masked = bool(header[1] & 0x80)

        if length == 126:
            length = struct.unpack('!H', self.sock.recv(2))[0]
        elif length == 127:
            length = struct.unpack('!Q', self.sock.recv(8))[0]

        mask = self.sock.recv(4) if masked else b''

        payload = b''
        while len(payload) < length:
            chunk = self.sock.recv(length - len(payload))
            if not chunk:
                break
            payload += chunk

        if masked:
            payload = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))

        return payload.decode() if opcode == 0x1 else payload

    def abort(self):
        ''' 异常断开：设置 SO_LINGER 后直接关闭，内核发 RST，不发 WebSocket close 帧 '''
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack('ii', 1, 0))
        self.sock.close()

    def close(self):
        try:
            self.sock.close()
        except Exception:
            ...
