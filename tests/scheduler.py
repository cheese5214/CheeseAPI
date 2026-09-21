'''
调度器（定时任务）用例

覆盖：注册方式（装饰器 / 函数调用）、key（显式 / 自动）、`run_type` 三种执行方式、
`expected_run_num` 与 `auto_remove`、`start` / `stop` / `remove`、`timeout` 默认值。

**平台说明**：任务的实际执行依赖 `multiprocessing.Queue.qsize()`，而 macOS 未实现该方法
（调用即 `NotImplementedError`）。`SchedulerProxy.start` / `stop`、`Task.is_running`、
`task_processing` / `async_task_processing` 都用到它，因此在本机（macOS）**任务只能注册，
无法真正跑起来，也无法 stop**——这是实现缺陷，凡是需要任务运行才能验证的断言都用 `known_issue`
如实记录；一旦在支持 `qsize` 的平台（如 Linux）上跑，同样的断言会自动变成实测断言。
'''
import json, re, time

import requests

APP = 'apps/scheduler.py'

KEY_UUID = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')

UNSUPPORTED = 'macOS 未实现 multiprocessing.Queue.qsize()（SchedulerProxy.start / stop、Task.is_running、任务处理循环都依赖它），任务无法启动 / 运行 / 停止'

def query(server, path: str) -> tuple[int, str]:
    response = requests.get(f'{server.url}{path}', timeout = 10)
    return response.status_code, response.text

def tasks(server) -> dict:
    return json.loads(server.get('/tasks'))

def runs(server, name: str) -> int:
    return int(server.get(f'/runs?name={name}'))

def capable(server) -> bool:
    ''' 当前平台能否让任务真正跑起来 '''

    return server.get('/platform/qsize') == '1'

def wait_for(getter, predicate, timeout: float = 10.0):
    deadline = time.time() + timeout
    value = getter()
    while time.time() < deadline:
        if predicate(value):
            return value
        time.sleep(0.2)
        value = getter()
    return value

def blocked(t, name: str, detail: str = ''):
    ''' 整个用例都依赖任务真正运行：平台不支持时只记一条已知缺陷 '''

    t.known_issue(name, False, f'{UNSUPPORTED}｜{detail}')

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
    ''' 启动后任务应当按 interval 反复执行（线程 / 进程 / 协程三种方式） '''

    # 协程任务的启动入口 `Task.async_start` 不检查队列，天然不报错（真正执行仍依赖 qsize）
    status, key = query(server, '/task/add?name=async&interval=0.3&key=run-async')
    t.check('执行：async 任务能启动（async_start 不报错）', status == 200 and key == 'run-async', f'status={status}, body={key!r}')

    if not capable(server):
        blocked(t, '执行：线程 / 进程 / 协程任务都能按 interval 反复执行', f'当前平台 start 直接抛异常：{query(server, "/task/add?name=thread&interval=0.3&key=run-thread")[1]!r}')
        t.check('执行：三种 run_type 的任务都注册在注册表里', tasks(server).get('run-async', {}).get('run_type') == 'ASYNC', f'keys={sorted(tasks(server))}')
        return

    for name, metric in [('thread', 'thread'), ('process', 'process'), ('async', 'async')]:
        before = runs(server, metric)
        status, key = query(server, f'/task/add?name={name}&interval=0.3&key=run-{name}')
        t.check(f'执行：{name} 任务能启动（start 不报错）', status == 200 and key == f'run-{name}', f'status={status}, body={key!r}')

        value = wait_for(lambda: runs(server, metric), lambda count: count >= before + 2, timeout = 10.0)
        t.check(f'执行：{name} 任务至少执行了 2 次', value >= before + 2, f'{before} -> {value}')

        describe = tasks(server).get(f'run-{name}', {})
        t.check(f'执行：{name} 任务的 run_num 与执行次数一致', describe.get('run_num', 0) >= 2, f'{describe}')

    keys = set(tasks(server))
    t.check('执行：三种 run_type 的任务都留在注册表里', all(f'run-{name}' in keys for name in ('thread', 'process', 'async')), f'keys={sorted(keys)}')
    t.check('执行：未指定 auto_remove 的任务不会自动移除', 'run-thread' in keys and 'run-process' in keys, f'keys={sorted(keys)}')

def case_expected_run_num(t, server):
    ''' 协程任务：`expected_run_num` 到达后停止；配合 `auto_remove` 会从注册表移除 '''

    status, key = query(server, '/task/add?name=async&interval=0.3&key=once-async&expected=3&auto_remove=1')
    t.check('次数：带 expected_run_num 的协程任务能启动（async_start 不报错）', status == 200 and key == 'once-async', f'status={status}, body={key!r}')

    describe = tasks(server).get('once-async', {})
    if not capable(server):
        blocked(t, '次数：协程任务到达 expected_run_num 后停止并从注册表移除', f'{describe}')
    else:
        describe = wait_for(lambda: tasks(server).get('once-async', {}), lambda item: item.get('run_num_completed') is True, timeout = 10.0)
        wait_for(lambda: 'once-async' in tasks(server), lambda present: not present, timeout = 10.0)
        t.check('次数：到达 expected_run_num 后 run_num_completed 为 True', describe.get('run_num_completed') is True, f'{describe}')
        t.check('次数：auto_remove 生效后任务从注册表移除', 'once-async' not in tasks(server), f'keys={sorted(tasks(server))}')

    t.check('次数：未设置 expected_run_num 时 run_num_completed 恒为 False', tasks(server)['reg-passive']['run_num_completed'] is False, f"{tasks(server)['reg-passive']}")
    t.check('次数：expected_run_num 未到达时 run_num_completed 为 False', tasks(server)['type-thread']['run_num_completed'] is False, f"{tasks(server)['type-thread']}")

