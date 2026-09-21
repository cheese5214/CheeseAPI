'''
生命周期信号测试应用

服务端把信号触发情况写进 `STATE`，测试进程读文件断言。

文件名带 `_hooks` 后缀是刻意的：不能叫 `signal.py`——`apps/` 会被从该目录启动的应用放进 `sys.path[0]`，
与标准库 `signal` 同名会遮蔽它，连 `multiprocessing` 都导入不了（所有测试应用一起起不来）。
'''
import os

from apputils import AppState, capture_warnings

capture_warnings()

from CheeseAPI import CheeseAPI, Response

STATE = AppState(events = [], order = [], handler_order = [], raise_in = [], raise_skip = {})

app = CheeseAPI(port = int(os.environ['CHEESE_TEST_PORT']))

def record(name: str, **info):
    ''' 记录一次信号触发 '''

    STATE.data['events'].append({'name': name, **info})
    STATE.dump()

def check_raise(name: str):
    ''' 由路由开关控制：让对应信号的处理函数抛异常

    `skip` 用于跳过「设置开关的那个请求自己」，否则 `before_response` / `after_response` /
    `after_request` 会在设置开关的同一个请求周期里就被消费掉
    '''

    if name not in STATE.data['raise_in']:
        return

    if STATE.data['raise_skip'].get(name, 0) > 0:
        STATE.data['raise_skip'][name] -= 1
        STATE.dump()
        return

    STATE.data['raise_in'].remove(name)
    STATE.dump()
    raise RuntimeError(f'probe raise in {name}')

#### 生命周期信号 ####

@app.signal.before_load_modules.connect()
def on_before_load_modules(*, modules: list[str]):
    record('before_load_modules', modules = list(modules))

@app.signal.before_load_module.connect()
def on_before_load_module(*, index: int, modules: str):
    ''' 框架发送的键名就是 `modules`（值为单个模块名） '''

    record('before_load_module', index = index, module = modules)

@app.signal.after_load_module.connect()
def on_after_load_module(*, index: int, modules: str):
    record('after_load_module', index = index, module = modules)

@app.signal.after_load_modules.connect()
def on_after_load_modules(*, modules: list[str]):
    record('after_load_modules', modules = list(modules))

@app.signal.before_server_start.connect()
def on_before_server_start():
    record('before_server_start')

@app.signal.after_server_start.connect()
def on_after_server_start():
    record('after_server_start')

@app.signal.before_workers_start.connect()
def on_before_workers_start(*, workers: int):
    record('before_workers_start', workers = workers)

@app.signal.after_workers_start.connect()
def on_after_workers_start(*, workers: int):
    record('after_workers_start', workers = workers)

@app.signal.before_worker_start.connect()
def on_before_worker_start(*, is_first: bool):
    record('before_worker_start', is_first = is_first)

@app.signal.after_worker_start.connect()
async def on_after_worker_start(*, is_first: bool):
    record('after_worker_start', is_first = is_first)

@app.signal.before_worker_stop.connect()
async def on_before_worker_stop(*, is_first: bool):
    record('before_worker_stop', is_first = is_first)

@app.signal.after_worker_stop.connect()
def on_after_worker_stop(*, is_first: bool):
    record('after_worker_stop', is_first = is_first)

@app.signal.before_app_stop.connect()
def on_before_app_stop():
    record('before_app_stop')

@app.signal.after_app_stop.connect()
def on_after_app_stop():
    record('after_app_stop')

#### 请求周期信号 ####

@app.signal.before_request.connect()
async def on_before_request(*, client_socket, addr):
    STATE.data['order'].append('before_request')
    record('before_request', addr = f'{addr[0]}:{addr[1]}', socket = type(client_socket).__name__)
    check_raise('before_request')

@app.signal.after_request.connect()
async def on_after_request(*, request):
    STATE.data['order'].append('after_request')
    record('after_request', method = getattr(request, 'method', None), path = getattr(request, 'path', None), type = type(request).__name__)
    check_raise('after_request')

@app.signal.before_response.connect()
async def on_before_response(*, response):
    STATE.data['order'].append('before_response')
    record('before_response', status = getattr(response, 'status', None), type = type(response).__name__, body = str(getattr(response, 'body', None))[:20])
    check_raise('before_response')

@app.signal.after_response.connect()
async def on_after_response(*, response):
    STATE.data['order'].append('after_response')
    record('after_response', status = getattr(response, 'status', None), type = type(response).__name__, body = str(getattr(response, 'body', None))[:20])
    check_raise('after_response')

#### 同一信号多个处理函数（按注册顺序执行） ####

@app.signal.before_request.connect()
async def handler_first(**_):
    STATE.data['handler_order'].append('first')
    STATE.dump()

@app.signal.before_request.connect()
async def handler_second(**_):
    STATE.data['handler_order'].append('second')
    STATE.dump()

@app.signal.before_request.connect()
async def handler_third(**_):
    STATE.data['handler_order'].append('third')
    STATE.dump()

#### 路由 ####

@app.route.get('/health')
async def health(**_):
    return Response('ok')

@app.route.get('/probe')
async def probe(**_):
    ''' 探针路由：请求周期里记录一次 route '''

    STATE.data['order'].append('route')
    STATE.dump()
    return Response('probe')

@app.route.get('/reset')
async def reset(**_):
    STATE.data['order'] = []
    STATE.data['handler_order'] = []
    STATE.dump()
    return Response('reset')

@app.route.get('/raise')
async def raise_in(*, request, **_):
    ''' `?name=before_response&skip=1`：让指定信号的处理函数在下次触发时抛异常 '''

    names = [name for name in request.query.get('name', '').split(',') if name]
    skip = int(request.query.get('skip', '0'))
    STATE.data['raise_in'] = names
    STATE.data['raise_skip'] = {
        name: skip for name in names
    }
    STATE.dump()
    return Response('raise=' + ','.join(names))

if __name__ == '__main__':
    app.start()
