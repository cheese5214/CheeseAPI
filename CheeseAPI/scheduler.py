import datetime, uuid, threading, multiprocessing, asyncio, time
from typing import Callable, Literal, TYPE_CHECKING

if TYPE_CHECKING:
    from CheeseAPI import CheeseAPI

class Task:
    __slots__ = ('fn', 'interval_time', 'first_run_timer', 'expected_run_num', '_key', 'run_type', 'args', 'kwargs', 'auto_remove', '_last_run_timer', '_last_run_time', '_run_num', '_handler', '_event')

    def __init__(self, fn: Callable, *, interval_time: float | None = None, first_run_timer: datetime.datetime | None = None, expected_run_num: int | None = None, key: str | None = None, run_type: Literal['THREAD', 'PROCESS', 'ASYNC'] = 'THREAD', args: tuple = (), kwargs: dict = {}, auto_remove: bool = False):
        '''
        在 `is_active` 为 `False` 时，修改任务属性是可行的，在下一次运行时会生效

        - Args
            - interval_time: 任务执行间隔，若未设置，则立刻执行，执行完毕后自动移除
            - first_run_timer: 首次执行时间，若值小于当前时间则立刻执行
            - expected_run_num: 预期执行次数，若未设置则无限次执行
            - key: 默认为 uuid
            - run_type: 任务执行方式，可选线程、协程、进程
            - args: 默认首位是 `app: CheeseAPI`
            - auto_remove: 任务完成期望次数后是否自动移除
        '''

        self.fn: Callable = fn
        self.interval_time: float | None = interval_time
        ''' 任务执行间隔，若未设置，则立刻执行，执行完毕后自动移除 '''
        self.first_run_timer: datetime.datetime | None = first_run_timer
        ''' 首次执行时间，若值小于当前时间则立刻执行 '''
        self.expected_run_num: int | None = expected_run_num
        ''' 预期执行次数，若未设置则无限次执行 '''
        self._key: str = key or str(uuid.uuid4())
        self.run_type: Literal['THREAD', 'PROCESS', 'ASYNC'] = run_type
        ''' 任务执行方式，可选线程、协程、进程 '''
        self.args: tuple = args
        ''' 默认首位是 `app: CheeseAPI` '''
        self.kwargs: dict = kwargs
        self.auto_remove: bool = auto_remove
        ''' 任务完成期望次数后是否自动移除 '''

        self._last_run_timer: datetime.datetime | None = None
        self._last_run_time: float | None = None
        self._run_num: int = 0
        self._handler: threading.Thread | multiprocessing.Process | asyncio.Task | None = None
        self._event = multiprocessing.get_context('spawn').Event()

    def __getstate__(self) -> tuple[None, dict[str, any]]:
        self._handler = None
        return None, {
            key: getattr(self, key) for key in self.__slots__
        }

    @property
    def key(self) -> str:
        return self._key

    @property
    def is_active(self) -> bool:
        if self.expected_run_num is None:
            return True
        return self._run_num < self.expected_run_num

    @property
    def last_run_timer(self) -> datetime.datetime | None:
        '''
        上一次的运行时刻
        '''

        return self._last_run_timer

    @property
    def last_run_time(self) -> float | None:
        '''
        上一次的运行耗时
        '''

        return self._last_run_time

    @property
    def run_num(self) -> int:
        '''
        运行次数
        '''

        return self._run_num

