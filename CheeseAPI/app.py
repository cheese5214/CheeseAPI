import os, pathlib, multiprocessing, ssl, socket, asyncio, concurrent.futures, inspect
from typing import Type, Literal, Callable, AsyncIterable, TYPE_CHECKING

import redis, signal
from CheeseLog import CheeseLogger, Message

from CheeseAPI.printer import Printer
from CheeseAPI.signal import Signal
from CheeseAPI.request import RequestProxy
from CheeseAPI.response import ResponseProxy
from CheeseAPI.request import Request
from CheeseAPI.response import Response, FileResponse
from CheeseAPI.route import RouteProxy, AppRoute
from CheeseAPI.cors import CORS
from CheeseAPI.websocket import WebsocketProxy
from CheeseAPI.scheduler import Scheduler, SchedulerProxy

if TYPE_CHECKING:
    from CheeseAPI.websocket import Websocket
    from CheeseAPI.route import Pattern

class AppProxy:
    __slots__ = ('app', 'ssl_context', 'server_socket')

    def __init__(self, app: 'CheeseAPI'):
        self.app: CheeseAPI = app

        self.ssl_context: ssl.SSLContext | None = None
        self.server_socket: socket.socket | None = None

    def start(self):
        signal.signal(signal.SIGTERM, lambda signum, frame: self.app.stop())

        waiting_list = []

        try:
            self.app.logger.start()
            self.app.printer.app_start()

            self.load_modules()

            self.app._is_running = True

            self.app.signal.before_server_start.send()

            self.server_start()

            waiting_list = self.worker_start()
            for item in waiting_list:
                item.join()
        except (KeyboardInterrupt, SystemExit):
            ...
        except Exception as e:
            self.app.printer.app_error(e)

        self.stop(waiting_list)

    def stop(self, waiting_list: list[multiprocessing.Process] | None = None):
        self.app.printer.server_stop()

        self.before_app_stop()
        self.app.signal.before_app_stop.send()

        if waiting_list:
            try:
                for item in waiting_list:
                    item.join()
            except (KeyboardInterrupt, SystemExit):
                for item in waiting_list:
                    item.terminate()

        self.app._is_running = False

        self.app.printer.app_stop()
        self.app.logger.stop()

        self.after_app_stop()
        self.app.signal.after_app_stop.send()

    def load_modules(self):
        if self.app.manual_modules:
            modules = self.app.manual_modules
        else:
            modules = [module for module in os.listdir(os.getcwd()) if os.path.isdir(module) and os.path.exists(os.path.join(module, '__init__.py')) and module not in self.app.exclude_modules]
            modules = [module for module in self.app.priority_modules if module in modules] + [module for module in modules if module not in self.app.priority_modules]

        modules = self.before_load_modules(modules)
        self.app.signal.before_load_modules.send(kwargs = {
            'modules': modules
        })

        for i, module in enumerate(modules):
            self.app.printer.load_module(module, i / len(modules))

            i, module = self.before_load_module(i, module)
            self.app.signal.before_load_module.send(kwargs = {
                'index': i,
                'modules': module
            })

            for path in pathlib.Path(module).glob('*.py'):
                __import__(f'{module}.{path.stem}')

            self.after_load_module(i, module)
            self.app.signal.after_load_module.send(kwargs = {
                'index': i,
                'modules': module
            })

        self.after_load_modules(modules)
        self.app.signal.after_load_modules.send(kwargs = {
            'modules': modules
        })

        if modules:
            self.app.printer.modules_loaded(modules)

    def before_load_modules(self, modules: list[str]) -> list[str]:
        return modules

    def after_load_modules(self, modules: list[str]):
        ...

    def before_load_module(self, index: int, module: str) -> tuple[int, str]:
        return index, module

    def after_load_module(self, index: int, module: str):
        ...

    def server_start(self):
        self.before_server_start()
        self.app.signal.before_server_start.send()

        if self.app.ssl_cert is not None and self.app.ssl_key is not None:
            self.ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            self.ssl_context.load_cert_chain(self.app.ssl_cert, self.app.ssl_key)

        if self.app.ipv6:
            self.server_socket = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
            if self.app.dual_stack is True:
                self.server_socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        else:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        self.server_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        try:
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except AttributeError:
            ...

        if self.app.socket_send_buffer_size is not None:
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, self.app.socket_send_buffer_size)
        else:
            self.app._socket_send_buffer_size = self.server_socket.getsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF)
        if self.app.socket_receive_buffer_size is not None:
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, self.app.socket_receive_buffer_size)
        else:
            self.app._socket_receive_buffer_size = self.server_socket.getsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF)
        self.server_socket.bind((self.app.host, self.app.port))
        self.server_socket.listen(self.app.socket_backlog or socket.SOMAXCONN)
        self.server_socket.setblocking(False)
        self.server_socket.set_inheritable(True)

        self.app.printer.server_start()

        self.after_server_start()
        self.app.signal.after_server_start.send()

    def before_server_start(self):
        ...

    def after_server_start(self):
        ...

    def before_app_stop(self):
        ...

    def after_app_stop(self):
        ...

    def worker_start(self) -> list[multiprocessing.Process] | None:
        workers = self.before_workers_start(self.app.workers)
        self.app.signal.before_workers_start.send(kwargs = {
            'workers': workers
        })

        processes = []
        if workers == 1:
            self.worker_running(True)
        else:
            processes: list[multiprocessing.Process] = []
            for i in range(workers):
                process = multiprocessing.Process(target = self.worker_running, args = (i == 0,))
                process.start()
                processes.append(process)

        self.after_workers_start(workers)
        self.app.signal.after_workers_start.send(kwargs = {
            'workers': workers
        })
        return processes

    def before_workers_start(self, workers: int) -> int:
        return workers

    def after_workers_start(self, workers: int):
        ...

    def before_worker_start(self, is_first: bool):
        ...

    async def after_worker_start(self, is_first: bool):
        ...

    def worker_running(self, is_first: bool):
        try:
            self.before_worker_start(is_first)
            self.app.signal.before_worker_start.send(kwargs = {
                'is_first': is_first
            })

            asyncio.run(self.async_worker_running(is_first))
        except (KeyboardInterrupt, SystemExit):
            ...
        except Exception as e:
            self.app.printer.app_error(e)

        try:
            self.after_worker_stop(is_first)
            self.app.signal.after_worker_stop.send(kwargs = {
                'is_first': is_first
            })
        except Exception as e:
            self.app.printer.app_error(e)

    async def async_worker_running(self, is_first: bool):
        try:
            loop = asyncio.get_event_loop()
            loop.set_default_executor(concurrent.futures.ThreadPoolExecutor())

            if self.app.sync_server_url:
                if WebsocketProxy.sync_servers is None:
                    WebsocketProxy.sync_servers = (redis.Redis.from_url(self.app.sync_server_url), redis.asyncio.Redis.from_url(self.app.sync_server_url))
                if WebsocketProxy.data_encode is None:
                    WebsocketProxy.data_encode = self.app.sync_server_data_encode
                if WebsocketProxy.data_decode is None:
                    WebsocketProxy.data_decode = self.app.sync_server_data_decode

            await self.after_worker_start(is_first)
            await self.app.signal.after_worker_start.async_send(kwargs = {
                'is_first': is_first
            })

            while True:
                client_socket, addr = await loop.sock_accept(self.server_socket)
                loop.create_task(self.client_socket_process(client_socket, addr))
        except asyncio.CancelledError:
            ...
        except Exception as e:
            self.app.printer.app_error(e)

        try:
            await self.before_worker_stop(is_first)
            await self.app.signal.before_worker_stop.async_send(kwargs = {
                'is_first': is_first
            })
        except Exception as e:
            self.app.printer.app_error(e)

    async def client_socket_process(self, client_socket: socket.socket, addr: tuple[str, int]):
        try:
            loop = asyncio.get_event_loop()

            if self.ssl_context is not None:
                client_socket = await loop.run_in_executor(None, lambda: self.ssl_context.wrap_socket(client_socket, server_side = True, do_handshake_on_connect = False))

            async for request, response in self.get_request(client_socket, addr):
                if not response:
                    response = await self.get_response(request)

                if not response._proxy:
                    response = self.app.ResponseProxy_Class(self.app, response).response

                if not response._proxy.request:
                    response._proxy.request = request

                await self.send_response(response, client_socket)

                if response._proxy.websocket:
                    await response._proxy.websocket._proxy.running()
        except ConnectionAbortedError:
            if client_socket._closed is False:
                client_socket.close()
        except Exception as e:
            self.app.printer.fn_error(e, request)

        if client_socket._closed is False:
            client_socket.close()

    async def send_response(self, response: Response, client_socket: socket.socket):
        response = await self.before_response(response)
        await self.app.signal.before_response.async_send(kwargs = {
            'response': response
        })

        await response._proxy.send(client_socket)

        await self.after_response(response)
        await self.app.signal.after_response.async_send(kwargs = {
            'response': response
        })

    async def get_response(self, request: Request) -> Response:
        if inspect.isfunction(request.fn):
            try:
                return await request.fn(request = request)
            except Exception as e:
                self.app.printer.fn_error(e, request)
                return Response(status = 500)
        else:
            websocket: Websocket = request.fn(request)
            if websocket.response:
                return websocket.response
            else:
                return await websocket._proxy.get_response()

    async def get_request(self, client_socket: socket.socket, addr: tuple[str, int]) -> AsyncIterable[tuple[Request, Response | None]]:
        keep_alive_max_requests = 0
        request = None
        while keep_alive_max_requests < self.app.keep_alive_max_requests and client_socket._closed is False:
            if request:
                keep_alive_max_requests += 1

                request = await self.after_request(request)
                await self.app.signal.after_request.async_send(kwargs = {
                    'request': request
                })

                if request._proxy.protocol is None or not self.app.keep_alive or (request._proxy.protocol == 'HTTP/1.0' and request.headers.get('Connection') != 'keep-alive') or (request._proxy.protocol == 'HTTP/1.1' and request.headers.get('Connection') == 'close'):
                    break

            client_socket, addr = await self.before_request(client_socket, addr)
            await self.app.signal.before_request.async_send(kwargs = {
                'client_socket': client_socket,
                'addr': addr
            })

            request = Request(self.app, client_socket, addr)
            try:
                response = await request._proxy.recv_headers(keep_alive_max_requests != 0)
                if response:
                    yield request, response
                    continue
                await request._proxy.parse_headers()
            except ConnectionAbortedError:
                raise
            except asyncio.TimeoutError:
                break
            except:
                yield request, Response(status = 400)
                continue

            route = self.app.route._proxy.get_route(request.method, request.path)
            if route == 404:
                if request.method == 'GET':
                    yield request, await self.get_static_response(request.path)
                    continue
                yield request, Response(status = 404)
                continue
            elif route == 405:
                yield request, await self.get_cors_response(request)
                continue

            request._params = route[1]
            request._fn = route[0]['fn']
            if route[0]['auto_recv_body'] is True:
                try:
                    response = await request.recv_body(True)
                    if type(response) is Response:
                        yield request, response
                        continue
                    await request.parse_body()
                except ConnectionAbortedError:
                    raise
                except asyncio.TimeoutError:
                    yield request, Response(status = 408)
                    continue
                except:
                    yield request, Response(status = 400)
                    continue

            yield request, None

    async def get_static_response(self, path: str) -> Response:
        for url, _path in self.app.static_path.items():
            if path.startswith(url) is False:
                continue

            relative_path = path[len(url):]
            if relative_path.startswith('/'):
                relative_path = relative_path[1:]

            path = os.path.join(_path, relative_path)
            if not os.path.abspath(path).startswith(os.path.abspath(_path)):
                return Response(status = 403)

            if os.path.exists(path):
                if os.path.isfile(path):
                    return FileResponse(path)
                elif os.path.isdir(path):
                    path = os.path.join(path, 'index.html')
                    if os.path.exists(path) and os.path.isfile(path):
                        return FileResponse(path)

        return Response(status = 404)

    async def get_cors_response(self, request: Request) -> Response:
        route = self.app.route._proxy.get_route(request.method, request.path)
        if route != 405:
            if route[0]['cors']:
                return route[0]['cors'].get_response(request)
            else:
                return self.app.cors.get_response(request)
        return Response(status = 405)

    async def before_request(self, client_socket: socket.socket, addr: tuple[str, int]) -> tuple[socket.socket, tuple]:
        return client_socket, addr

    async def after_request(self, request: Request | None) -> Request | None:
        return request

    async def before_worker_stop(self, is_first: bool):
        ...

    def after_worker_stop(self, is_first: bool):
        ...

    async def before_response(self, response: Response) -> Response:
        return response

    async def after_response(self, response: Response):
        ...