def case_expected_run_num_thread(t, server):
    ''' 线程任务同样应当在到达 `expected_run_num` 后停止并被移除 '''

    query(server, '/task/add?name=thread&interval=0.3&key=once-thread&expected=2&auto_remove=1')
    describe = tasks(server).get('once-thread', {})

    t.check('次数：带 expected_run_num 的线程任务已注册（run_type / expected_run_num 正确）', describe.get('run_type') == 'THREAD' and describe.get('expected_run_num') == 2 and describe.get('auto_remove') is True, f'{describe}')

    if not capable(server):
        blocked(t, '次数：线程任务到达 expected_run_num 后停止执行，auto_remove 后从注册表移除', f'start 结果={query(server, "/task/start?key=once-thread")[1]!r}')
        return

    describe = wait_for(lambda: tasks(server).get('once-thread', {}), lambda item: item.get('run_num_completed') is True, timeout = 10.0)
    wait_for(lambda: 'once-thread' in tasks(server), lambda present: not present, timeout = 10.0)
    t.check('次数：线程任务到达 expected_run_num 后 run_num_completed 为 True', describe.get('run_num_completed') is True, f'{describe}')
    t.check('次数：线程任务到达 expected_run_num 后停止执行（run_num 恰好为 2）', describe.get('run_num') == 2, f'{describe}')
    t.check('次数：线程任务 auto_remove 后从注册表移除', 'once-thread' not in tasks(server), f'keys={sorted(tasks(server))}')

def case_decorator(t, server):
    ''' 装饰器写法：注册并自动启动 '''

    status, body = query(server, '/task/decorate?interval=0.3&key=decorated')
    t.check('装饰器：注册后任务出现在注册表里', 'decorated' in tasks(server), f'keys={sorted(tasks(server))}')

    if not capable(server):
        blocked(t, '装饰器：装饰器写法会自动启动任务并持续执行', f'status={status}, body={body!r}')
        return

    t.check('装饰器：装饰器写法会自动启动任务（不报错）', status == 200 and body == 'decorated', f'status={status}, body={body!r}')
    value = wait_for(lambda: runs(server, 'thread'), lambda count: count >= 2, timeout = 10.0)
    t.check('装饰器：装饰的任务确实在执行', value >= 2, f'runs={value}')

def case_start_stop_remove(t, server):
    ''' `start` / `stop` / `remove` 的效果 '''

    status, key = query(server, '/task/add-without-start?interval=0.3&key=ctl-task')
    t.check('控制：待启动任务已注册', status == 200 and key == 'ctl-task', f'status={status}, body={key!r}')

    status, start_body = query(server, '/task/start?key=ctl-task')
    if not capable(server):
        blocked(t, '控制：start 启动任务、stop 停止运行中的任务', f'start 结果={start_body!r}')
    else:
        t.check('控制：start 能启动已注册的任务', status == 200, f'status={status}, body={start_body!r}')
        started = runs(server, 'thread')
        value = wait_for(lambda: runs(server, 'thread'), lambda count: count >= started + 2, timeout = 10.0)
        t.check('控制：start 后任务开始执行', value >= started + 2, f'{started} -> {value}')

        status, stop_body = query(server, '/task/stop?key=ctl-task')
        t.check('控制：stop 能停止运行中的任务', status == 200, f'status={status}, body={stop_body!r}')

        stopped = runs(server, 'thread')
        time.sleep(1.2)
        t.check('控制：stop 之后执行次数不再增长', runs(server, 'thread') == stopped, f'{stopped} -> {runs(server, "thread")}')

    t.check('控制：stop 不会把任务从注册表移除', 'ctl-task' in tasks(server), f'keys={sorted(tasks(server))}')

    status, body = query(server, '/task/remove?key=ctl-task')
    t.check('控制：remove 能移除任务', status == 200 and 'ctl-task' not in tasks(server), f'status={status}, body={body!r}, keys={sorted(tasks(server))}')
    t.check('控制：remove 不存在的任务不报错', query(server, '/task/remove?key=not-exists')[0] == 200)
    t.check('控制：stop 不存在的任务会报错', 'does not exist' in query(server, '/task/stop?key=not-exists')[1], f'body={query(server, "/task/stop?key=not-exists")[1]!r}')

def case_timeout(t, server):
    ''' `timeout` 默认值为 `interval_time * 2`，仅在存在 sync_server 时参与判定 '''

    t.check('timeout：未指定时默认为 interval_time * 2', tasks(server)['type-thread']['timeout'] == 60.0, f"{tasks(server)['type-thread']}")
    t.check('timeout：显式指定时按指定值保存', tasks(server)['reg-passive']['timeout'] == 2.5, f"{tasks(server)['reg-passive']}")

    status, key = query(server, '/task/add-without-start?interval=0.3&key=timeout-task&timeout=0.5')
    describe = tasks(server).get('timeout-task', {})
    t.check('timeout：短超时值同样原样保存', status == 200 and describe.get('timeout') == 0.5, f'{describe}')

    status, body = query(server, '/task/start?key=timeout-task')
    if not capable(server):
        blocked(t, 'timeout：未配置 sync_server 时短超时不会影响任务执行', f'start 结果={body!r}')
        return

    t.check('timeout：未配置 sync_server 时超时不影响任务启动', status == 200, f'status={status}, body={body!r}')
    before = runs(server, 'thread')
    value = wait_for(lambda: runs(server, 'thread'), lambda count: count >= before + 2, timeout = 10.0)
    t.check('timeout：短超时下任务仍持续执行，不会被误删', value >= before + 2 and 'timeout-task' in tasks(server), f'{before} -> {value}, keys={sorted(tasks(server))}')

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
