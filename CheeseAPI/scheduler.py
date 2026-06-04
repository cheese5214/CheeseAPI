import datetime, uuid, threading, multiprocessing, asyncio, time, json
from typing import Callable, Literal, TYPE_CHECKING

import redis, redis.exceptions

from CheeseAPI import static

if TYPE_CHECKING:
    from CheeseAPI import CheeseAPI

class Task:
    @classmethod
    def from_dict(cls, data: dict[str, any], _scheduler_proxy) -> 'Task':
        instance = cls.__new__(cls)
        for key, value in data.items():
            if key == '_queue':
                if value:
                    value = multiprocessing.Queue()
                    value.put(None)
                else:
                    value = multiprocessing.Queue()
            elif key == 'first_run_timer':
                value = datetime.datetime.fromtimestamp(value) if value else None
            elif key == '_last_run_timer':
                value = datetime.datetime.fromtimestamp(value) if value else None
            setattr(instance, key, value)
        setattr(instance, '_scheduler_proxy', _scheduler_proxy)
        return instance

    __slots__ = ('fn', 'interval_time', 'first_run_timer', 'expected_run_num', '_key', 'run_type', 'args', 'kwargs', 'auto_remove', '_last_run_timer', '_last_run_time', '_run_num', '_handler', '_queue', '_scheduler_proxy', 'timeout')

    def __init__(self, fn: Callable, interval_time: float, *, first_run_timer: datetime.datetime | float | None = None, expected_run_num: int | None = None, key: str | None = None, run_type: Literal['THREAD', 'PROCESS', 'ASYNC'] = 'THREAD', args: tuple = (), kwargs: dict = {}, auto_remove: bool = False, timeout: float | None = None, _scheduler_proxy: 'SchedulerProxy'):
        '''
        在 `is_active` 为 `False` 时，修改任务属性是可行的，在下一次运行时会生效

        - Args
            - interval_time: 任务执行间隔
            - first_run_timer: 首次执行时间，若小于当前时间则立刻执行，若大于当前时间则在指定时间执行
            - expected_run_num: 预期执行次数，若未设置则无限次执行
            - key: 默认为随机 uuid
            - run_type: 任务执行方式，可选线程、协程、进程
            - args: 默认首位是 `app: CheeseAPI`
            - auto_remove: 任务完成期望次数后是否自动移除
            - timeout: 当 app.sync_server_url 存在时，任务超过多少秒没有执行完毕则认为执行失败，在 sync_server 中会视为任务删除，None 默认为 interval_time * 2 的值；恢复执行后会在 sync_server 上自动恢复
        '''

        self.fn: Callable = fn
        self.interval_time: float = interval_time
        ''' 任务执行间隔 '''
        self.first_run_timer: datetime.datetime | float | None = first_run_timer
        ''' 首次执行时间，若小于当前时间则立刻执行，若大于当前时间则在指定时间执行 '''
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
        self.timeout: float = timeout if timeout is not None else interval_time * 2
        self._scheduler_proxy: 'SchedulerProxy' = _scheduler_proxy

        self._last_run_timer: datetime.datetime | None = None
        self._last_run_time: float | None = None
        self._run_num: int = 0
        self._handler: threading.Thread | multiprocessing.Process | asyncio.Task | None = None
        self._queue = multiprocessing.Queue()

    def __getstate__(self) -> tuple[None, dict[str, any]]:
        state = {
            key: getattr(self, key) for key in self.__slots__
        }
        state['_handler'] = None
        return None, state

    def _to_dict(self) -> dict[str, any]:
        data = {
            key: getattr(self, key) for key in self.__slots__
        }
        data['_queue'] = bool(data['_queue'].qsize())
        data['first_run_timer'] = self.first_run_timer.timestamp() if self.first_run_timer else None
        data['_last_run_timer'] = self._last_run_timer.timestamp() if self._last_run_timer else None
        data['_handler'] = None
        data['fn'] = None
        data['args'] = tuple()
        data['kwargs'] = {}
        data['_scheduler_proxy'] = None
        return data

    def start(self):
        self._scheduler_proxy.start(self.key)

    async def async_start(self):
        if not self._handler:
            self._handler = asyncio.create_task(self._scheduler_proxy.async_task_processing(self.key, self._queue, self.fn, *self.args, **self.kwargs))

    @property
    def key(self) -> str:
        return self._key

    @property
    def run_num_completed(self) -> bool:
        if self.expected_run_num is None:
            return False
        return self._run_num >= self.expected_run_num

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

    @property
    def is_running(self) -> bool:
        '''
        任务是否在运行中
        '''

        return not self._queue.qsize()

