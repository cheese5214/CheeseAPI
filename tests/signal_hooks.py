'''
生命周期信号用例

覆盖：应用生命周期信号（启动 / 停机）的触发与顺序、请求周期信号的触发顺序与上下文参数、
同一信号多个处理函数的执行顺序、信号处理函数抛异常时的表现。

文件名带 `_hooks` 后缀是刻意的：不能叫 `signal.py`——`tests/` 会在测试进程的 `sys.path` 里，
`apps/` 会在应用进程的 `sys.path[0]` 里，与标准库 `signal` 同名会遮蔽它，
`subprocess` / `multiprocessing` 会因此导入到测试文件而崩掉。
'''
import time

import requests

APP = 'apps/signal_hooks.py'

# 单次请求（`connection: close`）的完整信号顺序：请求周期信号都在这一轮里触发
CYCLE = ['before_request', 'route', 'before_response', 'after_response', 'after_request']

CLOSE = {'connection': 'close'}

def names(server) -> list[str]:
    return [event['name'] for event in server.state().get('events', [])]

def events(server, name: str) -> list[dict]:
    return [event for event in server.state().get('events', []) if event['name'] == name]

def order(server) -> list[str]:
    return server.state().get('order', [])

def wait_order(server, expected: list[str], timeout: float = 10.0) -> list[str]:
    ''' 等服务端把最后一个信号也记完（响应先到、`after_request` 后到，存在毫秒级竞态） '''

    deadline = time.time() + timeout
    while time.time() < deadline:
        current = order(server)
        if current[-len(expected):] == expected:
            return current
        time.sleep(0.1)
    return order(server)

def case_lifecycle_start(t, server):
    ''' 启动阶段的信号：全部触发过，且顺序正确 '''

    triggered = names(server)

    for name in ['before_load_modules', 'after_load_modules', 'before_server_start', 'after_server_start', 'before_workers_start', 'before_worker_start', 'after_worker_start']:
        t.check(f'启动：{name} 触发过', name in triggered, f'未触发；实际触发={triggered}')

    # 取每个信号的首次触发位置，验证启动顺序
    first = {name: triggered.index(name) for name in ['before_load_modules', 'after_load_modules', 'before_server_start', 'after_server_start', 'before_workers_start', 'before_worker_start', 'after_worker_start']}
    sequence = sorted(first, key = lambda name: first[name])
    t.check('启动：触发顺序为 载入模块 → 服务器启动 → 工作进程启动', sequence == ['before_load_modules', 'after_load_modules', 'before_server_start', 'after_server_start', 'before_workers_start', 'before_worker_start', 'after_worker_start'], f'{sequence}')

    t.check('启动：before_load_modules 收到 modules 列表参数', events(server, 'before_load_modules')[0]['modules'] == [], f"{events(server, 'before_load_modules')[0]}")
    t.check('启动：before_workers_start 收到 workers 参数', events(server, 'before_workers_start')[0]['workers'] == 1, f"{events(server, 'before_workers_start')[0]}")
    t.check('启动：before_worker_start 收到 is_first 参数', events(server, 'before_worker_start')[0]['is_first'] is True, f"{events(server, 'before_worker_start')[0]}")
    t.check('启动：after_worker_start（协程处理函数）收到 is_first 参数', events(server, 'after_worker_start')[0]['is_first'] is True, f"{events(server, 'after_worker_start')[0]}")

    # 单 worker 下没有可加载的模块（tests 目录下没有带 __init__.py 的子目录）
    t.check('启动：没有可加载模块时 before_load_module / after_load_module 不触发', 'before_load_module' not in triggered and 'after_load_module' not in triggered, f'实际触发={triggered}')

    t.check('启动：before_server_start 只触发一次', len(events(server, 'before_server_start')) == 1, f'实际触发 {len(events(server, "before_server_start"))} 次')

def case_lifecycle_stop(t, server):
    ''' 停机阶段的信号：另起一个服务进程，停止后读取状态文件 '''

    from utils import Server

    stopped = Server(app = APP)
    with stopped:
        stopped.get('/health')

    triggered = names(stopped)
    for name in ['before_worker_stop', 'after_worker_stop', 'before_app_stop', 'after_app_stop']:
        t.check(f'停机：{name} 触发过', name in triggered, f'未触发；实际触发={triggered}')

    tail = [name for name in triggered if name in ('after_workers_start', 'before_worker_stop', 'after_worker_stop', 'before_app_stop', 'after_app_stop')]
    t.check('停机：after_workers_start 已在请求处理前触发，停机信号顺序为 工作进程停止 → 应用停止', tail == ['after_workers_start', 'before_worker_stop', 'after_worker_stop', 'before_app_stop', 'after_app_stop'], f'{tail}')
    t.check('停机：before_worker_stop 收到 is_first 参数', events(stopped, 'before_worker_stop')[0]['is_first'] is True, f"{events(stopped, 'before_worker_stop')[0]}")

    t.check('启动：after_workers_start 在服务开始处理请求前触发', triggered.index('after_workers_start') < triggered.index('before_request'), f'实际触发顺序：{tail}')

