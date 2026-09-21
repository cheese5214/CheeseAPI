'''
调度器（定时任务）用例

覆盖：注册方式（装饰器 / 函数调用）、key（显式 / 自动）、`run_type` 三种执行方式、
`expected_run_num` 与 `auto_remove`、`start` / `stop` / `remove`、`timeout` 默认值、
任务是否在运行（`is_running`）。

任务的执行次数按 `tag` 分别计数（见 `apps/scheduler.py`）：套件里会同时存在多个常驻任务，
共用一个计数器会让断言变得不确定；`tag` 经 `args` 传给任务函数，每个任务有独立的计数。
'''
import json, re, time

import requests

APP = 'apps/scheduler.py'

KEY_UUID = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')

def query(server, path: str) -> tuple[int, str]:
    response = requests.get(f'{server.url}{path}', timeout = 10)
    return response.status_code, response.text

def tasks(server) -> dict:
    return json.loads(server.get('/tasks'))

def runs(server, name: str, tag: str | None = None) -> int:
    ''' 某个任务（`name` 执行方式 + `tag`）实际执行了多少次 '''

    return int(server.get(f'/runs?name={name}' + (f'&tag={tag}' if tag else '')))

def wait_for(getter, predicate, timeout: float = 10.0):
    deadline = time.time() + timeout
    value = getter()
    while time.time() < deadline:
        if predicate(value):
            return value
        time.sleep(0.2)
        value = getter()
    return value

def case_register(t, server):
    ''' 函数调用写法：只注册并返回 Task，不会自动启动 '''

    status, key = query(server, '/task/add-without-start?interval=0.4&key=reg-passive&expected=3&timeout=2.5')
    t.check('注册：函数调用写法返回 Task（其 key 与指定一致）', status == 200 and key == 'reg-passive', f'status={status}, body={key!r}')

    describe = json.loads(server.get('/task/get?key=reg-passive'))['describe']
    t.check('注册：显式 key 能通过 get_task 取回', describe and describe['key'] == 'reg-passive', f'{describe}')
    t.check('注册：run_type 默认为 THREAD', describe['run_type'] == 'THREAD', f"run_type={describe['run_type']!r}")
    t.check('注册：interval_time 与 expected_run_num 原样保存', describe['interval_time'] == 0.4 and describe['expected_run_num'] == 3, f'{describe}')
    t.check('注册：auto_remove 默认为 False', describe['auto_remove'] is False, f"auto_remove={describe['auto_remove']!r}")
    t.check('注册：新建任务 run_num 为 0、last_run_timer / last_run_time 为空', describe['run_num'] == 0 and describe['last_run_timer'] is None and describe['last_run_time'] is None, f'{describe}')
    t.check('注册：未启动的任务 is_running 为 False', describe['is_running'] is False, f'{describe}')

    # 只注册不启动：等待一个间隔后该任务仍然一次都没跑过
    time.sleep(1.0)
    passive = tasks(server)['reg-passive']
    t.check('注册：未调用 start 的任务不会执行', passive['run_num'] == 0 and passive['last_run_time'] is None, f'{passive}')

    t.check('注册：get_task 取不存在的 key 返回 None', json.loads(server.get('/task/get?key=not-exists'))['exists'] is False)
    duplicate = query(server, '/task/add-without-start?key=reg-passive')[1]
    t.check('注册：重复 key 注册会报错', 'already exists' in duplicate, f'body={duplicate!r}')

def case_auto_key(t, server):
    ''' 不指定 key 时自动生成 uuid 形式的 key '''

    status, key = query(server, '/task/add-without-start?interval=30')
    t.check('key：未指定 key 时自动生成 uuid', status == 200 and bool(KEY_UUID.match(key)), f'key={key!r}')

    describe = json.loads(server.get(f'/task/get?key={key}'))['describe']
    t.check('key：自动生成的 key 同样能被 get_task 取回', describe is not None and describe['key'] == key, f'{describe}')
    t.check('key：自动 key 与显式 key 是不同任务', 'reg-passive' in tasks(server) and key != 'reg-passive', f'keys={sorted(tasks(server))}')

