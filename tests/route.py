'''
路由域测试：HTTP 方法注册与匹配、静态/动态路由、内置与自定义类型的转换、匹配优先级

断言基于实测：回显路由把命中的处理函数、方法、路径与参数（带真实类型名）返回，
测试侧据此断言，不照直觉臆测。
'''
import json, socket

import requests

from utils import HOST

APP = 'apps/route.py'

def raw_request(server, method: str, path: str) -> tuple[int, str]:
    ''' 裸 socket 请求：CONNECT、绝对形式请求行等 requests 不便构造的场景 '''
    with socket.create_connection((HOST, server.port), timeout = 10) as sock:
        sock.sendall((
            f'{method} {path} HTTP/1.1\r\nHost: {HOST}:{server.port}\r\n'
            'Content-Length: 0\r\nConnection: close\r\n\r\n'
        ).encode())

        data = b''
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            data += chunk

    header, _, body = data.partition(b'\r\n\r\n')
    return int(header.split(b'\r\n')[0].split(b' ')[1]), body.decode('utf-8', 'replace')

def call(server, method: str, path: str, **kwargs) -> requests.Response:
    return requests.request(method, f'{server.url}{path}', timeout = 10, **kwargs)

def hit(server, method: str, path: str, **kwargs) -> tuple[int, dict]:
    ''' 请求回显路由，返回 (状态码, 回显内容)；回显不是 JSON 时返回空字典 '''
    response = call(server, method, path, **kwargs)
    try:
        return response.status_code, json.loads(response.text)
    except Exception:
        return response.status_code, {}

def case_methods(t, server):
    ''' 各 HTTP 方法注册到各自的处理函数，方法名原样透传 '''
    for method, path, handler in [
        ('GET', '/m/get', 'get'),
        ('POST', '/m/post', 'post'),
        ('PUT', '/m/put', 'put'),
        ('PATCH', '/m/patch', 'patch'),
        ('DELETE', '/m/delete', 'delete'),
        ('OPTIONS', '/m/options', 'options'),
        ('TRACE', '/m/trace', 'trace')
    ]:
        status, data = hit(server, method, path)
        t.check(
            f'{method} 命中 {handler} 处理函数',
            status == 200 and data.get('handler') == handler and data.get('method') == method,
            f'status={status} data={data}'
        )

    status, text = raw_request(server, 'CONNECT', '/m/connect')
    data = json.loads(text) if status == 200 else {}
    t.check(
        'CONNECT 命中 connect 处理函数且 method 原样透传',
        status == 200 and data.get('handler') == 'connect' and data.get('method') == 'CONNECT',
        f'status={status} text={text[:120]}'
    )

    response = call(server, 'HEAD', '/m/head')
    t.check(
        'HEAD 路由匹配成功且响应不含 body',
        response.status_code == 200 and response.text == '',
        f'status={response.status_code} body={response.text[:60]!r}'
    )
    t.check(
        'HEAD 处理函数确实被调用（响应无 body，只能靠服务端状态观察）',
        server.state().get('hit_head') == 1,
        f'state={server.state()}'
    )

def case_not_found_and_not_allowed(t, server):
    ''' 方法不匹配返回 405，路径不存在返回 404 '''
    response = call(server, 'POST', '/m/only-get')
    t.check(
        'POST 打只有 GET 的路径返回 405 且带状态说明 body',
        response.status_code == 405 and response.text == 'Method Not Allowed',
        f'status={response.status_code} body={response.text[:60]!r}'
    )

    response = call(server, 'GET', '/m/only-get')
    t.check('同一路径用注册过的方法访问正常', response.status_code == 200, f'status={response.status_code}')

    for method in ('GET', 'POST'):
        response = call(server, method, '/m/nonexistent')
        t.check(
            f'{method} 路径不存在返回 404',
            response.status_code == 404 and response.text == 'Not Found',
            f'status={response.status_code} body={response.text[:60]!r}'
        )

    response = call(server, 'HEAD', '/m/get')
    t.check(
        'HEAD 不会自动回退到同路径的 GET（返回 405）',
        response.status_code == 405,
        f'status={response.status_code}'
    )

    response = call(server, 'GET', '/m/get/')
    t.check('路径末尾多一个斜杠视为不同路径（404）', response.status_code == 404, f'status={response.status_code}')