class Scheduler:
    __slots__ = ('_proxy',)

    def __init__(self, app: 'CheeseAPI'):
        self._proxy: SchedulerProxy = app.SchedulerProxy_Class(app)

    def add(self, interval_time: float, fn: Callable | None = None, *, first_run_timer: datetime.datetime | None = None, expected_run_num: int | None = None, key: str | None = None, run_type: Literal['THREAD', 'PROCESS'] = 'THREAD', args: tuple = (), kwargs: dict = {}, auto_remove: bool = False, timeout: float | None = None) -> Callable | Task:
        '''
        使用表达式会自动执行任务，使用函数调用会返回 Task 对象，需手动调用 start 方法启动任务

        - Args
            - interval_time: 任务执行间隔，若未设置，则立刻执行，执行完毕后自动移除
            - first_run_timer: 首次执行时间，若值小于当前时间则立刻执行
            - expected_run_num: 预期执行次数，若未设置则无限次执行
            - key: 默认为 uuid
            - run_type: 任务执行方式，可选线程、进程
            - args: 默认首位是 `app: CheeseAPI`
            - auto_remove: 任务完成期望次数后是否自动移除
            - timeout: 当 app.sync_server_url 存在时，任务超过多少秒没有执行完毕则认为执行失败，在 sync_server 中会视为任务删除，None 默认为 interval_time * 2 的值；恢复执行后会在 sync_server 上自动恢复
        '''

        return self._proxy.add(interval_time, fn, first_run_timer = first_run_timer, expected_run_num = expected_run_num, key = key, run_type = run_type, args = args, kwargs = kwargs, auto_remove = auto_remove, timeout = timeout)

    async def async_add(self, interval_time: float, fn: Callable | None = None, *, first_run_timer: datetime.datetime | None = None, expected_run_num: int | None = None, key: str | None = None, args: tuple = (), kwargs: dict = {}, auto_remove: bool = False, timeout: float | None = None) -> Callable | Task:
        '''
        使用协程方式添加任务

        使用表达式会自动执行任务，使用函数调用会返回 Task 对象，需手动调用 start 方法启动任务

        - Args
            - interval_time: 任务执行间隔，若未设置，则立刻执行，执行完毕后自动移除
            - first_run_timer: 首次执行时间，若值小于当前时间则立刻执行
            - expected_run_num: 预期执行次数，若未设置则无限次执行
            - key: 默认为 uuid
            - args: 默认首位是 `app: CheeseAPI`
            - auto_remove: 任务完成期望次数后是否自动移除
            - timeout: 当 app.sync_server_url 存在时，任务超过多少秒没有执行完毕则认为执行失败，在 sync_server 中会视为任务删除，None 默认为 interval_time * 2 的值；恢复执行后会在 sync_server 上自动恢复
        '''

        return await self._proxy.async_add(interval_time, fn, first_run_timer = first_run_timer, expected_run_num = expected_run_num, key = key, args = args, kwargs = kwargs, auto_remove = auto_remove, timeout = timeout)

    def start(self, key: str):
        '''
        启动任务
        '''

        self._proxy.start(key)

    async def async_start(self, key: str):
        '''
        启动任务
        '''

        await self._proxy.async_start(key)

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

    async def async_stop(self, key: str):
        '''
        停止任务
        '''

        await self._proxy.async_stop(key)

    async def async_remove(self, key: str):
        '''
        移除任务
        '''

        await self._proxy.async_remove(key)

    def get_tasks(self) -> dict[str, Task]:
        '''
        获取所有任务
        '''

        return self._proxy.get_tasks()

    async def async_get_tasks(self) -> dict[str, Task]:
        '''
        获取所有任务
        '''

        return await self._proxy.async_get_tasks()

    def get_task(self, key: str) -> Task | None:
        '''
        获取任务
        '''

        return self._proxy.get_task(key)

    async def async_get_task(self, key: str) -> Task | None:
        '''
        获取任务
        '''

        return await self._proxy.async_get_task(key)

    @property
    def tasks(self) -> dict[str, Task]:
        return self._proxy.get_tasks()