def case_run_type(t, server):
    ''' `run_type` 三种执行方式都能注册（THREAD / PROCESS 走 add，ASYNC 走 async_add） '''

    for name, run_type in [('thread', 'THREAD'), ('process', 'PROCESS'), ('async', 'ASYNC')]:
        status, key = query(server, f'/task/add-without-start?name={name}&interval=30&key=type-{name}')
        t.check(f'run_type：{name} 能注册成功', status == 200 and key == f'type-{name}', f'status={status}, body={key!r}')

        describe = tasks(server).get(f'type-{name}')
        t.check(f'run_type：{name} 的 run_type 为 {run_type}', describe is not None and describe['run_type'] == run_type, f'{describe}')

def case_start_and_run(t, server):
    ''' 启动后任务应当按 interval 反复执行（线程 / 进程 / 协程三种方式）

    进程任务跑在 `spawn` 子进程里，父进程里的 `run_num` 是子进程自己的副本，不会回传，
    所以进程任务的「次数」只能靠任务函数自己写的记录文件（`tag`）观测；
    线程 / 协程任务与父进程同进程，额外断言注册表里的 `run_num` 与执行次数一致。
    '''

    for name, metric in [('thread', 'thread'), ('process', 'process'), ('async', 'async')]:
        status, key = query(server, f'/task/add?name={name}&interval=0.3&key=run-{name}&tag=run-{name}')
        t.check(f'执行：{name} 任务能启动（start 不报错）', status == 200 and key == f'run-{name}', f'status={status}, body={key!r}')

        value = wait_for(lambda: runs(server, metric, f'run-{name}'), lambda count: count >= 3, timeout = 10.0)
        t.check(f'执行：{name} 任务按 interval 反复执行（≥3 次）', value >= 3, f'runs={value}')

        describe = tasks(server).get(f'run-{name}', {})
        t.check(f'执行：{name} 任务的 is_running 为 True', describe.get('is_running') is True, f'{describe}')

        if name != 'process':
            describe = wait_for(lambda: tasks(server).get(f'run-{name}', {}), lambda item: item.get('run_num', 0) >= 3, timeout = 5.0)
            t.check(f'执行：{name} 任务的 run_num 与执行次数一致（≥3）', describe.get('run_num', 0) >= 3, f'{describe}')

    keys = set(tasks(server))
    t.check('执行：三种 run_type 的任务都留在注册表里', all(f'run-{name}' in keys for name in ('thread', 'process', 'async')), f'keys={sorted(keys)}')
    t.check('执行：未指定 auto_remove 的任务不会自动移除', 'run-thread' in keys and 'run-process' in keys, f'keys={sorted(keys)}')

    # 收尾：移除常驻任务，避免测试结束后还留下进程任务的子进程
    for name in ('thread', 'process', 'async'):
        query(server, f'/task/remove?key=run-{name}')

    t.check('执行：移除后任务从注册表消失', not any(f'run-{name}' in tasks(server) for name in ('thread', 'process', 'async')), f'keys={sorted(tasks(server))}')