def case_multi_methods(t, server):
    ''' 同一路径注册多个方法，各自命中自己的处理函数 '''
    for method, handler in [('GET', 'multi_get'), ('POST', 'multi_post'), ('PUT', 'multi_put')]:
        status, data = hit(server, method, '/m/multi')
        t.check(
            f'/m/multi 的 {method} 命中 {handler}',
            status == 200 and data.get('handler') == handler,
            f'status={status} data={data}'
        )

    response = call(server, 'PATCH', '/m/multi')
    t.check(
        '/m/multi 未注册的 PATCH 返回 405',
        response.status_code == 405,
        f'status={response.status_code}'
    )

def case_builtin_dynamic_types(t, server):
    ''' 四种内置动态类型的匹配与类型转换（params 里拿到的是转换后的类型） '''
    for path, handler, params in [
        ('/dyn/str/abc', 'dyn_str', {'value': 'str:abc'}),
        ('/dyn/str/123', 'dyn_str', {'value': 'str:123'}),
        ('/dyn/int/123', 'dyn_int', {'value': 'int:123'}),
        ('/dyn/int/-5', 'dyn_int', {'value': 'int:-5'}),
        ('/dyn/int/0', 'dyn_int', {'value': 'int:0'}),
        ('/dyn/float/1.5', 'dyn_float', {'value': 'float:1.5'}),
        ('/dyn/float/-0.25', 'dyn_float', {'value': 'float:-0.25'}),
        ('/dyn/uuid/550e8400-e29b-41d4-a716-446655440000', 'dyn_uuid', {'value': 'UUID:550e8400-e29b-41d4-a716-446655440000'})
    ]:
        status, data = hit(server, 'GET', path)
        t.check(
            f'{path} 命中 {handler}，params 为 {params}',
            status == 200 and data.get('handler') == handler and data.get('params') == params,
            f'status={status} data={data}'
        )

def case_dynamic_bounds(t, server):
    ''' 动态模式不匹配时的行为：不回退、直接 404 '''
    for path, expect in [
        ('/dyn/int/01', 'int 模式不允许前导零'),
        ('/dyn/int/1.5', 'int 模式不匹配小数'),
        ('/dyn/int/abc', 'int 模式不匹配非数字'),
        ('/dyn/float/5', 'float 模式要求小数点'),
        ('/dyn/uuid/abc', 'uuid 模式要求完整 uuid'),
        ('/dyn/email/plain', '自定义 email 模式不匹配时不会回退到 str')
    ]:
        status, _ = hit(server, 'GET', path)
        t.check(f'{path} 返回 404（{expect}）', status == 404, f'status={status}')

    status, data = hit(server, 'GET', '/dyn/str/a/b')
    t.check(
        'str 模式可跨 `/` 匹配',
        status == 200 and data.get('params') == {'value': 'str:a/b'},
        f'status={status} data={data}'
    )

def case_multi_params(t, server):
    ''' 一个动态路由中的多个参数按位置依次转换 '''
    status, data = hit(server, 'GET', '/dyn/two/7/hello')
    t.check(
        '两个参数分别按 int / str 转换',
        status == 200 and data.get('handler') == 'dyn_two' and data.get('params') == {'a': 'int:7', 'b': 'str:hello'},
        f'status={status} data={data}'
    )

    status, data = hit(server, 'GET', '/dyn/two/7/a/b')
    t.check(
        'str 参数贪婪吃下剩余路径',
        status == 200 and data.get('params') == {'a': 'int:7', 'b': 'str:a/b'},
        f'status={status} data={data}'
    )

    status, _ = hit(server, 'GET', '/dyn/two/x/hello')
    t.check('int 参数不匹配时整个路由不匹配（404）', status == 404, f'status={status}')

