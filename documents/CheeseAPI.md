# **CheeseAPI**

```python
from CheeseAPI import CheeseAPI

app = CheeseAPI()
```

## **`def __init__(self, host: str | None = None, port: int = 5214, *, ipv6: bool = False, logger_path: str | None = None, dual_stack: bool = False, socket_backlog: int | None = None, socket_send_buffer_size: int | None = None, socket_receive_buffer_size: int | None = None, workers: int = 1, ssl_cert: str | None = None, ssl_key: str | None = None, sync_server_url: str | None = None, static_path: dict[str, str] = {}, printer: Type[Printer] = Printer, compress: list[Literal['gzip', 'br', 'zstd', 'deflate']] = ['gzip', 'br', 'zstd', 'deflate'], compress_min_length: int = 1024, compress_level: int = 6, manual_modules: list[str] = [], exclude_modules: list[str] = [], priority_modules: list[str] = [], sync_server_data_encode: Callable[[bytes], bytes] | None = None, sync_server_data_decode: Callable[[bytes], bytes] | None = None, logger_messages: dict[str, 'Message'] = {}, request_timeout: float | None = None, keep_alive: bool = True, keep_alive_timeout: float = 5, keep_alive_max_requests: int = 100, AppProxy_Class: Type[AppProxy] = AppProxy, RequestProxy_Class: Type[RequestProxy] = RequestProxy, ResponseProxy_Class: Type[ResponseProxy] = ResponseProxy, RouteProxy_Class: Type[RouteProxy] = RouteProxy, cors_allow_origins: list[str] = ['*'], cors_allow_methods: Literal['GET', 'PUT', 'POST', 'DELETE', 'PATCH', 'OPTIONS', 'HEAD', 'CONNECT'] = ['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS', 'HEAD', 'PATCH', 'CONNECT'], cors_allow_headers: list[str] = ['*'], cors_allow_credentials: bool = True, cors_expose_headers: list[str] = [], cors_max_age: int | None = None, WebsocketProxy_Class: Type[WebsocketProxy] = WebsocketProxy, route_patterns: list['Pattern'] = [], SchedulerProxy_Class: Type[SchedulerProxy] = SchedulerProxy)`**

- **Args**

    - **logger_path**

        日志文件路径，支持日期格式化

    - **dual_stack**

        是否启用双栈支持；若系统不支持，则自动回退

    - **socket_backlog**

        最大连接数

    - **socket_send_buffer_size**

        发送缓冲区大小

    - **socket_receive_buffer_size**

        接收缓冲区大小

    - **workers**

        工作进程数

    - **ssl_cert**

        SSL 证书路径

    - **ssl_key**

        SSL 密钥路径

    - **sync_server_url**

        同步服务器地址，用于多进程间同步数据；支持redis

    - **static_path**

        静态文件路径映射，格式为 `{url_path: file_system_path}`

    - **printer**

        自定义消息输出

    - **compress**

        支持的压缩算法，按照顺序尝试压缩

    - **compress_min_length**

        启用压缩的最小响应体长度

    - **compress_level**

        压缩等级，每个算法的压缩级别可能不同，详见各算法文档

    - **manual_modules**

        手动加载的模块列表；若想要加载多层级模块，请使用点号分隔，如 `Xxx.module`，与导入模块的方式一致

    - **exclude_modules**

        排除加载的模块列表

    - **priority_modules**

        优先加载的模块列表

    - **sync_server_data_encode**

        同步服务器数据编码处理函数

    - **sync_server_data_decode**

        同步服务器数据解码处理函数

    - **logger_messages**

        归属于 CheeseAPI 日志的消息列表

    - **keep_alive**

        是否启用长连接

    - **keep_alive_max_requests**

        长连接最大请求次数

    - **AppProxy_Class**

        若想要对底层逻辑进行处理，可传入自定义的 AppProxy 类

    - **RequestProxy_Class**

        若想要对请求处理逻辑进行处理，可传入自定义的 RequestProxy 类

    - **ResponseProxy_Class**

        若想要对响应处理逻辑进行处理，可传入自定义的 ResponseProxy 类

    - **RouteProxy_Class**

        若想要对路由处理逻辑进行处理，可传入自定义的 RouteProxy 类

    - **WebsocketProxy_Class**

        若想要对 Websocket 处理逻辑进行处理，可传入自定义的 WebsocketProxy 类

    - **route_patterns**

        自定义路由校验规则

    - **SchedulerProxy_Class**

        若想要对定时任务处理逻辑进行处理，可传入自定义的 SchedulerProxy 类

