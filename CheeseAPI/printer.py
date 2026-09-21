import traceback
from typing import TYPE_CHECKING

from CheeseLog import ProgressBar

if TYPE_CHECKING:
    from CheeseAPI.app import CheeseAPI
    from CheeseAPI.request import Request
    from CheeseAPI.response import Response
    from CheeseAPI.websocket import Websocket
    from CheeseAPI.scheduler import Task

HTTP_STATUS_COLOR: tuple[str] = ('blue', 'green', 'cyan', 'yellow', 'red')

MAX_ERROR_LINES: int = 50
''' 单条错误日志中堆栈的最大行数；超出部分会被截断，避免异常堆栈无限增长 '''

class Printer:
    __slots__ = ('_app', '_progress_bar')

    def __init__(self, app: 'CheeseAPI'):
        self._app: 'CheeseAPI' = app

        self._progress_bar: ProgressBar = ProgressBar()

    def app_start(self):
        self.app.logger.print('START', 'CheeseAPI is starting...')

    def load_module(self, module: str, percent: float):
        message, message_styled = self._progress_bar(percent)
        self.app.logger.print('LOADING', f'{message} {module}', f'{message_styled} {module}', refresh = False if percent == 0 else True)

    def modules_loaded(self, modules: list[str]):
        self.app.logger.print('LOADED', f'All modules loaded\n    {" | ".join(modules)}', f'All modules loaded\n    {" | ".join(modules)}', refresh = True)

    def server_start(self):
        self.app.logger.print('START', f'CheeseAPI is running on {self.app.host}:{self.app.port}', f'CheeseAPI is running on <cyan>{self.app.host}:{self.app.port}</cyan>')

    def _error(self) -> str:
        '''
        格式化当前异常的堆栈

        限制最大行数，避免反复报错时堆栈越来越长把日志写爆
        '''
        lines = traceback.format_exc()[:-1].splitlines()
        if len(lines) > MAX_ERROR_LINES:
            lines = lines[:MAX_ERROR_LINES] + [f'... truncated {len(lines) - MAX_ERROR_LINES} lines ...']
        return '\n'.join(lines).replace('\n', '\n    ')

    def app_error(self, e: Exception):
        error = self._error()
        self.app.logger.error(f'An error occurred causing the server to stop:\n    {error}', f'An error occurred causing the server to stop:\n    {self.app.logger.encode(error)}')

    def server_stop(self):
        self.app.logger.print('STOP', 'CheeseAPI is stopping...')

    def app_stop(self):
        self.app.logger.print('STOP', 'CheeseAPI has stopped')

    def fn_error(self, e: Exception, request: 'Request'):
        error = self._error()
        self.app.logger.danger(f'An error occurred causing the {request.ip} visited {request.method} {request.full_path}:\n    {error}', f'An error occurred causing the <cyan>{request.ip}</cyan> visited <cyan>{request.method} {self.app.logger.encode(request.full_path)}</cyan>:\n    {self.app.logger.encode(error)}')

    def websocket_error(self, e: Exception, websocket: 'Websocket'):
        error = self._error()
        self.app.logger.danger(f'An error occurred causing the {websocket.request.ip} disconnected  {websocket.request.method} {websocket.request.full_path}:\n    {error}', f'An error occurred causing the <cyan>{websocket.request.ip}</cyan> disconnected <cyan>{websocket.request.method} {self.app.logger.encode(websocket.request.full_path)}</cyan>:\n    {self.app.logger.encode(error)}')

    def response(self, request: 'Request', response: 'Response'):
        status_color = HTTP_STATUS_COLOR[int(response.status / 100) - 1]
        if request.path is not None:
            self.app.logger.print('HTTP', f'The {request.ip} visited {request.method} {request.full_path} and returned {response.status}', f'The <cyan>{request.ip}</cyan> visited <cyan>{request.method} {self.app.logger.encode(request.full_path)}</cyan> returned <{status_color}>{response.status}</{status_color}>')
        else:
            self.app.logger.print('HTTP', f'The request from {request.ip} failed to parse and returned {response.status}', f'The request from <cyan>{request.ip}</cyan> failed to parse and returned <{status_color}>{response.status}</{status_color}>')

    def websocket_connect(self, websocket: 'Websocket'):
        self.app.logger.print('WEBSOCKET', f'The {websocket.request.ip} connected {websocket.request.method} {websocket.request.full_path}', f'The <cyan>{websocket.request.ip}</cyan> connected <cyan>{websocket.request.method} {self.app.logger.encode(websocket.request.full_path)}</cyan>')

    def websocket_disconnect(self, websocket: 'Websocket'):
        self.app.logger.print('WEBSOCKET', f'The {websocket.request.ip} disconnected {websocket.request.method} {websocket.request.full_path}', f'The <cyan>{websocket.request.ip}</cyan> disconnected <cyan>{websocket.request.method} {self.app.logger.encode(websocket.request.full_path)}</cyan>')

    def websocket_message_error(self, e: Exception, websocket: 'Websocket'):
        error = self._error()
        self.app.logger.danger(f'An error occurred causing the {websocket.request.ip} received a message to {websocket.request.method} {websocket.request.full_path}:\n    {error}', f'An error occurred causing the <cyan>{websocket.request.ip}</cyan> receive a message to <cyan>{websocket.request.method} {self.app.logger.encode(websocket.request.full_path)}</cyan>:\n    {self.app.logger.encode(error)}')

    def scheduler_error(self, e: Exception, task: 'Task'):
        error = self._error()
        self.app.logger.danger(f'An error occurred in the scheduled task {task.key} running:\n    {error}', f'An error occurred in the scheduled task running <green>{self.app.logger.encode(task.key)}</green>:\n    {self.app.logger.encode(error)}')

    @property
    def app(self) -> 'CheeseAPI':
        return self._app

    @property
    def progress_bar(self) -> ProgressBar:
        return self._progress_bar
