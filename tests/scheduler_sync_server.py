'''
调度器 sync_server 语义用例（死进程残留记录 → 启动即 KeyError → 重启循环）

与 `tests/run.py` 里的用例不同，这里直接连本机 redis，不启动 HTTP 服务：

```bash
python tests/scheduler_sync_server.py
```

- 用 **db 9**，避免污染部署库；脚本开头会 `flushdb`。
- 复现的是「死进程留下的 `_running_remote: true` 残留记录阻塞新进程注册」：
  修复前 `_can_add` 只看运行状态，残留记录一律拒绝接管；修复后靠实例存活标记判断属主是否还在。

覆盖：
1. 旧格式残留记录（无 `_instance`）→ 新进程能接管
2. 真·属主进程被 `SIGKILL` → 新进程秒级接管
3. 属主进程还活着 → 拒绝注册（去重语义不能削弱），且存活标记被持续刷新
4. 优雅停机（`app.stop()`）→ 记录置为非运行、存活标记清除，新进程即时接管
5. 未配置 sync_server 时 → 同进程重复注册仍报错
6. 共享记录写 TTL：不出现「永久 + 运行中」的记录形态
'''
import atexit, json, os, subprocess, sys, time
from pathlib import Path

import redis

TESTS_DIR = Path(__file__).parent
PROJECT_ROOT = TESTS_DIR.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

REDIS_URL = os.environ.get('CHEESE_TEST_REDIS', 'redis://127.0.0.1:6379/9')
HASH = 'CheeseAPI_scheduler_tasks'

from CheeseAPI import CheeseAPI, static
from CheeseAPI.scheduler import Task

WORKER_CODE = '''
import os, signal, sys, time
from CheeseAPI import CheeseAPI

app = CheeseAPI(sync_server_url = os.environ['REDIS_URL'], sync_server_timeout = 1)
app._proxy._process_init()

def task(*, app):
    time.sleep(3600)

task = app.scheduler.add(30, task, key = os.environ['TASK_KEY'])
task.start()

if os.environ.get('GRACEFUL'):
    def shutdown(*_):
        app._proxy.stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)

print('READY', flush = True)
time.sleep(3600)
'''

class Checker:
    __slots__ = ('results',)

    def __init__(self):
        self.results: list[tuple[str, bool, str]] = []

    def check(self, name: str, condition, detail: str = '') -> bool:
        condition = bool(condition)
        self.results.append((name, condition, detail))
        print(f'  {"PASS" if condition else "FAIL"}  {name}' + (f'  | {detail}' if detail else ''))
        return condition

    @property
    def failed(self):
        return [item for item in self.results if not item[1]]

    @property
    def summary(self) -> str:
        return f'{len(self.results) - len(self.failed)}/{len(self.results)} passed'

def hpttl(client: redis.Redis, key: str) -> int:
    ''' 记录字段的剩余 TTL（毫秒）：-1 表示永久，-2 表示不存在（不同 redis-py 版本可能返回标量或列表） '''

    value = client.hpttl(HASH, key)
    if isinstance(value, (list, tuple)):
        value = value[0]
    return int(value)

WORKERS: list[subprocess.Popen] = []

''' 结束时清掉常驻子进程与测试用的 redis 键，避免在脚本报错中断时留下孤儿进程 / 脏数据 '''
def cleanup():
    for process in WORKERS:
        if process.poll() is None:
            process.kill()
            process.wait()

    redis.Redis.from_url(REDIS_URL).flushdb()

atexit.register(cleanup)