class SchedulerProxy:
    __slots__ = ('app', '_tasks')

    def __init__(self, app: 'CheeseAPI'):
        self.app: 'CheeseAPI' = app

        self._tasks: dict[str, Task] = {}

    def __getstate__(self):
        return None, {
            'app': self.app
        }

    def __setstate__(self, state):
        self.app = state[1]['app']

    def init(self, app = None):
        if not app:
            app = self.app

        if app.sync_server_url:
            static.scheduler_sync_servers = (redis.ConnectionPool.from_url(app.sync_server_url), redis.asyncio.ConnectionPool.from_url(app.sync_server_url))
            threading.Thread(target = self._start_pubsub, args = (app,), daemon = True).start()
            coro = self._async_start_pubsub(app)
            try:
                asyncio.create_task(coro)
            except RuntimeError:
                coro.close()

    def _start_pubsub(self, app: 'CheeseAPI'):
        pubsub = redis.Redis(connection_pool = static.scheduler_sync_servers[0]).pubsub()
        pubsub.subscribe('CheeseAPI_scheduler')
        try:
            while True:
                try:
                    for message in pubsub.listen():
                        if message['type'] == 'message':
                            data = json.loads(message['data'])

                            task = self._tasks.get(data[1])
                            if not task or task.run_type == 'ASYNC':
                                continue

                            if data[0] == 'start':
                                self.start(data[1])
                            elif data[0] == 'stop':
                                self.stop(data[1])
                            elif data[0] == 'remove':
                                self.remove(data[1])
                except redis.exceptions.RedisError:
                    pubsub.close()
                    time.sleep(app.sync_server_timeout)
                    self._start_pubsub(app)
        except (KeyboardInterrupt, SystemExit):
            ...

    async def _async_start_pubsub(self, app: 'CheeseAPI'):
        pubsub = redis.asyncio.Redis(connection_pool = static.scheduler_sync_servers[1]).pubsub()
        await pubsub.subscribe('CheeseAPI_scheduler')
        try:
            while True:
                try:
                    async for message in pubsub.listen():
                        if message['type'] == 'message':
                            data = json.loads(message['data'])

                            task = self._tasks.get(data[1])
                            if not task or task.run_type == 'ASYNC':
                                continue

                            if data[0] == 'start':
                                await self.async_start(data[1])
                            elif data[0] == 'stop':
                                await self.async_stop(data[1])
                            elif data[0] == 'remove':
                                await self.async_remove(data[1])
                except redis.exceptions.RedisError:
                    await pubsub.close()
                    await asyncio.sleep(app.sync_server_timeout)
                    await self._async_start_pubsub(app)
        except (KeyboardInterrupt, SystemExit):
            ...

    def add(self, interval_time: float, fn: Callable | None = None, *, first_run_timer: datetime.datetime | None = None, expected_run_num: int | None = None, key: str | None = None, run_type: Literal['THREAD', 'PROCESS'] = 'THREAD', args: tuple = (), kwargs: dict = {}, auto_remove: bool = False, timeout: float | None = None) -> Callable | Task:
        if fn:
            task = Task(fn, interval_time, first_run_timer = first_run_timer, expected_run_num = expected_run_num, key = key, run_type = run_type, args = args, kwargs = kwargs, auto_remove = auto_remove, timeout = timeout, _scheduler_proxy = self)
            task._queue.put(None)

            if task.key in self.get_tasks():
                raise KeyError(f'Task with key "{task.key}" already exists')

            self._tasks[task.key] = task
            if static.scheduler_sync_servers:
                redis.Redis(connection_pool = static.scheduler_sync_servers[0]).hset('CheeseAPI_scheduler_tasks', task.key, json.dumps(task._to_dict()))

            return task
        else:
            def wrapper(_fn: Callable):
                task = self.add(interval_time, _fn, first_run_timer = first_run_timer, expected_run_num = expected_run_num, key = key, run_type = run_type, args = args, kwargs = kwargs, auto_remove = auto_remove, timeout = timeout)
                task.start()
                return _fn
            return wrapper

    async def async_add(self, interval_time: float | None = None, fn: Callable | None = None, *, first_run_timer: datetime.datetime | None = None, expected_run_num: int | None = None, key: str | None = None, args: tuple = (), kwargs: dict = {}, auto_remove: bool = False, timeout: float | None = None) -> Callable | Task:
        if fn is not None:
            task = Task(fn, interval_time = interval_time, first_run_timer = first_run_timer, expected_run_num = expected_run_num, key = key, run_type = 'ASYNC', args = args, kwargs = kwargs, auto_remove = auto_remove, timeout = timeout, _scheduler_proxy = self)
            task._queue.put(None)

            if task.key in await self.async_get_tasks():
                raise KeyError(f'Task with key "{task.key}" already exists')

            self._tasks[task.key] = task
            if static.scheduler_sync_servers:
                await redis.asyncio.Redis(connection_pool = static.scheduler_sync_servers[1]).hset('CheeseAPI_scheduler_tasks', task.key, json.dumps(task._to_dict()))

            return task
        else:
            async def wrapper(_fn: Callable):
                task = await self.async_add(interval_time, _fn, first_run_timer = first_run_timer, expected_run_num = expected_run_num, key = key, args = args, kwargs = kwargs, auto_remove = auto_remove, timeout = timeout)
                await task.async_start()
                return _fn
            return wrapper

    def task_processing(self, key: str, queue: multiprocessing.Queue, fn, *args, **kwargs):
        try:
            task = self.get_task(key)
            if not task:
                return

            queue.get()
            task._queue.get()
            first_run = True

            if task.first_run_timer:
                time.sleep(max(0, task.first_run_timer.timestamp() - time.time()))

            while not queue.qsize():
                if static.scheduler_sync_servers:
                    task = self.get_task(key)
                    if (not task or (not first_run and task._queue.qsize())):
                        break

                now = time.time()

                try:
                    fn(self.app, *args, **kwargs)
                except Exception as e:
                    self.app.printer.scheduler_error(e, task)

                if static.scheduler_sync_servers:
                    task = self.get_task(key)

                if task:
                    if first_run:
                        task._queue.get()
                    task._last_run_time = time.time() - now
                    task._last_run_timer = datetime.datetime.fromtimestamp(now)
                    task._run_num += 1

                    if static.scheduler_sync_servers:
                        sync_server = redis.Redis(connection_pool = static.scheduler_sync_servers[0])
                        sync_server.hset('CheeseAPI_scheduler_tasks', key, json.dumps(task._to_dict()))
                        sync_server.hpexpire('CheeseAPI_scheduler_tasks', int(task.timeout * 1000), key)

                if (not task or task._queue.qsize()) or task.run_num_completed:
                    break

                first_run = False
                time.sleep(max(0, task.interval_time - time.time() + now))
        except (KeyboardInterrupt, SystemExit):
            ...

        queue.put(None)

        if static.scheduler_sync_servers and task:
            redis.Redis(connection_pool = static.scheduler_sync_servers[0]).hpersist('CheeseAPI_scheduler_tasks', key)

    async def async_task_processing(self, key: str, queue: multiprocessing.Queue, fn, *args, **kwargs):
        task = self.get_task(key)
        if not task:
            return

        queue.get()
        task._queue.get()
        first_run = True

        if task.first_run_timer:
            await asyncio.sleep(max(0, task.first_run_timer.timestamp() - time.time()))

        while not queue.qsize():
            if static.scheduler_sync_servers:
                task = await self.async_get_task(key)
                if (not task or (not first_run and task._queue.qsize())):
                    break

            now = time.time()

            try:
                await fn(self.app, *args, **kwargs)
            except Exception as e:
                self.app.printer.scheduler_error(e, task)

            if static.scheduler_sync_servers:
                task = await self.async_get_task(key)

            if task:
                if first_run:
                    task._queue.get()
                task._last_run_time = time.time() - now
                task._last_run_timer = datetime.datetime.fromtimestamp(now)
                task._run_num += 1

                if static.scheduler_sync_servers:
                    sync_server = redis.asyncio.Redis(connection_pool = static.scheduler_sync_servers[1])
                    await sync_server.hset('CheeseAPI_scheduler_tasks', key, json.dumps(task._to_dict()))
                    await sync_server.hpexpire('CheeseAPI_scheduler_tasks', int(task.timeout * 1000), key)

            if (not task or task._queue.qsize()) or task.run_num_completed:
                break

            first_run = False
            await asyncio.sleep(max(0, task.interval_time - time.time() + now))

        if not task or task.auto_remove:
            self._tasks.pop(key, None)
            if static.scheduler_sync_servers is not None:
                await redis.asyncio.Redis(connection_pool = static.scheduler_sync_servers[1]).hdel('CheeseAPI_scheduler_tasks', key)
        else:
            if static.scheduler_sync_servers is not None:
                await redis.asyncio.Redis(connection_pool = static.scheduler_sync_servers[1]).hpersist('CheeseAPI_scheduler_tasks', key)

    def join(self, task: Task):
        if task.run_type == 'THREAD' and isinstance(task._handler, threading.Thread):
            task._handler.join()
        elif task.run_type == 'PROCESS' and isinstance(task._handler, multiprocessing.Process):
            task._handler.join()
        self._tasks.pop(task.key, None)
        redis.Redis(connection_pool = static.scheduler_sync_servers[0]).hdel('CheeseAPI_scheduler_tasks', task.key)

    def start(self, key: str):
        task = self.get_task(key)
        if not task:
            raise KeyError(f'Task with key "{key}" does not exist')
        if task.is_running:
            raise KeyError(f'Task with key "{key}" is already running')

        task = self._tasks.get(key)
        if not task and static.scheduler_sync_servers:
            redis.Redis(connection_pool = static.scheduler_sync_servers[0]).publish('CheeseAPI_scheduler', json.dumps(['start', key]))
            return

        if task.run_type == 'THREAD':
            task._handler = threading.Thread(target = self.task_processing, args = (key, task._queue, task.fn, *task.args), kwargs = task.kwargs, daemon = True)
        elif task.run_type == 'PROCESS':
            task._handler = multiprocessing.get_context('spawn').Process(target = self.task_processing, args = (key, task._queue, task.fn, *task.args), kwargs = task.kwargs, daemon = True)
        task._handler.start()

        if task.auto_remove:
            threading.Thread(target = self.join, args = (task,), daemon = True).start()

    async def async_start(self, key: str):
        task = await self.async_get_task(key)
        if not task:
            raise KeyError(f'Task with key "{key}" does not exist')
        if task.is_running:
            raise KeyError(f'Task with key "{key}" is already running')

        task = self._tasks.get(key)
        if not task and static.scheduler_sync_servers:
            await redis.asyncio.Redis(connection_pool = static.scheduler_sync_servers[1]).publish('CheeseAPI_scheduler', json.dumps(['start', key]))
        else:
            task._handler = asyncio.create_task(self.async_task_processing(task, *task.args, **task.kwargs))

    def stop(self, key: str):
        task = self.get_task(key)
        if not task:
            raise KeyError(f'Task with key "{key}" does not exist')
        if not task.is_running:
            raise KeyError(f'Task with key "{key}" is not running')

        _task = self._tasks.get(key)
        if not _task:
            if static.scheduler_sync_servers:
                redis.Redis(connection_pool = static.scheduler_sync_servers[0]).publish('CheeseAPI_scheduler', json.dumps(['stop', key]))
        else:
            _task._queue.put(None)
        if static.scheduler_sync_servers:
            redis.Redis(connection_pool = static.scheduler_sync_servers[0]).hset('CheeseAPI_scheduler_tasks', key, json.dumps(task._to_dict()))

    def remove(self, key: str):
        task = self.get_task(key)
        if not task or not task.is_running:
            return

        _task = self._tasks.get(key)
        if not _task:
            if static.scheduler_sync_servers:
                redis.Redis(connection_pool = static.scheduler_sync_servers[0]).publish('CheeseAPI_scheduler', json.dumps(['remove', key]))
        else:
            self._tasks.pop(key, None)
        if static.scheduler_sync_servers:
            redis.Redis(connection_pool = static.scheduler_sync_servers[0]).hdel('CheeseAPI_scheduler_tasks', key)

    async def async_stop(self, key: str):
        task = await self.async_get_task(key)
        if not task:
            raise KeyError(f'Task with key "{key}" does not exist')
        if not task.is_running:
            raise KeyError(f'Task with key "{key}" is not running')

        _task = self._tasks.get(key)
        if not _task:
            if static.scheduler_sync_servers:
                await redis.asyncio.Redis(connection_pool = static.scheduler_sync_servers[1]).publish('CheeseAPI_scheduler', json.dumps(['stop', key]))
        else:
            _task._queue.put(None)
        if static.scheduler_sync_servers:
            await redis.asyncio.Redis(connection_pool = static.scheduler_sync_servers[1]).hset('CheeseAPI_scheduler_tasks', key, json.dumps(task._to_dict()))

    async def async_remove(self, key: str):
        task = await self.async_get_task(key)
        if not task or not task.is_running:
            return

        _task = self._tasks.get(key)
        if not _task:
            if static.scheduler_sync_servers:
                await redis.asyncio.Redis(connection_pool = static.scheduler_sync_servers[1]).publish('CheeseAPI_scheduler', json.dumps(['remove', key]))
        else:
            self._tasks.pop(key, None)
        if static.scheduler_sync_servers:
            await redis.asyncio.Redis(connection_pool = static.scheduler_sync_servers[1]).hdel('CheeseAPI_scheduler_tasks', key)

    def get_task(self, key: str) -> Task | None:
        if static.scheduler_sync_servers is not None:
            data = redis.Redis(connection_pool = static.scheduler_sync_servers[0]).hget('CheeseAPI_scheduler_tasks', key)
            if data:
                return Task.from_dict(json.loads(data), self)
            return

        return self._tasks.get(key)

    async def async_get_task(self, key: str) -> Task | None:
        if static.scheduler_sync_servers is not None:
            data = await redis.asyncio.Redis(connection_pool = static.scheduler_sync_servers[1]).hget('CheeseAPI_scheduler_tasks', key)
            if data:
                return Task.from_dict(json.loads(data), self)
            return

        return self._tasks.get(key)

    def get_tasks(self) -> dict[str, Task]:
        if static.scheduler_sync_servers is not None:
            return {
                key: Task.from_dict(json.loads(data), self) for key, data in redis.Redis(connection_pool = static.scheduler_sync_servers[0]).hgetall('CheeseAPI_scheduler_tasks').items()
            }

        return self._tasks

    async def async_get_tasks(self) -> dict[str, Task]:
        if static.scheduler_sync_servers is not None:
            return {
                key: Task.from_dict(json.loads(data), self) for key, data in (await redis.asyncio.Redis(connection_pool = static.scheduler_sync_servers[1]).hgetall('CheeseAPI_scheduler_tasks')).items()
            }

        return self._tasks
