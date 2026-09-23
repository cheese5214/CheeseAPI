import inspect, os
import datetime, uuid, threading, multiprocessing, asyncio, time, json
from queue import Empty
from typing import Callable, Literal, TYPE_CHECKING

import redis, redis.exceptions

from CheeseAPI import static

if TYPE_CHECKING:
    from CheeseAPI import CheeseAPI

def _timeout_ms(task: 'Task') -> int:
    ''' 任务记录的 TTL（毫秒）：`timeout` 秒转换为毫秒，至少 1 毫秒（`0` 会让 `hpexpire` 直接删除记录） '''

    return max(1, int(task.timeout * 1000))

class Task:
    @classmethod
    def from_dict(cls, data: dict[str, any], _scheduler_proxy) -> 'Task':
        instance = cls.__new__(cls)

        for key, value in data.items():
            if key == '_queue':
                value = None # 队列按需创建（见 `_ensure_queue`），反序列化时不占用文件描述符
            elif key == '_stop_event':
                value = threading.Event()
            elif key == 'first_run_timer':
                value = datetime.datetime.fromtimestamp(value) if value else None
            elif key == '_last_run_timer':
                value = datetime.datetime.fromtimestamp(value) if value else None
            setattr(instance, key, value)

        if '_running_remote' not in data:
            instance._running_remote = False # 无法判断运行状态的旧数据按未运行处理，避免残留记录阻塞重启
        if '_instance' not in data:
            instance._instance = None # 没有实例 id 的旧数据视为无属主：按死进程残留处理，允许接管

        setattr(instance, '_scheduler_proxy', _scheduler_proxy)
        return instance

    __slots__ = ('fn', 'interval_time', 'first_run_timer', 'expected_run_num', '_key', 'run_type', 'args', 'kwargs', 'auto_remove', '_last_run_timer', '_last_run_time', '_run_num', '_handler', '_queue', '_stop_event', '_running_remote', '_instance', '_scheduler_proxy', 'timeout')

    def __init__(self, fn: Callable, interval_time: float, *, first_run_timer: datetime.datetime | float | None = None, expected_run_num: int | None = None, key: str | None = None, run_type: Literal['THREAD', 'PROCESS', 'ASYNC'] = 'THREAD', args: tuple = (), kwargs: dict = {}, auto_remove: bool = False, timeout: float | None = None, _scheduler_proxy: 'SchedulerProxy'):
        '''
        在 `is_active` 为 `False` 时，修改任务属性是可行的，在下一次运行时会生效

        - Args
            - interval_time: 任务执行间隔
            - first_run_timer: 首次执行时间，若小于当前时间则立刻执行，若大于当前时间则在指定时间执行
            - expected_run_num: 预期执行次数，若未设置则无限次执行
            - key: 默认为随机 uuid
            - run_type: 任务执行方式，可选线程、协程、进程
            - kwargs: 自动包含 `app: CheeseAPI`，如果不提供 app 参数位置，则不会传入
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
        self.kwargs: dict = kwargs
        ''' 自动包含 `app: CheeseAPI`，如果不提供 app 参数位置，则不会传入 '''
        self.auto_remove: bool = auto_remove
        ''' 任务完成期望次数后是否自动移除 '''
        self.timeout: float = timeout if timeout is not None else interval_time * 2
        self._scheduler_proxy: 'SchedulerProxy' = _scheduler_proxy

        self._last_run_timer: datetime.datetime | None = None
        self._last_run_time: float | None = None
        self._run_num: int = 0
        self._handler: threading.Thread | multiprocessing.Process | asyncio.Task | None = None

        self._queue = None
        ''' 进程任务的停止信号队列（父进程放入、子进程取出），按需创建（见 `_ensure_queue`） '''
        self._stop_event = threading.Event()
        ''' 线程 / 协程任务的停止信号（同进程内使用） '''
        self._running_remote: bool = False
        ''' 任务的运行状态（写入共享存储，其它进程据此判断同名任务是否已被占用） '''
        self._instance: str | None = None
        ''' 占用该任务的进程实例 id（由 `SchedulerProxy` 在注册时写入，用于判断属主进程是否已死） '''

    '''
    停止信号的收发

    不使用 `multiprocessing.Queue.qsize()`（macOS 未实现，调用即 `NotImplementedError`）：
    线程 / 协程任务用 `threading.Event`，进程任务用队列的 `empty()` / `get_nowait()` 判断与取出信号。
    '''

    def _ensure_queue(self):
        '''
        进程任务的停止信号队列，按需创建

        线程 / 协程任务用 `threading.Event` 传递停止信号，不需要队列；每个队列都会占用若干文件描述符，
        无条件创建会在大量短生命周期任务（如每条 websocket 连接一个心跳任务）下耗尽文件描述符。
        '''

        if self._queue is None:
            self._queue = multiprocessing.get_context('spawn').Queue()
        return self._queue

    def _close_queue(self):
        ''' 释放停止信号队列占用的文件描述符（任务移除后调用） '''

        queue, self._queue = self._queue, None
        if queue is None:
            return

        try:
            queue.close()
            queue.join_thread()
        except (OSError, ValueError):
            ...

    def _stop(self):
        ''' 发送停止信号 '''

        if self.run_type == 'PROCESS':
            self._ensure_queue().put(None)
        else:
            self._stop_event.set()

    def _reset_stop(self):
        ''' 清除停止信号（启动任务前调用） '''

        if self.run_type == 'PROCESS':
            queue = self._ensure_queue()
            while True:
                try:
                    queue.get_nowait()
                except Empty:
                    break
        else:
            self._stop_event.clear()

    def _stops(self) -> bool:
        ''' 是否收到了停止信号 '''

        if self.run_type == 'PROCESS':
            return not self._ensure_queue().empty()
        return self._stop_event.is_set()

    def __getstate__(self) -> tuple[None, dict[str, any]]:
        state = {
            key: getattr(self, key) for key in self.__slots__
        }
        state['_handler'] = None
        state['_stop_event'] = None # `threading.Event` 不能被 pickle，进程任务只用队列信号
        return None, state

    def _to_dict(self) -> dict[str, any]:
        data = {
            key: getattr(self, key) for key in self.__slots__
        }
        data['_queue'] = None
        data['_stop_event'] = None
        data['_handler'] = None
        data['_running_remote'] = self._running_remote
        data['first_run_timer'] = self.first_run_timer.timestamp() if self.first_run_timer else None
        data['_last_run_timer'] = self._last_run_timer.timestamp() if self._last_run_timer else None
        data['fn'] = None
        data['args'] = tuple()
        data['kwargs'] = {}
        data['_scheduler_proxy'] = None
        return data

    def start(self):
        self._scheduler_proxy.start(self.key)

    async def async_start(self):
        if not self._handler:
            self._handler = asyncio.create_task(self._scheduler_proxy.async_task_processing(self.key, self.fn, *self.args, **self.kwargs))

    @property
    def key(self) -> str:
        return self._key

    @property
    def run_num_completed(self) -> bool:
        if self.expected_run_num is None:
            return False
        return self.run_num >= self.expected_run_num

    @property
    def last_run_timer(self) -> datetime.datetime | None:
        ''' 上一次的运行时刻 '''

        return self._last_run_timer

    @property
    def last_run_time(self) -> float | None:
        ''' 上一次的运行耗时 '''

        return self._last_run_time

    @property
    def run_num(self) -> int:
        ''' 运行次数 '''

        return self._run_num

    @property
    def is_running(self) -> bool:
        ''' 任务是否在运行中 '''

        if self._handler is None:
            return self._running_remote
        if isinstance(self._handler, asyncio.Task):
            return not self._handler.done()
        return self._handler.is_alive()

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
            - kwargs: 自动包含 `app: CheeseAPI`，如果不提供 app 参数位置，则不会传入
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
            - kwargs: 自动包含 `app: CheeseAPI`，如果不提供 app 参数位置，则不会传入
            - auto_remove: 任务完成期望次数后是否自动移除
            - timeout: 当 app.sync_server_url 存在时，任务超过多少秒没有执行完毕则认为执行失败，在 sync_server 中会视为任务删除，None 默认为 interval_time * 2 的值；恢复执行后会在 sync_server 上自动恢复
        '''

        return await self._proxy.async_add(interval_time, fn, first_run_timer = first_run_timer, expected_run_num = expected_run_num, key = key, args = args, kwargs = kwargs, auto_remove = auto_remove, timeout = timeout)

    def start(self, key: str):
        ''' 启动任务 '''

        self._proxy.start(key)

    async def async_start(self, key: str):
        ''' 启动任务 '''

        await self._proxy.async_start(key)

    def stop(self, key: str):
        ''' 停止任务 '''


        self._proxy.stop(key)

    def remove(self, key: str):
        ''' 移除任务 '''

        self._proxy.remove(key)

    async def async_stop(self, key: str):
        ''' 停止任务 '''

        await self._proxy.async_stop(key)

    async def async_remove(self, key: str):
        ''' 移除任务 '''

        await self._proxy.async_remove(key)

    def get_tasks(self) -> dict[str, Task]:
        ''' 获取所有任务 '''

        return self._proxy.get_tasks()

    async def async_get_tasks(self) -> dict[str, Task]:
        ''' 获取所有任务 '''

        return await self._proxy.async_get_tasks()

    def get_task(self, key: str) -> Task | None:
        ''' 获取任务 '''

        return self._proxy.get_task(key)

    def _shutdown(self):
        ''' 停机清理，见 `SchedulerProxy._shutdown`；自定义 SchedulerProxy 未实现时跳过（实例存活标记的 TTL 仍能兜底） '''

        shutdown = getattr(self._proxy, '_shutdown', None)
        if shutdown is not None:
            shutdown()

    async def async_get_task(self, key: str) -> Task | None:
        ''' 获取任务 '''

        return await self._proxy.async_get_task(key)

    @property
    def tasks(self) -> dict[str, Task]:
        return self._proxy.get_tasks()