def spawn_worker(key: str, graceful: bool = False) -> subprocess.Popen:
    ''' 起一个「占用 task key 的进程」：注册并启动任务后常驻 '''

    process = subprocess.Popen(
        [sys.executable, '-c', WORKER_CODE],
        env = dict(os.environ, REDIS_URL = REDIS_URL, TASK_KEY = key, GRACEFUL = '1' if graceful else '',
            # site-packages 里可能装着旧版 CheeseAPI（如 1.7.x），必须让子进程优先 import 源码目录
            PYTHONPATH = os.pathsep.join(filter(None, [str(PROJECT_ROOT), os.environ.get('PYTHONPATH', '')]))),
        cwd = str(TESTS_DIR),
        stdout = subprocess.PIPE,
        stderr = subprocess.STDOUT,
        text = True
    )
    WORKERS.append(process)
    return process

def wait_ready(process: subprocess.Popen, timeout: float = 30.0) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if process.poll() is not None:
            return '已退出'
        line = process.stdout.readline()
        if 'READY' in line:
            return 'READY'
        if line == '':
            break
    return '超时'

def try_add(app: CheeseAPI, key: str, deadline: float = 5.0) -> tuple[bool, float, str]:
    ''' 反复尝试注册同名任务，返回（是否成功、耗时、最后一次的报错） '''

    started = time.time()
    error = ''

    while time.time() - started < deadline:
        try:
            app.scheduler.add(30, lambda *, app: None, key = key)
            return True, time.time() - started, ''
        except KeyError as e:
            error = str(e)
            time.sleep(0.2)

    return False, time.time() - started, error