def case_expected_run_num(t, server):
    ''' 协程任务：`expected_run_num` 到达后停止；配合 `auto_remove` 会从注册表移除 '''

    status, key = query(server, '/task/add?name=async&interval=0.3&key=once-async&expected=3&auto_remove=1&tag=once-async')
    t.check('次数：带 expected_run_num 的协程任务能启动（async_start 不报错）', status == 200 and key == 'once-async', f'status={status}, body={key!r}')

    gone = wait_for(lambda: 'once-async' in tasks(server), lambda present: not present, timeout = 10.0)
    t.check('次数：协程任务到达 expected_run_num 后 auto_remove 生效，从注册表移除', gone is False, f'keys={sorted(tasks(server))}')
    t.check('次数：协程任务到达 expected_run_num 后停止执行（恰好 3 次）', runs(server, 'async', 'once-async') == 3, f'runs={runs(server, "async", "once-async")}')

    time.sleep(0.9)
    t.check('次数：移除之后不再执行', runs(server, 'async', 'once-async') == 3, f'runs={runs(server, "async", "once-async")}')

    t.check('次数：未设置 expected_run_num 时 run_num_completed 恒为 False', tasks(server)['reg-passive']['run_num_completed'] is False, f"{tasks(server)['reg-passive']}")
    t.check('次数：expected_run_num 未到达时 run_num_completed 为 False', tasks(server)['type-thread']['run_num_completed'] is False, f"{tasks(server)['type-thread']}")

def case_expected_run_num_thread(t, server):
    ''' 线程任务同样应当在到达 `expected_run_num` 后停止执行，`auto_remove` 时从注册表移除 '''

    status, key = query(server, '/task/add?name=thread&interval=0.3&key=once-thread-stay&expected=2&tag=once-thread-stay')
    t.check('次数：线程任务能注册并启动', status == 200 and key == 'once-thread-stay', f'status={status}, body={key!r}')

    describe = wait_for(lambda: tasks(server).get('once-thread-stay', {}), lambda item: item.get('run_num_completed') is True, timeout = 10.0)
    t.check('次数：线程任务到达 expected_run_num 后 run_num_completed 为 True', describe.get('run_num_completed') is True, f'{describe}')
    t.check('次数：线程任务到达 expected_run_num 后停止执行（run_num 恰好为 2）', describe.get('run_num') == 2, f'{describe}')

    time.sleep(1.0)
    stay = tasks(server).get('once-thread-stay', {})
    t.check('次数：线程任务到达 expected_run_num 后不再执行', stay.get('run_num') == 2 and runs(server, 'thread', 'once-thread-stay') == 2, f"{stay}, runs={runs(server, 'thread', 'once-thread-stay')}")

    status, key = query(server, '/task/add?name=thread&interval=0.3&key=once-thread&expected=2&auto_remove=1&tag=once-thread')
    t.check('次数：带 auto_remove 的线程任务能注册并启动', status == 200 and key == 'once-thread', f'status={status}, body={key!r}')

    gone = wait_for(lambda: 'once-thread' in tasks(server), lambda present: not present, timeout = 10.0)
    t.check('次数：线程任务 auto_remove 后从注册表移除', gone is False, f'keys={sorted(tasks(server))}')
    t.check('次数：移除之前恰好执行了 expected_run_num 次', runs(server, 'thread', 'once-thread') == 2, f"runs={runs(server, 'thread', 'once-thread')}")

def case_decorator(t, server):
    ''' 装饰器写法：注册并自动启动 '''

    status, body = query(server, '/task/decorate?interval=0.3&key=decorated&tag=decorated')
    t.check('装饰器：注册后任务出现在注册表里', 'decorated' in tasks(server), f'keys={sorted(tasks(server))}')
    t.check('装饰器：装饰器写法会自动启动任务（不报错）', status == 200 and body == 'decorated', f'status={status}, body={body!r}')

    value = wait_for(lambda: runs(server, 'thread', 'decorated'), lambda count: count >= 3, timeout = 10.0)
    t.check('装饰器：装饰的任务确实在执行', value >= 3, f'runs={value}')

    describe = tasks(server).get('decorated', {})
    t.check('装饰器：被装饰的任务处于运行中', describe.get('is_running') is True, f'{describe}')

    query(server, '/task/remove?key=decorated')