class SchedulerProxy:
    __slots__ = ('app', '_tasks', '_pubsub_ready', '_instance', '_instance_ready')

    def __init__(self, app: 'CheeseAPI'):
        self.app: 'CheeseAPI' = app

        self._tasks: dict[str, Task] = {}
        self._pubsub_ready: bool = False
        self._instance: str = str(uuid.uuid4())
        ''' 本进程实例 id，写进任务记录，供其它进程判断任务属主是否还在运行 '''
        self._instance_ready: bool = False
        ''' 本进程的实例存活标记是否已建立 '''

    def __getstate__(self):
        return None, {
            'app': self.app
        }

    def __setstate__(self, state):
        self.app = state[1]['app']
        self._tasks = {}
        self._pubsub_ready = False
        self._instance = str(uuid.uuid4()) # 工作进程是独立的进程，实例 id 必须重新生成
        self._instance_ready = False

    @staticmethod
    def _instance_key(instance: str) -> str:
        ''' 实例存活标记的 redis key '''

        return f'CheeseAPI_scheduler_instance:{instance}'

    def _instance_ttl(self) -> int:
        '''
        实例存活标记的存活时长（秒）

        取 `sync_server_timeout` 量级：太长会让死进程的残留记录迟迟不能接管，
        太短会在刷新线程偶发延迟时把活进程误判为死进程。
        '''

        return max(1, int(self.app.sync_server_timeout))

    def _instance_alive(self, instance: str | None) -> bool:
        '''
        指定实例（进程）是否还活着

        无 `_instance`（旧记录）或存活标记已过期都视为属主已不存在；读取出错时保守判定为存活，避免误接管正在运行的任务。
        '''

        if not instance or static.scheduler_sync_servers is None:
            return False

        try:
            return bool(redis.Redis(connection_pool = static.scheduler_sync_servers[0]).exists(self._instance_key(instance)))
        except redis.exceptions.RedisError:
            return True

    async def _async_instance_alive(self, instance: str | None) -> bool:
        ''' 见 `_instance_alive` '''

        if not instance or static.scheduler_sync_servers is None:
            return False

        try:
            return bool(await redis.asyncio.Redis(connection_pool = static.scheduler_sync_servers[1]).exists(self._instance_key(instance)))
        except redis.exceptions.RedisError:
            return True

    def _ensure_instance_ready(self):
        '''
        保证本进程的实例存活标记存在，并启动刷新线程

        标记必须在本进程写入任何「运行中」的任务记录之前就位，否则同名任务会被其它进程当作死进程残留接管。
        '''

        if self._instance_ready or static.scheduler_sync_servers is None:
            return

        self._instance_ready = True
        try:
            redis.Redis(connection_pool = static.scheduler_sync_servers[0]).setex(self._instance_key(self._instance), self._instance_ttl(), '1')
        except redis.exceptions.RedisError:
            ...

        threading.Thread(target = self._instance_running, args = (self.app,), daemon = True).start()

    def _instance_running(self, app: 'CheeseAPI'):
        ''' 守护线程：按 `sync_server_timeout` 的一半为周期刷新实例存活标记 '''

        try:
            while True:
                time.sleep(max(0.5, app.sync_server_timeout / 2))
                try:
                    redis.Redis(connection_pool = static.scheduler_sync_servers[0]).setex(self._instance_key(self._instance), self._instance_ttl(), '1')
                except redis.exceptions.RedisError:
                    continue
        except (KeyboardInterrupt, SystemExit):
            ...

    def _shutdown(self):
        '''
        优雅停机：把本进程正在运行的任务标记为非运行，并删除本进程的实例存活标记

        `SIGKILL` 等无法捕获的退出只能靠实例存活标记兜底（标记过期后即可接管），所以这里不是唯一防线。
        '''

        if static.scheduler_sync_servers is None:
            return

        try:
            _redis = redis.Redis(connection_pool = static.scheduler_sync_servers[0])
        except redis.exceptions.RedisError:
            return

        for task in list(self._tasks.values()):
            if not task._running_remote:
                continue

            task._running_remote = False
            try:
                _redis.hset('CheeseAPI_scheduler_tasks', task.key, json.dumps(task._to_dict()))
                _redis.hpersist('CheeseAPI_scheduler_tasks', task.key)
            except redis.exceptions.RedisError:
                ...

        try:
            _redis.delete(self._instance_key(self._instance))
        except redis.exceptions.RedisError:
            ...

    def _start_pubsub(self, app: 'CheeseAPI'):
        try:
            while True:
                try:
                    pubsub = redis.from_url(app.sync_server_url, socket_timeout = None, socket_connect_timeout = None).pubsub()
                    pubsub.subscribe('CheeseAPI_scheduler')
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
        except (KeyboardInterrupt, SystemExit):
            ...

    async def _async_start_pubsub(self, app: 'CheeseAPI'):
        try:
            while True:
                try:
                    pubsub = redis.asyncio.from_url(app.sync_server_url, socket_timeout = None, socket_connect_timeout = None).pubsub()
                    await pubsub.subscribe('CheeseAPI_scheduler')
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
        except (KeyboardInterrupt, SystemExit):
            ...

    def add(self, interval_time: float, fn: Callable | None = None, *, first_run_timer: datetime.datetime | None = None, expected_run_num: int | None = None, key: str | None = None, run_type: Literal['THREAD', 'PROCESS'] = 'THREAD', args: tuple = (), kwargs: dict = {}, auto_remove: bool = False, timeout: float | None = None) -> Callable | Task:
        if fn:
            if self.app.sync_server_url and not self._pubsub_ready:
                self._pubsub_ready = True
                threading.Thread(target = self._start_pubsub, args = (self.app,), daemon = True).start()
                coro = self._async_start_pubsub(self.app)
                try:
                    asyncio.create_task(coro)
                except RuntimeError:
                    coro.close()

            task = Task(fn, interval_time, first_run_timer = first_run_timer, expected_run_num = expected_run_num, key = key, run_type = run_type, args = args, kwargs = kwargs, auto_remove = auto_remove, timeout = timeout, _scheduler_proxy = self)

            if not self._can_add(task.key):
                raise KeyError(f'Task with key "{task.key}" already exists')

            self._tasks[task.key] = task
            task._instance = self._instance
            self._ensure_instance_ready()
            if static.scheduler_sync_servers:
                _redis = redis.Redis(connection_pool = static.scheduler_sync_servers[0])
                _redis.hset('CheeseAPI_scheduler_tasks', task.key, json.dumps(task._to_dict()))
                _redis.hpexpire('CheeseAPI_scheduler_tasks', _timeout_ms(task), task.key)

            return task
        else:
            def wrapper(_fn: Callable):
                task = self.add(interval_time, _fn, first_run_timer = first_run_timer, expected_run_num = expected_run_num, key = key, run_type = run_type, args = args, kwargs = kwargs, auto_remove = auto_remove, timeout = timeout)
                task.start()
                return _fn
            return wrapper

    async def async_add(self, interval_time: float | None = None, fn: Callable | None = None, *, first_run_timer: datetime.datetime | None = None, expected_run_num: int | None = None, key: str | None = None, args: tuple = (), kwargs: dict = {}, auto_remove: bool = False, timeout: float | None = None) -> Callable | Task:
        if fn is not None:
            if self.app.sync_server_url and not self._pubsub_ready:
                self._pubsub_ready = True
                threading.Thread(target = self._start_pubsub, args = (self.app,), daemon = True).start()
                coro = self._async_start_pubsub(self.app)
                try:
                    asyncio.create_task(coro)
                except RuntimeError:
                    coro.close()

            task = Task(fn, interval_time = interval_time, first_run_timer = first_run_timer, expected_run_num = expected_run_num, key = key, run_type = 'ASYNC', args = args, kwargs = kwargs, auto_remove = auto_remove, timeout = timeout, _scheduler_proxy = self)

            if not await self._async_can_add(task.key):
                raise KeyError(f'Task with key "{task.key}" already exists')

            self._tasks[task.key] = task
            task._instance = self._instance
            self._ensure_instance_ready()
            if static.scheduler_sync_servers:
                _redis = redis.asyncio.Redis(connection_pool = static.scheduler_sync_servers[1])
                await _redis.hset('CheeseAPI_scheduler_tasks', task.key, json.dumps(task._to_dict()))
                await _redis.hpexpire('CheeseAPI_scheduler_tasks', _timeout_ms(task), task.key)

            return task
        else:
            async def wrapper(_fn: Callable):
                task = await self.async_add(interval_time, _fn, first_run_timer = first_run_timer, expected_run_num = expected_run_num, key = key, args = args, kwargs = kwargs, auto_remove = auto_remove, timeout = timeout)
                await task.async_start()
                return _fn
            return wrapper

    def task_processing(self, task: Task, fn, *args, **kwargs):
        try:
            if task.first_run_timer:
                time.sleep(max(0, task.first_run_timer.timestamp() - time.time()))

            while not task._stops():
                now = time.time()

                try:
                    signature = inspect.signature(fn)
                    has_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in signature.parameters.values())
                    if 'app' in signature.parameters or has_kwargs:
                        fn(*args, app = self.app, **kwargs)
                    else:
                        fn(*args, **kwargs)
                except Exception as e:
                    self.app.printer.scheduler_error(e, task)

                if task._stops():
                    break

                task._last_run_time = time.time() - now
                task._last_run_timer = datetime.datetime.fromtimestamp(now)
                task._run_num += 1

                if static.scheduler_sync_servers:
                    sync_server = redis.Redis(connection_pool = static.scheduler_sync_servers[0])
                    sync_server.hset('CheeseAPI_scheduler_tasks', task.key, json.dumps(task._to_dict()))
                    sync_server.hpexpire('CheeseAPI_scheduler_tasks', int(task.timeout * 1000), task.key)

                if task.run_num_completed:
                    break

                time.sleep(max(0, task.interval_time - time.time() + now))
        except (KeyboardInterrupt, SystemExit):
            ...

        if static.scheduler_sync_servers:
            _redis = redis.Redis(connection_pool = static.scheduler_sync_servers[0])
            if _redis.hexists('CheeseAPI_scheduler_tasks', task.key):
                task._running_remote = False # 任务已结束，清除共享存储里的运行状态，使重启后的同名任务可以注册
                _redis.hset('CheeseAPI_scheduler_tasks', task.key, json.dumps(task._to_dict()))
                _redis.hpersist('CheeseAPI_scheduler_tasks', task.key)

        if task.run_type == 'PROCESS':
            task._reset_stop() # 取出残留的停止信号，保证下次启动时队列是干净的

    async def async_task_processing(self, key: str, fn, *args, **kwargs):
        task = self._tasks.get(key)
        if task is None:
            task = await self.async_get_task(key)
        if task is None:
            return

        if task.first_run_timer:
            await asyncio.sleep(max(0, task.first_run_timer.timestamp() - time.time()))

        while not task._stops():
            now = time.time()

            try:
                signature = inspect.signature(fn)
                has_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in signature.parameters.values())
                if 'app' in signature.parameters or has_kwargs:
                    await fn(*args, app = self.app, **kwargs)
                else:
                    await fn(*args, **kwargs)
            except Exception as e:
                self.app.printer.scheduler_error(e, task)

            if task._stops():
                break

            task._last_run_time = time.time() - now
            task._last_run_timer = datetime.datetime.fromtimestamp(now)
            task._run_num += 1

            if static.scheduler_sync_servers:
                sync_server = redis.asyncio.Redis(connection_pool = static.scheduler_sync_servers[1])
                await sync_server.hset('CheeseAPI_scheduler_tasks', key, json.dumps(task._to_dict()))
                await sync_server.hpexpire('CheeseAPI_scheduler_tasks', int(task.timeout * 1000), key)

            if task.run_num_completed:
                break

            await asyncio.sleep(max(0, task.interval_time - time.time() + now))

        if task.auto_remove:
            local_task = self._tasks.pop(key, None)
            if local_task is not None:
                local_task._close_queue()
            if static.scheduler_sync_servers is not None:
                await redis.asyncio.Redis(connection_pool = static.scheduler_sync_servers[1]).hdel('CheeseAPI_scheduler_tasks', key)
        else:
            if static.scheduler_sync_servers:
                task._running_remote = False # 任务已结束，清除共享存储里的运行状态
                _redis = redis.asyncio.Redis(connection_pool = static.scheduler_sync_servers[1])
                if await _redis.hexists('CheeseAPI_scheduler_tasks', key):
                    await _redis.hset('CheeseAPI_scheduler_tasks', key, json.dumps(task._to_dict()))
                    await _redis.hpersist('CheeseAPI_scheduler_tasks', key)

    def join(self, task: Task):
        if task.run_type == 'THREAD' and isinstance(task._handler, threading.Thread):
            task._handler.join()
        elif task.run_type == 'PROCESS' and isinstance(task._handler, multiprocessing.Process):
            task._handler.join()
        self._tasks.pop(task.key, None)
        task._close_queue()
        if static.scheduler_sync_servers:
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

        task._reset_stop()
        if task.run_type == 'THREAD':
            task._handler = threading.Thread(target = self.task_processing, args = (task, task.fn, *task.args), kwargs = task.kwargs, daemon = True)
        elif task.run_type == 'PROCESS':
            task._ensure_queue() # 队列必须在 `spawn` 之前创建，子进程才能拿到同一个队列
            task._handler = multiprocessing.get_context('spawn').Process(target = self.task_processing, args = (task, task.fn, *task.args), kwargs = task.kwargs, daemon = True)
        task._running_remote = True # 必须先置位：进程任务在 `start` 时就（通过 pickle）把状态传给子进程
        task._handler.start()

        task._instance = self._instance
        self._ensure_instance_ready()
        if static.scheduler_sync_servers:
            _redis = redis.Redis(connection_pool = static.scheduler_sync_servers[0])
            _redis.hset('CheeseAPI_scheduler_tasks', task.key, json.dumps(task._to_dict()))
            _redis.hpexpire('CheeseAPI_scheduler_tasks', _timeout_ms(task), task.key)

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
            task._reset_stop()
            task._handler = asyncio.create_task(self.async_task_processing(key, task.fn, *task.args, **task.kwargs))
            task._running_remote = True
            task._instance = self._instance
            self._ensure_instance_ready()
            if static.scheduler_sync_servers:
                _redis = redis.asyncio.Redis(connection_pool = static.scheduler_sync_servers[1])
                await _redis.hset('CheeseAPI_scheduler_tasks', key, json.dumps(task._to_dict()))
                await _redis.hpexpire('CheeseAPI_scheduler_tasks', _timeout_ms(task), key)

    def stop(self, key: str):
        task = self.get_task(key)
        if not task:
            raise KeyError(f'Task with key "{key}" does not exist')
        if not task.is_running:
            raise KeyError(f'Task with key "{key}" is not running')

        local_task = self._tasks.get(key)
        if not local_task:
            if static.scheduler_sync_servers:
                redis.Redis(connection_pool = static.scheduler_sync_servers[0]).publish('CheeseAPI_scheduler', json.dumps(['stop', key]))
        else:
            local_task._stop()
            local_task._running_remote = False
            if static.scheduler_sync_servers:
                _redis = redis.Redis(connection_pool = static.scheduler_sync_servers[0])
                _redis.hset('CheeseAPI_scheduler_tasks', key, json.dumps(local_task._to_dict()))
                _redis.hpexpire('CheeseAPI_scheduler_tasks', _timeout_ms(local_task), key)

        time.sleep(self.app.sync_server_timeout)

    def remove(self, key: str):
        task = self.get_task(key)
        if not task:
            return

        local_task = self._tasks.get(key)
        if not local_task:
            if static.scheduler_sync_servers:
                redis.Redis(connection_pool = static.scheduler_sync_servers[0]).publish('CheeseAPI_scheduler', json.dumps(['remove', key]))
        else:
            local_task._stop()
            self._tasks.pop(key, None)
            local_task._close_queue()
            if static.scheduler_sync_servers:
                redis.Redis(connection_pool = static.scheduler_sync_servers[0]).hdel('CheeseAPI_scheduler_tasks', key)

    async def async_stop(self, key: str):
        task = await self.async_get_task(key)
        if not task:
            raise KeyError(f'Task with key "{key}" does not exist')
        if not task.is_running:
            raise KeyError(f'Task with key "{key}" is not running')

        local_task = self._tasks.get(key)
        if not local_task:
            if static.scheduler_sync_servers:
                await redis.asyncio.Redis(connection_pool = static.scheduler_sync_servers[1]).publish('CheeseAPI_scheduler', json.dumps(['stop', key]))
        else:
            local_task._stop()
            local_task._running_remote = False
            if static.scheduler_sync_servers:
                _redis = redis.asyncio.Redis(connection_pool = static.scheduler_sync_servers[1])
                await _redis.hset('CheeseAPI_scheduler_tasks', key, json.dumps(local_task._to_dict()))
                await _redis.hpexpire('CheeseAPI_scheduler_tasks', _timeout_ms(local_task), key)

    async def async_remove(self, key: str):
        task = await self.async_get_task(key)
        if not task:
            return

        local_task = self._tasks.get(key)
        if not local_task:
            if static.scheduler_sync_servers:
                await redis.asyncio.Redis(connection_pool = static.scheduler_sync_servers[1]).publish('CheeseAPI_scheduler', json.dumps(['remove', key]))
        else:
            local_task._stop()
            self._tasks.pop(key, None)
            local_task._close_queue()
            if static.scheduler_sync_servers:
                await redis.asyncio.Redis(connection_pool = static.scheduler_sync_servers[1]).hdel('CheeseAPI_scheduler_tasks', key)

    def _can_add(self, key: str) -> bool:
        '''
        该 key 是否可以注册任务

        未使用 sync_server 时任务只存在于本进程，重复注册一律报错；
        使用 sync_server 时任务记录跨进程共享：同名任务由存活进程运行时报错，
        记录虽为「运行中」但属主进程已不存在（崩溃 / 被杀后的残留），
        或只剩上次运行退出后残留的记录（未在运行）则允许接管，否则进程重启后无法再注册自己的任务。
        '''

        if static.scheduler_sync_servers is None:
            return key not in self._tasks

        task = self.get_task(key)
        if task is None or not task.is_running:
            return True

        return not self._instance_alive(task._instance)

    async def _async_can_add(self, key: str) -> bool:
        ''' 见 `_can_add` '''

        if static.scheduler_sync_servers is None:
            return key not in self._tasks

        task = await self.async_get_task(key)
        if task is None or not task.is_running:
            return True

        return not await self._async_instance_alive(task._instance)

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
                key.decode(): Task.from_dict(json.loads(data), self) for key, data in (await redis.asyncio.Redis(connection_pool = static.scheduler_sync_servers[1]).hgetall('CheeseAPI_scheduler_tasks')).items()
            }

        return self._tasks
