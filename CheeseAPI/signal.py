from typing import TYPE_CHECKING

from CheeseSignal import Signal as CheeseSignal

if TYPE_CHECKING:
    from CheeseAPI.app import CheeseAPI

class Signal:
    __slots__ = ('_app', '_before_load_module', '_after_load_module', '_before_load_modules', '_after_load_modules', '_before_server_start', '_after_server_start', '_before_app_stop', '_after_app_stop', '_before_workers_start', '_after_workers_start', '_before_worker_start', '_after_worker_start', '_before_worker_stop', '_after_worker_stop', '_before_request', '_after_request', '_before_response', '_after_response')

    def __init__(self, app: 'CheeseAPI'):
        self._app: 'CheeseAPI' = app

        self._before_load_module = CheeseSignal()
        self._after_load_module = CheeseSignal()
        self._before_load_modules = CheeseSignal()
        self._after_load_modules = CheeseSignal()
        self._before_server_start = CheeseSignal()
        self._after_server_start = CheeseSignal()
        self._before_app_stop = CheeseSignal()
        self._after_app_stop = CheeseSignal()
        self._before_workers_start = CheeseSignal()
        self._after_workers_start = CheeseSignal()
        self._before_worker_start = CheeseSignal()
        self._after_worker_start = CheeseSignal()
        self._before_worker_stop = CheeseSignal()
        self._after_worker_stop = CheeseSignal()
        self._before_request = CheeseSignal()
        self._after_request = CheeseSignal()
        self._before_response = CheeseSignal()
        self._after_response = CheeseSignal()

    @property
    def app(self) -> 'CheeseAPI':
        return self._app

    @property
    def before_load_module(self) -> CheeseSignal:
        '''
        绑定函数`def func(*, index: int, module: str)`
        '''

        return self._before_load_module

    @property
    def after_load_module(self) -> CheeseSignal:
        '''
        绑定函数`def func(*, index: int, module: str)`
        '''

        return self._after_load_module

    @property
    def before_load_modules(self) -> CheeseSignal:
        '''
        绑定函数`def func(*, modules: list[str])`
        '''

        return self._before_load_modules

    @property
    def after_load_modules(self) -> CheeseSignal:
        '''
        绑定函数`def func(*, modules: list[str])`
        '''

        return self._after_load_modules

    @property
    def before_server_start(self) -> CheeseSignal:
        return self._before_server_start

    @property
    def after_server_start(self) -> CheeseSignal:
        return self._after_server_start

    @property
    def before_app_stop(self) -> CheeseSignal:
        return self._before_app_stop

    @property
    def after_app_stop(self) -> CheeseSignal:
        return self._after_app_stop

    @property
    def before_workers_start(self) -> CheeseSignal:
        '''
        绑定函数`def func(*, workers: int)`
        '''

        return self._before_workers_start

    @property
    def after_workers_start(self) -> CheeseSignal:
        '''
        绑定函数`def func(*, workers: int)`
        '''

        return self._after_workers_start

    @property
    def before_worker_start(self) -> CheeseSignal:
        '''
        绑定函数`def func(*, is_first: bool)`
        '''

        return self._before_worker_start

    @property
    def after_worker_start(self) -> CheeseSignal:
        '''
        绑定协程函数`async def func(*, is_first: bool)`
        '''

        return self._after_worker_start

    @property
    def before_worker_stop(self) -> CheeseSignal:
        '''
        绑定协程函数`async def func(*, is_first: bool)`
        '''

        return self._before_worker_stop

    @property
    def after_worker_stop(self) -> CheeseSignal:
        '''
        绑定函数`def func(*, is_first: bool)`
        '''

        return self._after_worker_stop

    @property
    def before_request(self) -> CheeseSignal:
        '''
        绑定协程函数`async def func(*, client_socket: socket.socket, addr: tuple[str, int])`
        '''

        return self._before_request

    @property
    def after_request(self) -> CheeseSignal:
        '''
        绑定协程函数`async def func(*, request: Request | None)`
        '''

        return self._after_request

    @property
    def before_response(self) -> CheeseSignal:
        '''
        绑定协程函数`async def func(*, response: Response) -> Response`
        '''

        return self._before_response

    @property
    def after_response(self) -> CheeseSignal:
        '''
        绑定协程函数`async def func(*, response: Response)`
        '''

        return self._after_response