def case_start_stop_remove(t, server):
    ''' `start` / `stop` / `remove` 的效果 '''

    status, key = query(server, '/task/add-without-start?interval=0.3&key=ctl-task&tag=ctl-task')
    t.check('控制：待启动任务已注册', status == 200 and key == 'ctl-task', f'status={status}, body={key!r}')

    describe = tasks(server).get('ctl-task', {})
    t.check('控制：未启动的任务 is_running 为 False', describe.get('is_running') is False, f'{describe}')

    status, start_body = query(server, '/task/start?key=ctl-task')
    t.check('控制：start 能启动已注册的任务', status == 200, f'status={status}, body={start_body!r}')

    started = wait_for(lambda: runs(server, 'thread', 'ctl-task'), lambda count: count >= 2, timeout = 10.0)
    t.check('控制：start 后任务开始执行', started >= 2, f'runs={started}')

    describe = tasks(server).get('ctl-task', {})
    t.check('控制：启动后 is_running 为 True', describe.get('is_running') is True, f'{describe}')

    status, stop_body = query(server, '/task/stop?key=ctl-task')
    t.check('控制：stop 能停止运行中的任务', status == 200, f'status={status}, body={stop_body!r}')

    describe = tasks(server).get('ctl-task', {})
    t.check('控制：stop 后 is_running 为 False', describe.get('is_running') is False, f'{describe}')

    stopped = runs(server, 'thread', 'ctl-task')
    time.sleep(1.2)
    t.check('控制：stop 之后执行次数不再增长', runs(server, 'thread', 'ctl-task') == stopped, f'{stopped} -> {runs(server, "thread", "ctl-task")}')

    t.check('控制：stop 不会把任务从注册表移除', 'ctl-task' in tasks(server), f'keys={sorted(tasks(server))}')

    status, body = query(server, '/task/remove?key=ctl-task')
    t.check('控制：remove 能移除任务', status == 200 and 'ctl-task' not in tasks(server), f'status={status}, body={body!r}, keys={sorted(tasks(server))}')
    t.check('控制：remove 不存在的任务不报错', query(server, '/task/remove?key=not-exists')[0] == 200)
    t.check('控制：stop 不存在的任务会报错', 'does not exist' in query(server, '/task/stop?key=not-exists')[1], f'body={query(server, "/task/stop?key=not-exists")[1]!r}')

def case_timeout(t, server):
    ''' `timeout` 默认值为 `interval_time * 2`，仅在存在 sync_server 时参与判定 '''

    t.check('timeout：未指定时默认为 interval_time * 2', tasks(server)['type-thread']['timeout'] == 60.0, f"{tasks(server)['type-thread']}")
    t.check('timeout：显式指定时按指定值保存', tasks(server)['reg-passive']['timeout'] == 2.5, f"{tasks(server)['reg-passive']}")

    status, key = query(server, '/task/add-without-start?interval=0.3&key=timeout-task&timeout=0.5&tag=timeout-task')
    describe = tasks(server).get('timeout-task', {})
    t.check('timeout：短超时值同样原样保存', status == 200 and describe.get('timeout') == 0.5, f'{describe}')

    status, body = query(server, '/task/start?key=timeout-task')
    t.check('timeout：未配置 sync_server 时超时不影响任务启动', status == 200, f'status={status}, body={body!r}')

    value = wait_for(lambda: runs(server, 'thread', 'timeout-task'), lambda count: count >= 2, timeout = 10.0)
    t.check('timeout：短超时下任务仍持续执行，不会被误删', value >= 2 and 'timeout-task' in tasks(server), f'runs={value}, keys={sorted(tasks(server))}')

    query(server, '/task/remove?key=timeout-task')

CASES = [
    ('任务注册（函数调用写法 / 显式 key）', case_register),
    ('自动生成的 key', case_auto_key),
    ('run_type 三种执行方式注册', case_run_type),
    ('三种执行方式实际运行', case_start_and_run),
    ('expected_run_num 与 auto_remove（协程任务）', case_expected_run_num),
    ('expected_run_num 与 auto_remove（线程任务）', case_expected_run_num_thread),
    ('装饰器写法', case_decorator),
    ('start / stop / remove', case_start_stop_remove),
    ('timeout', case_timeout)
]