class Scheduler:
    __slots__ = ('_proxy',)

    def __init__(self, app: 'CheeseAPI'):
        self._proxy: SchedulerProxy = app.SchedulerProxy_Class(app)

    def add(self, fn: Callable | None = None, *, interval_time: float | None = None, first_run_timer: datetime.datetime | None = None, expected_run_num: int | None = None, key: str | None = None, run_type: Literal['THREAD', 'PROCESS'] = 'THREAD', args: tuple = (), kwargs: dict = {}, auto_remove: bool = False):
        '''
        - Args
            - interval_time: 任务执行间隔，若未设置，则立刻执行，执行完毕后自动移除
            - first_run_timer: 首次执行时间，若值小于当前时间则立刻执行
            - expected_run_num: 预期执行次数，若未设置则无限次执行
            - key: 默认为 uuid
            - run_type: 任务执行方式，可选线程、进程
            - args: 默认首位是 `app: CheeseAPI`
            - auto_remove: 任务完成期望次数后是否自动移除
        '''

        return self._proxy.add(fn, interval_time = interval_time, first_run_timer = first_run_timer, expected_run_num = expected_run_num, key = key, run_type = run_type, args = args, kwargs = kwargs, auto_remove = auto_remove)

    async def async_add(self, fn: Callable | None = None, *, interval_time: float | None = None, first_run_timer: datetime.datetime | None = None, expected_run_num: int | None = None, key: str | None = None, args: tuple = (), kwargs: dict = {}, auto_remove: bool = False):
        '''
        使用协程方式添加任务

        - Args
            - interval_time: 任务执行间隔，若未设置，则立刻执行，执行完毕后自动移除
            - first_run_timer: 首次执行时间，若值小于当前时间则立刻执行
            - expected_run_num: 预期执行次数，若未设置则无限次执行
            - key: 默认为 uuid
            - args: 默认首位是 `app: CheeseAPI`
            - auto_remove: 任务完成期望次数后是否自动移除
        '''

        return await self._proxy.async_add(fn, interval_time = interval_time, first_run_timer = first_run_timer, expected_run_num = expected_run_num, key = key, args = args, kwargs = kwargs, auto_remove = auto_remove)

    def restart(self, key: str):
        '''
        重启任务
        '''

        self._proxy.restart(key)

    async def async_restart(self, key: str):
        '''
        重启任务
        '''

        await self._proxy.async_restart(key)

    def stop(self, key: str):
        '''
        停止任务
        '''

        self._proxy.stop(key)

    def remove(self, key: str):
        '''
        移除任务
        '''

        self._proxy.remove(key)

    @property
    def tasks(self) -> dict[str, Task]:
        return self._proxy._tasks

