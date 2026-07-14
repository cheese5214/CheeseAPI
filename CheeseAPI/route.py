import re, uuid
from typing import Literal, TypedDict, Callable, TYPE_CHECKING, AsyncIterable, Union

from urllib.parse import unquote

from CheeseAPI.cors import CORS

if TYPE_CHECKING:
    from CheeseAPI.websocket import Websocket
    from CheeseAPI.app import CheeseAPI

HTTP_METHOD_TYPE = Literal['CONNECT', 'DELETE', 'GET', 'HEAD', 'OPTIONS', 'PATCH', 'POST', 'PUT', 'TRACE', 'WEBSOCKET']

class Pattern(TypedDict):
    pattern: re.Pattern
    weight: int
    ''' 权重；越高权重，匹配优先级越高 '''
    type: type
    ''' 数据类型；应当为对应的 Python 类型，执行该类型转换后应当返还一个对应类型的值 '''
    key: str

class RouteDict(TypedDict):
    fn: Callable | 'Websocket'
    cors: CORS | None
    params: dict[str, type] | None
    auto_recv_body: bool

class Route:
    __slots__ = ('_path', '_proxy')

    def __init__(self, path: str, app: 'CheeseAPI'):
        '''
        - Args
            - path: 路由前缀
        '''

        self._path: str = path

        self._proxy: RouteProxy = app.RouteProxy_Class(app, self)

    def add(self, method_or_methods: list[HTTP_METHOD_TYPE] | HTTP_METHOD_TYPE, path: str, fn: Callable | 'Websocket' | AsyncIterable | None = None, *, allow_origins: list[str] | None = None, allow_methods: list[HTTP_METHOD_TYPE] | None = None, allow_headers: list[str] | None = None, allow_credentials: bool | None = None, expose_headers: list[str] | None = None, max_age: int | None = None, auto_recv_body: bool = True):
        '''
        - Args
            - auto_recv_body: 是否自动接收响应的 body，若否则自行调用 `request.recv_body()` 接收，并自行调用 `request.parse_body()` 解析
        '''

        if allow_origins is not None or allow_methods is not None or allow_headers is not None or allow_credentials is not None or expose_headers or max_age is not None:
            cors = CORS(allow_origins = allow_origins, allow_methods = allow_methods, allow_headers = allow_headers, allow_credentials = allow_credentials, expose_headers = expose_headers, max_age = max_age)
        else:
            cors = None

        methods = method_or_methods if isinstance(method_or_methods, list) else [method_or_methods]
        if fn is not None:
            for method in methods:
                self._proxy.add_route(method, f'{self.path}{path}', fn, cors, auto_recv_body)
        else:
            def wrapper(_fn: Callable | AsyncIterable | 'Websocket'):
                for method in methods:
                    self._proxy.add_route(method, f'{self.path}{path}', _fn, cors, auto_recv_body)
                return _fn
            return wrapper

    def get(self, path: str, fn: Callable | AsyncIterable | None = None, *, allow_origins: list[str] | None = None, allow_methods: list[HTTP_METHOD_TYPE] | None = None, allow_headers: list[str] | None = None, allow_credentials: bool | None = None, expose_headers: list[str] | None = None, max_age: int | None = None, auto_recv_body: bool = True):
        '''
        - Args
            - auto_recv_body: 是否自动接收响应的 body，若否则自行调用 `request.recv_body()` 接收，并自行调用 `request.parse_body()` 解析
        '''

        return self.add('GET', path, fn, allow_origins = allow_origins, allow_methods = allow_methods, allow_headers = allow_headers, allow_credentials = allow_credentials, expose_headers = expose_headers, max_age = max_age, auto_recv_body = auto_recv_body)

    def post(self, path: str, fn: Callable |AsyncIterable | None = None, *, allow_origins: list[str] | None = None, allow_methods: list[HTTP_METHOD_TYPE] | None = None, allow_headers: list[str] | None = None, allow_credentials: bool | None = None, expose_headers: list[str] | None = None, max_age: int | None = None, auto_recv_body: bool = True):
        '''
        - Args
            - auto_recv_body: 是否自动接收响应的 body，若否则自行调用 `request.recv_body()` 接收，并自行调用 `request.parse_body()` 解析
        '''

        return self.add('POST', path, fn, allow_origins = allow_origins, allow_methods = allow_methods, allow_headers = allow_headers, allow_credentials = allow_credentials, expose_headers = expose_headers, max_age = max_age, auto_recv_body = auto_recv_body)

    def websocket(self, path: str, fn: Union['Websocket', None] = None, *, allow_origins: list[str] | None = None, allow_methods: list[HTTP_METHOD_TYPE] | None = None, allow_headers: list[str] | None = None, allow_credentials: bool | None = None, expose_headers: list[str] | None = None, max_age: int | None = None):
        return self.add('WEBSOCKET', path, fn, allow_origins = allow_origins, allow_methods = allow_methods, allow_headers = allow_headers, allow_credentials = allow_credentials, expose_headers = expose_headers, max_age = max_age, auto_recv_body = True)

    def delete(self, path: str, fn: Callable |AsyncIterable | None = None, *, allow_origins: list[str] | None = None, allow_methods: list[HTTP_METHOD_TYPE] | None = None, allow_headers: list[str] | None = None, allow_credentials: bool | None = None, expose_headers: list[str] | None = None, max_age: int | None = None, auto_recv_body: bool = True):
        '''
        - Args
            - auto_recv_body: 是否自动接收响应的 body，若否则自行调用 `request.recv_body()` 接收，并自行调用 `request.parse_body()` 解析
        '''

        return self.add('DELETE', path, fn, allow_origins = allow_origins, allow_methods = allow_methods, allow_headers = allow_headers, allow_credentials = allow_credentials, expose_headers = expose_headers, max_age = max_age, auto_recv_body = auto_recv_body)

    def put(self, path: str, fn: Callable |AsyncIterable | None = None, *, allow_origins: list[str] | None = None, allow_methods: list[HTTP_METHOD_TYPE] | None = None, allow_headers: list[str] | None = None, allow_credentials: bool | None = None, expose_headers: list[str] | None = None, max_age: int | None = None, auto_recv_body: bool = True):
        '''
        - Args
            - auto_recv_body: 是否自动接收响应的 body，若否则自行调用 `request.recv_body()` 接收，并自行调用 `request.parse_body()` 解析
        '''

        return self.add('PUT', path, fn, allow_origins = allow_origins, allow_methods = allow_methods, allow_headers = allow_headers, allow_credentials = allow_credentials, expose_headers = expose_headers, max_age = max_age, auto_recv_body = auto_recv_body)

    def patch(self, path: str, fn: Callable |AsyncIterable | None = None, *, allow_origins: list[str] | None = None, allow_methods: list[HTTP_METHOD_TYPE] | None = None, allow_headers: list[str] | None = None, allow_credentials: bool | None = None, expose_headers: list[str] | None = None, max_age: int | None = None, auto_recv_body: bool = True):
        '''
        - Args
            - auto_recv_body: 是否自动接收响应的 body，若否则自行调用 `request.recv_body()` 接收，并自行调用 `request.parse_body()` 解析
        '''

        return self.add('PATCH', path, fn, allow_origins = allow_origins, allow_methods = allow_methods, allow_headers = allow_headers, allow_credentials = allow_credentials, expose_headers = expose_headers, max_age = max_age, auto_recv_body = auto_recv_body)

    def head(self, path: str, fn: Callable |AsyncIterable | None = None, *, allow_origins: list[str] | None = None, allow_methods: list[HTTP_METHOD_TYPE] | None = None, allow_headers: list[str] | None = None, allow_credentials: bool | None = None, expose_headers: list[str] | None = None, max_age: int | None = None, auto_recv_body: bool = True):
        '''
        - Args
            - auto_recv_body: 是否自动接收响应的 body，若否则自行调用 `request.recv_body()` 接收，并自行调用 `request.parse_body()` 解析
        '''

        return self.add('HEAD', path, fn, allow_origins = allow_origins, allow_methods = allow_methods, allow_headers = allow_headers, allow_credentials = allow_credentials, expose_headers = expose_headers, max_age = max_age, auto_recv_body = auto_recv_body)

    def options(self, path: str, fn: Callable |AsyncIterable | None = None, *, allow_origins: list[str] | None = None, allow_methods: list[HTTP_METHOD_TYPE] | None = None, allow_headers: list[str] | None = None, allow_credentials: bool | None = None, expose_headers: list[str] | None = None, max_age: int | None = None, auto_recv_body: bool = True):
        '''
        - Args
            - auto_recv_body: 是否自动接收响应的 body，若否则自行调用 `request.recv_body()` 接收，并自行调用 `request.parse_body()` 解析
        '''

        return self.add('OPTIONS', path, fn, allow_origins = allow_origins, allow_methods = allow_methods, allow_headers = allow_headers, allow_credentials = allow_credentials, expose_headers = expose_headers, max_age = max_age, auto_recv_body = auto_recv_body)

    def trace(self, path: str, fn: Callable |AsyncIterable | None = None, *, allow_origins: list[str] | None = None, allow_methods: list[HTTP_METHOD_TYPE] | None = None, allow_headers: list[str] | None = None, allow_credentials: bool | None = None, expose_headers: list[str] | None = None, max_age: int | None = None, auto_recv_body: bool = True):
        '''
        - Args
            - auto_recv_body: 是否自动接收响应的 body，若否则自行调用 `request.recv_body()` 接收，并自行调用 `request.parse_body()` 解析
        '''

        return self.add('TRACE', path, fn, allow_origins = allow_origins, allow_methods = allow_methods, allow_headers = allow_headers, allow_credentials = allow_credentials, expose_headers = expose_headers, max_age = max_age, auto_recv_body = auto_recv_body)

    def connect(self, path: str, fn: Callable |AsyncIterable | None = None, *, allow_origins: list[str] | None = None, allow_methods: list[HTTP_METHOD_TYPE] | None = None, allow_headers: list[str] | None = None, allow_credentials: bool | None = None, expose_headers: list[str] | None = None, max_age: int | None = None, auto_recv_body: bool = True):
        '''
        - Args
            - auto_recv_body: 是否自动接收响应的 body，若否则自行调用 `request.recv_body()` 接收，并自行调用 `request.parse_body()` 解析
        '''

        return self.add('CONNECT', path, fn, allow_origins = allow_origins, allow_methods = allow_methods, allow_headers = allow_headers, allow_credentials = allow_credentials, expose_headers = expose_headers, max_age = max_age, auto_recv_body = auto_recv_body)

    @property
    def path(self) -> str:
        ''' 路由前缀 '''

        return self._path