def case_request_order(t, server):
    ''' 请求周期信号的触发顺序 '''

    requests.get(f'{server.url}/reset', headers = CLOSE, timeout = 10)

    requests.get(f'{server.url}/probe', headers = CLOSE, timeout = 10)
    current = wait_order(server, CYCLE)
    t.check('请求周期：单个请求的信号顺序为 before_request → route → before_response → after_response → after_request', current[-len(CYCLE):] == CYCLE, f'{current}')

    requests.get(f'{server.url}/probe', headers = CLOSE, timeout = 10)
    current = wait_order(server, CYCLE * 2)
    t.check('请求周期：连续两个请求各自完整走一轮，互不交错', current[-len(CYCLE) * 2:] == CYCLE * 2, f'{current}')

def case_request_kwargs(t, server):
    ''' 请求周期信号处理函数拿到的上下文参数 '''

    requests.get(f'{server.url}/probe', headers = CLOSE, timeout = 10)
    wait_order(server, CYCLE)

    before_request = events(server, 'before_request')[-1]
    t.check('上下文：before_request 收到 addr 与 client_socket', before_request['addr'].startswith('127.0.0.1:') and before_request['socket'] == 'socket', f'{before_request}')

    after_request = events(server, 'after_request')[-1]
    t.check('上下文：after_request 收到 Request（method / path 可用）', after_request['type'] == 'Request' and after_request['method'] == 'GET' and after_request['path'] == '/probe', f'{after_request}')

    before_response = events(server, 'before_response')[-1]
    t.check('上下文：before_response 收到 Response（status / body 可用）', before_response['type'] == 'Response' and before_response['status'] == 200 and before_response['body'] == 'probe', f'{before_response}')

    after_response = events(server, 'after_response')[-1]
    t.check('上下文：after_response 收到 Response', after_response['type'] == 'Response' and after_response['status'] == 200, f'{after_response}')

def case_handler_order(t, server):
    ''' 同一个信号上的多个处理函数按注册顺序执行 '''

    server.get('/reset')
    requests.get(f'{server.url}/probe', headers = CLOSE, timeout = 10)
    wait_order(server, CYCLE)

    recorded = server.state().get('handler_order', [])
    t.check('处理函数顺序：同一信号的三个处理函数按注册顺序执行', recorded[-3:] == ['first', 'second', 'third'], f'{recorded}')

def case_handler_exception(t, server):
    '''
    信号处理函数抛异常时的表现

    `before_request` / `before_response` 抛异常 → 响应发不出去，连接被服务端关闭（客户端只会看到连接断开）；
    `after_response` / `after_request` 抛异常 → 响应已经发出，客户端正常拿到响应。
    两种情况服务进程都要继续存活。
    '''

    # before_request 抛异常：请求拿不到响应（当前实现是连接被挂住，而不是干净地关闭）
    requests.get(f'{server.url}/raise?name=before_request', headers = CLOSE, timeout = 10)
    try:
        requests.get(f'{server.url}/probe', headers = CLOSE, timeout = 4)
        before_request_outcome = 'response'
    except requests.exceptions.Timeout:
        before_request_outcome = 'timeout'
    except requests.exceptions.RequestException:
        before_request_outcome = 'closed'

    t.check('异常：before_request 抛异常时该请求拿不到响应', before_request_outcome != 'response', f'outcome={before_request_outcome}')
    t.check('异常：抛异常的处理函数执行过（开关被消费）', server.wait_state('raise_in', [], timeout = 5), f'raise_in={server.state().get("raise_in")}')
    t.check('异常：before_request 抛异常后服务仍能响应', server.get('/health') == 'ok')

    # before_response 抛异常：响应还没发出去
    requests.get(f'{server.url}/raise?name=before_response&skip=1', headers = CLOSE, timeout = 10)
    try:
        requests.get(f'{server.url}/probe', headers = CLOSE, timeout = 4)
        before_response_outcome = 'response'
    except requests.exceptions.Timeout:
        before_response_outcome = 'timeout'
    except requests.exceptions.RequestException:
        before_response_outcome = 'closed'

    t.check('异常：before_response 抛异常时该请求拿不到响应', before_response_outcome != 'response', f'outcome={before_response_outcome}')
    t.check('异常：before_response 抛异常后服务仍能响应', server.get('/health') == 'ok')

    # after_response 抛异常：响应已经发出
    requests.get(f'{server.url}/raise?name=after_response&skip=1', headers = CLOSE, timeout = 10)
    t.check('异常：after_response 抛异常时客户端仍能拿到响应', server.get('/probe') == 'probe')
    t.check('异常：after_response 抛异常后服务仍能响应', server.get('/health') == 'ok')

    # after_request 抛异常：响应已经发出
    requests.get(f'{server.url}/raise?name=after_request&skip=1', headers = CLOSE, timeout = 10)
    t.check('异常：after_request 抛异常时客户端仍能拿到响应', server.get('/probe') == 'probe')
    t.check('异常：after_request 抛异常后服务仍能响应', server.get('/health') == 'ok')

    t.check('异常：信号处理函数抛异常时连接被关闭（客户端不会无限等待）', before_request_outcome == 'closed', f'before_request 抛异常时实际 outcome={before_request_outcome}')

CASES = [
    ('启动生命周期信号', case_lifecycle_start),
    ('请求周期信号顺序', case_request_order),
    ('请求周期信号上下文参数', case_request_kwargs),
    ('同一信号多个处理函数顺序', case_handler_order),
    ('信号处理函数抛异常', case_handler_exception),
    ('停机生命周期信号', case_lifecycle_stop)
]