class SchedulerProxy:
    __slots__ = ('app', '_tasks')

    def __init__(self, app: 'CheeseAPI'):
        self.app: 'CheeseAPI' = app

        self._tasks: dict[str, Task] = {}

    def add(self, fn: Callable | None = None, *, interval_time: float | None = None, first_run_timer: datetime.datetime | None = None, expected_run_num: int | None = None, key: str | None = None, run_type: Literal['THREAD', 'PROCESS'] = 'THREAD', args: tuple = (), kwargs: dict = {}, auto_remove: bool = False):
        if fn is not None:
            task = Task(fn, interval_time = interval_time, first_run_timer = first_run_timer, expected_run_num = expected_run_num, key = key, run_type = run_type, args = args, kwargs = kwargs, auto_remove = auto_remove)

            if task.key in self.app.scheduler.tasks:
                raise KeyError(f"Task with key '{task.key}' already exists")
            self._tasks[task.key] = task

            if task.run_type == 'THREAD':
                task._handler = threading.Thread(target = self.task_processing, args = (task, *args), kwargs = kwargs, daemon = True)
            elif task.run_type == 'PROCESS':
                task._handler = multiprocessing.get_context('spawn').Process(target = self.task_processing, args = (task, *args), kwargs = kwargs, daemon = True)
            task._handler.start()

            if task.auto_remove:
                threading.Thread(target = self.join, args = (task,), daemon = True).start()
        else:
            def wrapper(_fn: Callable):
                self.add(_fn, interval_time = interval_time, first_run_timer = first_run_timer, expected_run_num = expected_run_num, key = key, run_type = run_type, args = args, kwargs = kwargs, auto_remove = auto_remove)
                return _fn
            return wrapper

    async def async_add(self, fn: Callable | None = None, *, interval_time: float | None = None, first_run_timer: datetime.datetime | None = None, expected_run_num: int | None = None, key: str | None = None, args: tuple = (), kwargs: dict = {}, auto_remove: bool = False):
        if fn is not None:
            task = Task(fn, interval_time = interval_time, first_run_timer = first_run_timer, expected_run_num = expected_run_num, key = key, run_type = 'ASYNC', args = args, kwargs = kwargs, auto_remove = auto_remove)

            if task.key in self.app.scheduler.tasks:
                raise KeyError(f"Task with key '{task.key}' already exists")
            self._tasks[task.key] = task

            task._handler = asyncio.create_task(self.async_task_processing(task, *args, **kwargs))
        else:
            def wrapper(_fn: Callable):
                self.add(_fn, interval_time = interval_time, first_run_timer = first_run_timer, expected_run_num = expected_run_num, key = key, args = args, kwargs = kwargs, auto_remove = auto_remove)
                return _fn
            return wrapper

    def task_processing(self, task: Task, *args, **kwargs):
        if task.run_type == 'PROCESS' and multiprocessing.get_start_method() != 'spawn':
            self.app.logger.stop()
            self.app.logger.start()

        try:
            sleep_time = max(0, task.first_run_timer.timestamp() - time.time()) if task.first_run_timer else 0
            if sleep_time:
                time.sleep(sleep_time)

            while task._event.is_set() is False:
                now = time.time()

                try:
                    task.fn(self.app, *args, **kwargs)
                except Exception as e:
                    self.app.printer.scheduler_error(e, task)

                task._last_run_time = time.time() - now
                task._last_run_timer = datetime.datetime.fromtimestamp(now)
                task._run_num += 1

                if task.is_active is False or task.interval_time is None or task._event.is_set():
                    break

                time.sleep(max(0, task.interval_time - time.time() + now))
        except (KeyboardInterrupt, SystemExit):
            ...

    async def async_task_processing(self, task: Task, *args, **kwargs):
        sleep_time = max(0, task.first_run_timer.timestamp() - time.time()) if task.first_run_timer else 0
        if sleep_time:
            await asyncio.sleep(sleep_time)

        while task._event.is_set() is False:
            now = time.time()

            try:
                await task.fn(self.app, *args, **kwargs)
            except Exception as e:
                self.app.printer.scheduler_error(e, task)

            task._last_run_time = time.time() - now
            task._last_run_timer = datetime.datetime.fromtimestamp(now)
            task._run_num += 1

            if task.is_active is False or task.interval_time is None or task._event.is_set():
                break

            await asyncio.sleep(max(0, task.interval_time - time.time() + now))

        if task.auto_remove:
            del self._tasks[task.key]

    def join(self, task: Task):
        if task.run_type == 'THREAD' and isinstance(task._handler, threading.Thread):
            task._handler.join()
        elif task.run_type == 'PROCESS' and isinstance(task._handler, multiprocessing.Process):
            task._handler.join()

        del self._tasks[task.key]

    def restart(self, key: str):
        task = self._tasks.get(key)
        if task is None:
            raise KeyError(f"Task with key '{key}' does not exist")

        task._event.clear()
        task._run_num = 0
        if task.run_type == 'THREAD':
            task._handler = threading.Thread(target = self.task_processing, args = (task, *task.args), kwargs = task.kwargs, daemon = True)
        elif task.run_type == 'PROCESS':
            task._handler = multiprocessing.get_context('spawn').Process(target = self.task_processing, args = (task, *task.args), kwargs = task.kwargs, daemon = True)
        task._handler.start()

    async def async_restart(self, key: str):
        task = self._tasks.get(key)
        if task is None:
            raise KeyError(f"Task with key '{key}' does not exist")

        task._event.clear()
        task._run_num = 0
        task._handler = asyncio.create_task(self.async_task_processing(task, *task.args, **task.kwargs))

    def stop(self, key: str):
        if key not in self._tasks:
            return

        self._tasks[key]._event.set()

    def remove(self, key: str):
        if key not in self._tasks:
            return
        self._tasks[key]._event.set()
        del self._tasks[key]