class AppRoute(Route):
    __slots__ = ('_routes', '_proxy', '_patterns')

    def __init__(self, app: 'CheeseAPI'):
        super().__init__('', app)

        self._routes: dict[str, dict[HTTP_METHOD_TYPE, RouteDict]] = {}
        self._patterns: list[Pattern] = [
            {
                'pattern': re.compile(r'-?(?:0|[1-9]\d*)'),
                'weight': 5,
                'type': int,
                'key': 'int'
            },
            {
                'pattern': re.compile(r'-?\d+\.\d+'),
                'weight': 5,
                'type': float,
                'key': 'float'
            },
            {
                'pattern': re.compile(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}'),
                'weight': 5,
                'type': uuid.UUID,
                'key': 'uuid'
            },
            {
                'pattern': re.compile(r'.+'),
                'weight': 0,
                'type': str,
                'key': 'str'
            }
        ]

    @property
    def patterns(self) -> list[Pattern]:
        ''' 动态路由匹配模式 '''

        return self._patterns

    @property
    def routes(self) -> dict[str, dict[HTTP_METHOD_TYPE, RouteDict]]:
        ''' 所有路由 '''

        return self._routes

class RouteProxy:
    __slots__ = ('app', 'is_root', 'dynamic_routes', 'route', 'dynamic_route_orders')

    def __init__(self, app: 'CheeseAPI', route: Route):
        self.app: 'CheeseAPI' = app
        self.route: Route = route

        self.dynamic_routes: dict[str, dict[HTTP_METHOD_TYPE, RouteDict]] = {}
        self.dynamic_route_orders: list[tuple[str, int]] = []

    def add_route(self, method: HTTP_METHOD_TYPE, path: str, fn: Callable | 'Websocket', cors: CORS | None, auto_recv_body: bool):
        if path not in self.app.route.routes:
            self.app.route.routes[path] = {}
        self.app.route.routes[path][method] = {
            'fn': fn,
            'cors': cors,
            'params': None,
            'auto_recv_body': auto_recv_body
        }

        if '<' in path and '>' in path and ':' in path:
            regex_path = f'^{path}$'
            params = {}
            weight = 0
            for match in re.finditer(r'<(\w+):(\w+)>', path):
                key = match.group(1)
                type = match.group(2)
                for pattern in self.app.route.patterns:
                    if pattern['key'] == type:
                        regex_path = regex_path.replace(f'<{key}:{type}>', f'({pattern["pattern"].pattern})')
                        params[key] = pattern['type']
                        weight += pattern['weight']
                        break

            if regex_path not in self.app.route._proxy.dynamic_routes:
                self.app.route._proxy.dynamic_routes[regex_path] = {}
            self.app.route._proxy.dynamic_routes[regex_path][method] = {
                'fn': fn,
                'cors': cors,
                'params': params,
                'auto_recv_body': auto_recv_body
            }
            self.app.route._proxy.dynamic_route_orders.append((regex_path, weight))

            self.app.route._proxy.dynamic_route_orders.sort(key = lambda x: x[1], reverse = True)

    def get_route(self, method: HTTP_METHOD_TYPE, path: str) -> tuple[RouteDict, dict] | Literal[404, 405]:
        if path in self.app.route.routes:
            if method in self.app.route.routes[path]:
                return (self.app.route.routes[path][method], {})
            else:
                return 405

        for _path, _ in self.app.route._proxy.dynamic_route_orders:
            match = re.match(_path, path)
            if match:
                if method in self.app.route._proxy.dynamic_routes[_path]:
                    _params = {}
                    i = 1
                    for key, type in self.app.route._proxy.dynamic_routes[_path][method]['params'].items():
                        value = match.group(i)
                        _params[key] = type(unquote(value))
                        i += 1
                    return self.app.route._proxy.dynamic_routes[_path][method], _params
                else:
                    return 405

        return 404