def main() -> int:
    checker = Checker()

    client = redis.Redis.from_url(REDIS_URL)
    client.flushdb()

    app = CheeseAPI(sync_server_url = REDIS_URL, sync_server_timeout = 1)
    app._proxy._process_init()

    ''' 1. 旧格式残留记录（无 `_instance`）：属主无从判断，必须允许接管 '''
    probe = Task(lambda: None, 30, key = 'legacy-key', _scheduler_proxy = app.scheduler._proxy)
    data = probe._to_dict()
    data['_running_remote'] = True
    data.pop('_instance', None) # 旧格式记录本就没有该字段
    client.hset(HASH, 'legacy-key', json.dumps(data))

    try:
        app.scheduler.add(30, lambda *, app: None, key = 'legacy-key')
        checker.check('残留：无 `_instance` 的旧格式「运行中」记录允许接管', True)
    except KeyError as e:
        checker.check('残留：无 `_instance` 的旧格式「运行中」记录允许接管', False, f'{e}')

    ''' 2. 属主进程被 SIGKILL（无法优雅关闭，只能靠存活标记过期）→ 秒级接管 '''
    crashed = spawn_worker('crash-key')
    ready = wait_ready(crashed)
    checker.check('残留：属主进程已注册并启动任务', ready == 'READY', f'{ready}')

    crashed.kill()
    crashed.wait()

    ok, elapsed, error = try_add(app, 'crash-key')
    checker.check('残留：属主进程被 SIGKILL 后新进程能接管', ok, f'elapsed={elapsed:.2f}s, error={error!r}')
    checker.check('残留：接管耗时是秒级（< 5s，而非 interval_time * 2）', ok and elapsed < 5, f'elapsed={elapsed:.2f}s')

    ''' 3. 属主进程还活着 → 拒绝注册 '''
    alive = spawn_worker('live-key')
    ready = wait_ready(alive)
    checker.check('去重：属主进程已注册并启动任务', ready == 'READY', f'{ready}')

    try:
        app.scheduler.add(30, lambda *, app: None, key = 'live-key')
        checker.check('去重：属主进程存活时拒绝重复注册', False, '居然注册成功了')
    except KeyError as e:
        checker.check('去重：属主进程存活时拒绝重复注册', 'already exists' in str(e), f'{e}')

    record = json.loads(client.hget(HASH, 'live-key'))
    checker.check('记录：存活进程的运行中记录带有 `_instance`', bool(record.get('_instance')), f'{record.get("_instance")!r}')
    ttl = hpttl(client, 'live-key')
    checker.check('TTL：运行中的记录带 TTL（不是永久记录）', 0 < ttl <= 120000, f'hpttl={ttl}ms')

    ''' 3b. 存活属主超过一个标记 TTL 后仍拒绝：守护线程在给存活标记续期 '''
    time.sleep(3 * app.sync_server_timeout)
    checker.check('去重：存活属主的存活标记被持续刷新', client.exists(f'CheeseAPI_scheduler_instance:{record["_instance"]}') == 1)

    try:
        app.scheduler.add(30, lambda *, app: None, key = 'live-key')
        checker.check('去重：存活属主超过一个标记 TTL 后仍拒绝重复注册', False, '居然注册成功了')
    except KeyError as e:
        checker.check('去重：存活属主超过一个标记 TTL 后仍拒绝重复注册', 'already exists' in str(e), f'{e}')

    alive.kill()
    alive.wait()

    ''' 4. 优雅停机（`app.stop()` 链路）：任务标记为非运行、存活标记清除，新进程无需等待即时接管 '''
    graceful = spawn_worker('graceful-key', graceful = True)
    ready = wait_ready(graceful)
    checker.check('停机：属主进程已注册并启动任务', ready == 'READY', f'{ready}')
    instance = json.loads(client.hget(HASH, 'graceful-key'))['_instance']

    graceful.terminate()
    graceful.wait(timeout = 30)

    checker.check('停机：`app.stop()` 把本进程运行中的任务标记为非运行', json.loads(client.hget(HASH, 'graceful-key'))['_running_remote'] is False)
    checker.check('停机：`app.stop()` 清除本进程的存活标记', client.exists(f'CheeseAPI_scheduler_instance:{instance}') == 0)

    ok, elapsed, error = try_add(app, 'graceful-key')
    checker.check('停机：优雅停机后新进程即时接管（无需等标记过期）', ok and elapsed < 1, f'elapsed={elapsed:.2f}s, error={error!r}')

    ''' 5. 未配置 sync_server 时：同进程重复注册仍一律报错 '''
    servers, static.scheduler_sync_servers = static.scheduler_sync_servers, None
    try:
        app.scheduler.add(30, lambda *, app: None, key = 'local-key')
        try:
            app.scheduler.add(30, lambda *, app: None, key = 'local-key')
            checker.check('去重：未配置 sync_server 时同进程重复注册报错', False, '居然注册成功了')
        except KeyError as e:
            checker.check('去重：未配置 sync_server 时同进程重复注册报错', 'already exists' in str(e), f'{e}')
    finally:
        static.scheduler_sync_servers = servers

    ''' 6. 写共享记录的地方都带 TTL 兜底：不出现「永久 + 运行中」的记录形态 '''
    client.delete(HASH)
    app.scheduler.add(30, lambda *, app: None, key = 'ttl-key')
    ttl = hpttl(client, 'ttl-key')
    checker.check('TTL：`add` 写入的记录带 TTL', 0 < ttl <= 120000, f'hpttl={ttl}ms')

    app.scheduler.start('ttl-key')
    record = json.loads(client.hget(HASH, 'ttl-key'))
    ttl = hpttl(client, 'ttl-key')
    checker.check('TTL：`start` 写入的运行中记录带 TTL（杜绝「永久 + 运行中」）', record['_running_remote'] is True and 0 < ttl <= 120000, f'hpttl={ttl}ms')

    try:
        app.scheduler._shutdown()
        checker.check('停机：`_shutdown()` 清除实例存活标记', client.exists(f'CheeseAPI_scheduler_instance:{app.scheduler._proxy._instance}') == 0)
        checker.check('停机：`_shutdown()` 把本进程运行中的任务标记为非运行', json.loads(client.hget(HASH, 'ttl-key'))['_running_remote'] is False)
    except AttributeError as e:
        checker.check('停机：优雅停机钩子存在', False, f'{e}')

    client.flushdb()
    print(f'\n===== {checker.summary} =====')
    return 1 if checker.failed else 0

if __name__ == '__main__':
    sys.exit(main())