def case_custom_pattern(t, server):
    ''' 自定义类型 email（权重 10）优先于内置 str（权重 0） '''
    status, data = hit(server, 'GET', '/custom/a@b.com')
    t.check(
        '邮箱路径命中自定义 email 路由',
        status == 200 and data.get('handler') == 'custom_email' and data.get('params') == {'value': 'str:a@b.com'},
        f'status={status} data={data}'
    )

    status, data = hit(server, 'GET', '/custom/abc')
    t.check(
        '非邮箱路径回落到内置 str 路由',
        status == 200 and data.get('handler') == 'custom_str' and data.get('params') == {'value': 'str:abc'},
        f'status={status} data={data}'
    )

def case_static_over_dynamic(t, server):
    ''' 静态路径优先于动态路径 '''
    status, data = hit(server, 'GET', '/priority/fixed')
    t.check(
        '静态路径命中静态处理函数且 params 为空字典',
        status == 200 and data.get('handler') == 'priority_fixed' and data.get('params') == {},
        f'status={status} data={data}'
    )

    status, data = hit(server, 'GET', '/priority/other')
    t.check(
        '其它值命中动态路由',
        status == 200 and data.get('handler') == 'priority_str' and data.get('params') == {'value': 'str:other'},
        f'status={status} data={data}'
    )

    response = call(server, 'POST', '/priority/fixed')
    t.check(
        '静态路径命中后不再回退到动态路由（POST 返回 405）',
        response.status_code == 405,
        f'status={response.status_code}'
    )

def case_weight_order(t, server):
    ''' 同形状动态路由按权重排序：int / float（权重 5）先于 str（权重 0） '''
    for path, handler, params in [
        ('/weight/12', 'weight_int', {'value': 'int:12'}),
        ('/weight/1.5', 'weight_float', {'value': 'float:1.5'}),
        ('/weight/abc', 'weight_str', {'value': 'str:abc'})
    ]:
        status, data = hit(server, 'GET', path)
        t.check(
            f'{path} 命中 {handler}',
            status == 200 and data.get('handler') == handler and data.get('params') == params,
            f'status={status} data={data}'
        )

def case_weight_no_fallback(t, server):
    ''' 高权重动态路由匹配上但方法不匹配时，不会继续尝试低权重路由 '''
    status, data = hit(server, 'GET', '/blocked/abc')
    t.check(
        'GET /blocked/abc 命中 str 路由',
        status == 200 and data.get('handler') == 'blocked_str',
        f'status={status} data={data}'
    )

    response = call(server, 'GET', '/blocked/123')
    t.check(
        'GET /blocked/123 因命中 int 路由（仅注册 POST）而 405，不回落 str 路由',
        response.status_code == 405,
        f'status={response.status_code}'
    )

    status, data = hit(server, 'POST', '/blocked/123')
    t.check(
        'POST /blocked/123 命中 int 路由',
        status == 200 and data.get('handler') == 'blocked_int' and data.get('params') == {'value': 'int:123'},
        f'status={status} data={data}'
    )

def case_dynamic_multi_methods(t, server):
    ''' 同一动态路径注册多个方法 '''
    for method, handler in [('GET', 'dyn_multi_get'), ('POST', 'dyn_multi_post')]:
        status, data = hit(server, method, '/dyn/multi/x')
        t.check(
            f'/dyn/multi/x 的 {method} 命中 {handler}',
            status == 200 and data.get('handler') == handler and data.get('params') == {'value': 'str:x'},
            f'status={status} data={data}'
        )

    response = call(server, 'PUT', '/dyn/multi/x')
    t.check('/dyn/multi/x 未注册的 PUT 返回 405', response.status_code == 405, f'status={response.status_code}')