## **`self.host: str`**

## **`self.port: int`**

## **`self.ipv6: bool`**

## **`self.logger_path: str | None`**

日志文件路径，支持日期格式化

## **`self.dual_stack: bool`**

是否启用双栈支持；若系统不支持，则自动回退

## **`self.socket_backlog: int | None`**

最大连接数

## **`self.socket_send_buffer_size: int | None`**

发送缓冲区大小

## **`self.socket_receive_buffer_size: int | None`**

接收缓冲区大小

## **`self.workers: int`**

工作进程数

## **`self.ssl_cert: str | None`**

SSL 证书路径

## **`self.ssl_key: str | None`**

SSL 密钥路径

## **`self.sync_server_url: str | None`**

同步服务器地址，用于多进程间同步数据；支持redis

## **`self.static_path: dict[str, str]`**

静态文件路径映射，格式为 `{url_path: file_system_path}`

## **`self.printer: Type[Printer]`**

自定义消息输出

## **`self.compress: list[Literal['gzip', 'br', 'zstd', 'deflate']]`**

支持的压缩算法，按照顺序尝试压缩

## **`self.compress_min_length: int`**

启用压缩的最小响应体长度

## **`self.compress_level: int`**

压缩等级，每个算法的压缩级别可能不同，详见各算法文档

## **`self.manual_modules: list[str]`**

手动加载的模块列表；若想要加载多层级模块，请使用点号分隔，如 `Xxx.module`，与导入模块的方式一致

## **`self.exclude_modules: list[str]`**

排除加载的模块列表

## **`self.priority_modules: list[str]`**

优先加载的模块列表

## **`self.sync_server_data_encode: Callable[[bytes], bytes] | None`**

同步服务器数据编码处理函数

## **`self.sync_server_data_decode: Callable[[bytes], bytes] | None`**

同步服务器数据解码处理函数

## **`self.logger_messages: dict[str, 'Message']`**

归属于 CheeseAPI 日志的消息列表

## **`self.logger: CheeseLogger`**

归属于 CheeseAPI 日志实例

## **`self.is_running: bool`**

## **`self.signal: Signal`**

## **`self.request_timeout: float | None`**

## **`self.keep_alive: bool`**

是否启用长连接

## **`self.keep_alive_timeout: float`**

## **`self.keep_alive_max_requests: int`**

长连接最大请求次数

## **`self.AppProxy_Class: Type[AppProxy]`**

若想要对底层逻辑进行处理，可传入自定义的 AppProxy 类

## **`self.RequestProxy_Class: Type[RequestProxy]`**

若想要对请求处理逻辑进行处理，可传入自定义的 RequestProxy 类

## **`self.ResponseProxy_Class: Type[ResponseProxy]`**

若想要对响应处理逻辑进行处理，可传入自定义的 ResponseProxy 类

## **`self.RouteProxy_Class: Type[RouteProxy]`**

若想要对路由处理逻辑进行处理，可传入自定义的 RouteProxy 类

## **`self.WebsocketProxy_Class: Type[WebsocketProxy]`**

若想要对 Websocket 处理逻辑进行处理，可传入自定义的 WebsocketProxy 类

## **`self.route: AppRoute`**

总路由

## **`self.cors: CORS`**

## **`self.scheduler: Scheduler`**

任务调度

## **`self.SchedulerProxy_Class: Type[SchedulerProxy]`**

若想要对定时任务处理逻辑进行处理，可传入自定义的 SchedulerProxy 类

## **`def start(self)`**

启动服务器

## **`def stop(self)`**

停止服务器
