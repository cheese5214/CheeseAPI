'''
定时任务测试应用

任务执行次数通过 `STATE`（线程 / 协程任务）传给测试进程；进程任务（`spawn` 子进程会重新执行本文件，
重建 `AppState` 会把状态文件重置）的计数单独存一个文件。

其余可观测状态（任务注册表、运行次数、是否在运行……）全部通过 HTTP 路由暴露。
'''
from apputils import AppState, capture_warnings

capture_warnings()

import multiprocessing, os, sys

# 本文件位于 `apps/` 目录，脚本目录会被放进 `sys.path[0]`，与其他域的同名文件（如 `signal.py`）冲突，
# 这里统一把脚本目录移出 `sys.path`
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:] = [path for path in sys.path if os.path.abspath(path or os.getcwd()) != _HERE]

from CheeseAPI import CheeseAPI, Response

STATE = AppState(thread_runs = 0, async_runs = 0)

PROCESS_RUNS_PATH = os.environ['CHEESE_TEST_STATE'] + '.process'

app = CheeseAPI(port = int(os.environ['CHEESE_TEST_PORT']))

#### 任务函数 ####

def thread_task(*, app):
    ''' 线程任务：拿到注入的 `app` 参数，执行次数写进 `STATE` '''

    STATE.inc('thread_runs')

async def async_task(*, app):
    ''' 协程任务 '''

    STATE.inc('async_runs')

def process_task(*, app):
    ''' 进程任务：独立进程里整体覆写状态文件会与其他任务打架，改为追加一行 '''

    with open(PROCESS_RUNS_PATH, 'a', encoding = 'utf-8') as f:
        f.write('1\n')

#### 工具 ####

def safe(getter, default = None):
    ''' 取值失败时把异常名当作值返回，方便测试观测到内部异常 '''

    try:
        return getter()
    except Exception as e:
        return type(e).__name__

def describe(task) -> dict:
    ''' 任务的可观测字段（不触碰私有属性） '''

    return {
        'key': task.key,
        'run_num': task.run_num,
        'run_num_completed': safe(lambda: task.run_num_completed),
        'is_running': safe(lambda: task.is_running),
        'run_type': task.run_type,
        'interval_time': task.interval_time,
        'expected_run_num': task.expected_run_num,
        'auto_remove': task.auto_remove,
        'timeout': task.timeout,
        'last_run_timer': task.last_run_timer.timestamp() if task.last_run_timer else None,
        'last_run_time': task.last_run_time
    }

#### 路由 ####

@app.route.get('/health')
async def health(**_):
    return Response('ok')

@app.route.get('/platform/qsize')
async def platform_qsize(**_):
    ''' 当前平台是否支持 `multiprocessing.Queue.qsize()`（macOS 未实现，任务逻辑依赖它） '''

    try:
        multiprocessing.get_context('spawn').Queue().qsize()
        return Response('1')
    except Exception:
        return Response('0')

@app.route.get('/runs')
async def runs(*, request, **_):
    ''' 任务执行次数：线程 / 协程读 STATE，进程读独立文件 '''

    name = request.query.get('name', 'thread')
    if name == 'process':
        try:
            with open(PROCESS_RUNS_PATH, encoding = 'utf-8') as f:
                return Response(str(len([line for line in f.read().splitlines() if line])))
        except FileNotFoundError:
            return Response('0')

    return Response(str(STATE.data.get(f'{name}_runs', 0)))

@app.route.get('/tasks')
async def tasks(**_):
    return Response({
        key: describe(task) for key, task in app.scheduler.get_tasks().items()
    })

@app.route.get('/task-count')
async def task_count(**_):
    return Response(str(len(app.scheduler.tasks)))

@app.route.get('/task/add')
async def task_add(*, request, **_):
    ''' `?name=thread|async|process&interval=0.3&expected=2&auto_remove=1&key=xxx` 注册并启动任务 '''

    params = request.query
    name = params.get('name', 'thread')
    interval = float(params.get('interval', '0.3'))
    expected = int(params['expected']) if 'expected' in params else None
    auto_remove = params.get('auto_remove') == '1'
    key = params.get('key') or None

    try:
        if name == 'thread':
            task = app.scheduler.add(interval, thread_task, key = key, expected_run_num = expected, auto_remove = auto_remove)
            task.start()
        elif name == 'process':
            task = app.scheduler.add(interval, process_task, key = key, run_type = 'PROCESS', expected_run_num = expected, auto_remove = auto_remove)
            task.start()
        else:
            task = await app.scheduler.async_add(interval, async_task, key = key, expected_run_num = expected, auto_remove = auto_remove)
            await task.async_start()
    except Exception as e:
        return Response(f'{type(e).__name__}: {e}', status = 500)

    return Response(task.key)

@app.route.get('/task/add-without-start')
async def task_add_without_start(*, request, **_):
    ''' 函数调用写法：`add` / `async_add` 只注册并返回 Task，不会自动启动

    `?name=thread|process|async&interval=0.3&key=xxx&expected=2&timeout=1&auto_remove=1`
    '''

    params = request.query
    name = params.get('name', 'thread')
    interval = float(params.get('interval', '0.3'))
    expected = int(params['expected']) if 'expected' in params else None
    timeout = float(params['timeout']) if 'timeout' in params else None
    auto_remove = params.get('auto_remove') == '1'
    key = params.get('key') or None

    try:
        if name == 'async':
            task = await app.scheduler.async_add(interval, async_task, key = key, expected_run_num = expected, auto_remove = auto_remove, timeout = timeout)
        else:
            task = app.scheduler.add(interval, thread_task if name == 'thread' else process_task, key = key, run_type = 'THREAD' if name == 'thread' else 'PROCESS', expected_run_num = expected, auto_remove = auto_remove, timeout = timeout)
    except Exception as e:
        return Response(f'{type(e).__name__}: {e}', status = 500)

    return Response(task.key)

@app.route.get('/task/decorate')
async def task_decorate(*, request, **_):
    ''' 装饰器写法：注册并自动启动任务 '''

    params = request.query
    try:
        task = app.scheduler.add(float(params.get('interval', '0.3')), key = params.get('key') or None)(thread_task)
    except Exception as e:
        return Response(f'{type(e).__name__}: {e}', status = 500)

    return Response(task.key)

@app.route.get('/task/start')
async def task_start(*, request, **_):
    try:
        app.scheduler.start(request.query['key'])
    except Exception as e:
        return Response(f'{type(e).__name__}: {e}', status = 500)

    return Response('started')

@app.route.get('/task/async-start')
async def task_async_start(*, request, **_):
    try:
        await app.scheduler.async_start(request.query['key'])
    except Exception as e:
        return Response(f'{type(e).__name__}: {e}', status = 500)

    return Response('started')

@app.route.get('/task/stop')
async def task_stop(*, request, **_):
    try:
        app.scheduler.stop(request.query['key'])
    except Exception as e:
        return Response(f'{type(e).__name__}: {e}', status = 500)

    return Response('stopped')

@app.route.get('/task/remove')
async def task_remove(*, request, **_):
    try:
        app.scheduler.remove(request.query['key'])
    except Exception as e:
        return Response(f'{type(e).__name__}: {e}', status = 500)

    return Response('removed')

@app.route.get('/task/get')
async def task_get(*, request, **_):
    ''' 用 `get_task` 取单个任务，验证显式 key 与自动生成的 key '''

    task = app.scheduler.get_task(request.query.get('key', ''))
    return Response({
        'exists': task is not None,
        'describe': describe(task) if task else None
    })

if __name__ == '__main__':
    app.start()