class CheeseAPI:
    __slots__ = ('_host', '_port', '_ipv6', '_logger_path', '_dual_stack', '_socket_backlog', '_socket_send_buffer_size', '_socket_receive_buffer_size', '_workers', '_ssl_cert', '_ssl_key', '_sync_server_url', '_static_path', '_printer', '_compress', '_compress_min_length', '_compress_level', '_manual_modules', '_exclude_modules', '_priority_modules', '_sync_server_data_encode', '_sync_server_data_decode', '_logger_messages', '_logger', '_is_running', '_request_timeout', '_keep_alive', '_keep_alive_timeout', '_keep_alive_max_requests', '_AppProxy_Class', '_RequestProxy_Class', '_proxy', '_signal', '_ResponseProxy_Class', '_RouteProxy_Class', '_route', '_WebsocketProxy_Class', '_cors', '_SchedulerProxy_Class', '_scheduler')

    def __init__(self, host: str | None = None, port: int = 5214, *, ipv6: bool = False, logger_path: str | None = None, dual_stack: bool = False, socket_backlog: int | None = None, socket_send_buffer_size: int | None = None, socket_receive_buffer_size: int | None = None, workers: int = 1, ssl_cert: str | None = None, ssl_key: str | None = None, sync_server_url: str | None = None, static_path: dict[str, str] = {}, printer: Type[Printer] = Printer, compress: list[Literal['gzip', 'br', 'zstd', 'deflate']] = ['gzip', 'br', 'zstd', 'deflate'], compress_min_length: int = 1024, compress_level: int = 6, manual_modules: list[str] = [], exclude_modules: list[str] = [], priority_modules: list[str] = [], sync_server_data_encode: Callable[[bytes], bytes] | None = None, sync_server_data_decode: Callable[[bytes], bytes] | None = None, logger_messages: dict[str, 'Message'] = {}, request_timeout: float | None = None, keep_alive: bool = True, keep_alive_timeout: float = 5, keep_alive_max_requests: int = 100, AppProxy_Class: Type[AppProxy] = AppProxy, RequestProxy_Class: Type[RequestProxy] = RequestProxy, ResponseProxy_Class: Type[ResponseProxy] = ResponseProxy, RouteProxy_Class: Type[RouteProxy] = RouteProxy, cors_allow_origins: list[str] = ['*'], cors_allow_methods: Literal['GET', 'PUT', 'POST', 'DELETE', 'PATCH', 'OPTIONS', 'HEAD', 'CONNECT'] = ['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS', 'HEAD', 'PATCH', 'CONNECT'], cors_allow_headers: list[str] = ['*'], cors_allow_credentials: bool = True, cors_expose_headers: list[str] = [], cors_max_age: int | None = None, WebsocketProxy_Class: Type[WebsocketProxy] = WebsocketProxy, route_patterns: list['Pattern'] = [], SchedulerProxy_Class: Type[SchedulerProxy] = SchedulerProxy):
        '''
        - Args
            - logger_path: 日志文件路径，支持日期格式化
            - dual_stack: 是否启用双栈支持；若系统不支持，则自动回退
            - socket_backlog: 最大连接数
            - socket_send_buffer_size: 发送缓冲区大小
            - socket_receive_buffer_size: 接收缓冲区大小
            - workers: 工作进程数
            - ssl_cert: SSL 证书路径
            - ssl_key: SSL 密钥路径
            - sync_server_url: 同步服务器地址，用于多进程间同步数据；支持redis
            - static_path: 静态文件路径映射，格式为 `{url_path: file_system_path}`
            - printer: 自定义消息输出
            - compress: 支持的压缩算法，按照顺序尝试压缩
            - compress_min_length: 启用压缩的最小响应体长度
            - compress_level: 压缩等级，每个算法的压缩级别可能不同，详见各算法文档
            - manual_modules: 手动加载的模块列表
            - exclude_modules: 排除加载的模块列表
            - priority_modules: 优先加载的模块列表
            - sync_server_data_encode: 同步服务器数据编码处理函数
            - sync_server_data_decode: 同步服务器数据解码处理函数
            - logger_messages: 归属于 CheeseAPI 日志的消息列表
            - keep_alive: 是否启用长连接
            - keep_alive_max_requests: 长连接最大请求次数
            - AppProxy_Class: 若想要对底层逻辑进行处理，可传入自定义的 AppProxy 类
            - RequestProxy_Class: 若想要对请求处理逻辑进行处理，可传入自定义的 RequestProxy 类
            - ResponseProxy_Class: 若想要对响应处理逻辑进行处理，可传入自定义的 ResponseProxy 类
            - RouteProxy_Class: 若想要对路由处理逻辑进行处理，可传入自定义的 RouteProxy 类
            - WebsocketProxy_Class: 若想要对 Websocket 处理逻辑进行处理，可传入自定义的 WebsocketProxy 类
            - route_patterns: 自定义路由校验规则
            - SchedulerProxy_Class: 自定义任务调度器代理类
        '''

        self._host: str = host if host is not None else ('::' if ipv6 else '0.0.0.0')
        self._port: int = port
        self._ipv6: bool = ipv6
        self._logger_path: str | None = logger_path
        self._dual_stack: bool = dual_stack
        self._socket_backlog: int | None = socket_backlog
        self._socket_send_buffer_size: int | None = socket_send_buffer_size
        self._socket_receive_buffer_size: int | None = socket_receive_buffer_size
        self._workers: int = workers
        self._ssl_cert: str | None = ssl_cert
        self._ssl_key: str | None = ssl_key
        self._sync_server_url: str | None = sync_server_url
        self._static_path: dict[str, str] = static_path
        self._printer: Type[Printer] = printer(self)
        self._compress: list[Literal['gzip', 'br', 'zstd', 'deflate']] = compress
        self._compress_min_length: int = compress_min_length
        self._compress_level: int = compress_level
        self._manual_modules: list[str] = manual_modules
        self._exclude_modules: list[str] = exclude_modules
        self._priority_modules: list[str] = priority_modules
        self._sync_server_data_encode: Callable[[bytes], bytes] | None = sync_server_data_encode
        self._sync_server_data_decode: Callable[[bytes], bytes] | None = sync_server_data_decode
        self._logger_messages: dict[str, Message] = logger_messages
        self._request_timeout: float | None = request_timeout
        self._keep_alive: bool = keep_alive
        self._keep_alive_timeout: float = keep_alive_timeout
        self._keep_alive_max_requests: int = keep_alive_max_requests
        self._AppProxy_Class: Type[AppProxy] = AppProxy_Class
        self._RequestProxy_Class: Type[RequestProxy] = RequestProxy_Class
        self._ResponseProxy_Class: Type[ResponseProxy] = ResponseProxy_Class
        self._RouteProxy_Class: Type[RouteProxy] = RouteProxy_Class
        self._WebsocketProxy_Class: Type[WebsocketProxy] = WebsocketProxy_Class
        self._SchedulerProxy_Class: Type[SchedulerProxy] = SchedulerProxy_Class

        self._logger: CheeseLogger = CheeseLogger(self.logger_path, messages = {
            'START': Message('START', 20, message_template_styled = '(<green>%k</green>) <black>%t</black> > %c'),
            'STOP': Message('STOP', 20, message_template_styled = '(<green>%k</green>) <black>%t</black> > %c'),
            'HTTP': Message('HTTP', 20, message_template_styled = '(<blue>%k</blue>) <black>%t</black> > %c'),
            'WEBSOCKET': Message('WEBSOCKET', 20, message_template_styled = '(<blue>%k</blue>) <black>%t</black> > %c'),
            'LOADING': Message('LOADING', 15, message_template_styled = '(<blue>%k</blue>) <black>%t</black> > %c'),
            'LOADED': Message('LOADED', 15, message_template_styled = '(<cyan>%k</cyan>) <black>%t</black> > %c'),
            **self.logger_messages
        })
        self._is_running: bool = False
        self._proxy: Type[AppProxy] = self._AppProxy_Class(self)
        self._signal: Signal = Signal(self)
        self._route: AppRoute = AppRoute(self)
        self._cors: CORS = CORS(cors_allow_origins, cors_allow_methods, cors_allow_headers, cors_allow_credentials, cors_expose_headers, cors_max_age)
        self._scheduler: Scheduler = Scheduler(self)

        self.route.patterns.extend(route_patterns)
        self.route.patterns.sort(key = lambda x: x['weight'], reverse = True)

    def __setstate__(self, state: tuple[None, dict[str, any]]):
        for key, value in state[1].items():
            setattr(self, key, value)

        if self.sync_server_url and WebsocketProxy.sync_servers is None:
            WebsocketProxy.sync_servers = (redis.Redis.from_url(self.sync_server_url), redis.asyncio.Redis.from_url(self.sync_server_url))
        if WebsocketProxy.data_encode is None:
            WebsocketProxy.data_encode = self.sync_server_data_encode
        if WebsocketProxy.data_decode is None:
            WebsocketProxy.data_decode = self.sync_server_data_decode

    def start(self):
        self._proxy.start()

    def stop(self):
        os.killpg(os.getpgid(os.getpid()), signal.SIGINT)

    @property
    def host(self) -> str:
        return self._host

    @property
    def port(self) -> int:
        return self._port

    @property
    def ipv6(self) -> bool:
        return self._ipv6

    @property
    def logger_path(self) -> str | None:
        '''
        日志文件路径，支持日期格式化
        '''

        return self._logger_path

    @property
    def dual_stack(self) -> bool:
        '''
        是否启用双栈支持；若系统不支持，则自动回退
        '''

        return self._dual_stack

    @property
    def socket_backlog(self) -> int | None:
        '''
        最大连接数
        '''

        return self._socket_backlog

    @property
    def socket_send_buffer_size(self) -> int | None:
        '''
        发送缓冲区大小
        '''

        return self._socket_send_buffer_size

    @property
    def socket_receive_buffer_size(self) -> int | None:
        '''
        接收缓冲区大小
        '''

        return self._socket_receive_buffer_size

    @property
    def workers(self) -> int:
        '''
        工作进程数
        '''

        return self._workers

    @property
    def ssl_cert(self) -> str | None:
        '''
        SSL 证书路径
        '''

        return self._ssl_cert

    @property
    def ssl_key(self) -> str | None:
        '''
        SSL 密钥路径
        '''

        return self._ssl_key

    @property
    def sync_server_url(self) -> str | None:
        '''
        同步服务器地址，用于多进程间同步数据；支持redis
        '''

        return self._sync_server_url

    @property
    def static_path(self) -> dict[str, str]:
        '''
        静态文件路径映射，格式为`{url_path: file_system_path}`
        '''

        return self._static_path

    @property
    def printer(self) -> Type[Printer]:
        '''
        自定义消息输出
        '''

        return self._printer

    @property
    def compress(self) -> list[Literal['gzip', 'br', 'zstd', 'deflate']]:
        '''
        支持的压缩算法，按照顺序尝试压缩
        '''

        return self._compress

    @property
    def compress_min_length(self) -> int:
        '''
        启用压缩的最小响应体长度
        '''

        return self._compress_min_length

    @property
    def compress_level(self) -> int:
        '''
        压缩等级，每个算法的压缩级别可能不同，详见各算法文档
        '''

        return self._compress_level

    @property
    def manual_modules(self) -> list[str]:
        '''
        手动加载的模块列表
        '''

        return self._manual_modules

    @property
    def exclude_modules(self) -> list[str]:
        '''
        排除加载的模块列表
        '''

        return self._exclude_modules

    @property
    def priority_modules(self) -> list[str]:
        '''
        优先加载的模块列表
        '''

        return self._priority_modules

    @property
    def sync_server_data_encode(self) -> Callable[[bytes], bytes] | None:
        '''
        同步服务器数据编码处理函数
        '''

        return self._sync_server_data_encode

    @property
    def sync_server_data_decode(self) -> Callable[[bytes], bytes] | None:
        '''
        同步服务器数据解码处理函数
        '''

        return self._sync_server_data_decode

    @property
    def logger_messages(self) -> dict[str, 'Message']:
        '''
        归属于 CheeseAPI 日志的消息列表
        '''

        return self._logger_messages

    @property
    def logger(self) -> CheeseLogger:
        '''
        归属于 CheeseAPI 日志实例
        '''

        return self._logger

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def signal(self) -> Signal:
        return self._signal

    @property
    def request_timeout(self) -> float | None:
        return self._request_timeout

    @property
    def keep_alive(self) -> bool:
        '''
        是否启用长连接
        '''

        return self._keep_alive

    @property
    def keep_alive_timeout(self) -> float:
        return self._keep_alive_timeout

    @property
    def keep_alive_max_requests(self) -> int:
        '''
        长连接最大请求次数
        '''

        return self._keep_alive_max_requests

    @property
    def AppProxy_Class(self) -> Type[AppProxy]:
        '''
        若想要对底层逻辑进行处理，可传入自定义的 AppProxy 类
        '''

        return self._AppProxy_Class

    @property
    def RequestProxy_Class(self) -> Type[RequestProxy]:
        '''
        若想要对请求处理逻辑进行处理，可传入自定义的 RequestProxy 类
        '''

        return self._RequestProxy_Class

    @property
    def ResponseProxy_Class(self) -> Type[ResponseProxy]:
        '''
        若想要对响应处理逻辑进行处理，可传入自定义的 ResponseProxy 类
        '''

        return self._ResponseProxy_Class

    @property
    def RouteProxy_Class(self) -> Type[RouteProxy]:
        '''
        若想要对路由处理逻辑进行处理，可传入自定义的 RouteProxy 类
        '''

        return self._RouteProxy_Class

    @property
    def route(self) -> AppRoute:
        '''
        总路由
        '''

        return self._route

    @property
    def cors(self) -> CORS:
        return self._cors

    @property
    def WebsocketProxy_Class(self) -> Type[WebsocketProxy]:
        '''
        若想要对 Websocket 处理逻辑进行处理，可传入自定义的 WebsocketProxy 类
        '''

        return self._WebsocketProxy_Class

    @property
    def scheduler(self) -> 'Scheduler':
        '''
        任务调度
        '''

        return self._scheduler

    @property
    def SchedulerProxy_Class(self) -> Type[SchedulerProxy]:
        '''
        自定义任务调度器代理类
        '''

        return self._SchedulerProxy_Class