def case_path_and_full_path(t, server):
    ''' request.path 不含查询串，full_path 原样保留请求行中的目标 '''
    status, data = hit(server, 'GET', '/m/get?x=1')
    t.check(
        '带查询串时 path 不含 `?`，full_path 保留完整目标',
        status == 200 and data.get('path') == '/m/get' and data.get('full_path') == '/m/get?x=1',
        f'status={status} data={data}'
    )

    status, data = hit(server, 'GET', '/dyn/int/5')
    t.check(
        '动态路由中 path / full_path 为原始路径，params 已转换',
        status == 200 and data.get('path') == '/dyn/int/5' and data.get('full_path') == '/dyn/int/5' and data.get('params') == {'value': 'int:5'},
        f'status={status} data={data}'
    )

    status, text = raw_request(server, 'GET', '//m/get')
    data = json.loads(text) if status == 200 else {}
    t.check(
        '请求行以 `//` 开头时会去掉一个斜杠',
        status == 200 and data.get('path') == '/m/get' and data.get('full_path') == '/m/get',
        f'status={status} text={text[:120]}'
    )

    status, text = raw_request(server, 'GET', f'http://{HOST}:{server.port}/m/get')
    data = json.loads(text) if status == 200 else {}
    t.check(
        '绝对形式请求行：path 取值路径部分，full_path 保留完整 URL',
        status == 200 and data.get('path') == '/m/get' and data.get('full_path') == f'http://{HOST}:{server.port}/m/get',
        f'status={status} text={text[:160]}'
    )

def case_path_not_url_decoded(t, server):
    ''' 匹配用的路径不做 URL 解码，但动态参数会解码 '''
    status, data = hit(server, 'GET', '/dyn/str/a%20b')
    t.check(
        '动态参数做 URL 解码',
        status == 200 and data.get('params') == {'value': 'str:a b'} and data.get('path') == '/dyn/str/a%20b',
        f'status={status} data={data}'
    )

    status, text = raw_request(server, 'GET', '/m/%67et')
    t.check(
        '静态路径按原始路径匹配（%67 不解码，404）',
        status == 404,
        f'status={status} text={text[:80]}'
    )

def case_no_interference(t, server):
    ''' 多路径之间互不干扰 '''
    for path, handler in [('/isolate/a', 'isolate_a'), ('/isolate/b', 'isolate_b')]:
        status, data = hit(server, 'GET', path)
        t.check(
            f'{path} 命中 {handler}',
            status == 200 and data.get('handler') == handler and data.get('params') == {},
            f'status={status} data={data}'
        )

    response = call(server, 'GET', '/isolate/c')
    t.check('未注册的兄弟路径返回 404', response.status_code == 404, f'status={response.status_code}')

CASES = [
    ('各 HTTP 方法的注册与匹配', case_methods),
    ('方法不匹配 405 / 路径不存在 404', case_not_found_and_not_allowed),
    ('同一路径注册多方法', case_multi_methods),
    ('四种内置动态类型的匹配与类型转换', case_builtin_dynamic_types),
    ('动态模式的边界（前导零 / 小数 / 非数字 / 跨斜杠）', case_dynamic_bounds),
    ('多参数动态路由', case_multi_params),
    ('自定义类型与内置类型的优先级', case_custom_pattern),
    ('静态路径优先于动态路径', case_static_over_dynamic),
    ('动态路由权重排序', case_weight_order),
    ('高权重路由方法不匹配时不回落', case_weight_no_fallback),
    ('动态路径注册多方法', case_dynamic_multi_methods),
    ('request.path / full_path 的取值', case_path_and_full_path),
    ('路径匹配不做 URL 解码、参数会解码', case_path_not_url_decoded),
    ('多路径互不干扰', case_no_interference)
]
