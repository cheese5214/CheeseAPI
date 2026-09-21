'''
validator（参数校验）功能测试

断言都来自实测：`@validator` 合法的入参被转换成 pydantic 模型实例（字符串转 int、默认值生效），
非法入参返回 400 + pydantic 的错误 JSON，`hide_body=True` 时只回 400 不回细节，
且**校验失败时回调不会被执行**。
'''
import json

import requests

APP = 'apps/validator.py'

def fetch(server, path: str, **kwargs):
    ''' 发一个 GET 并返回完整响应（`Server.get` 只回文本，这里需要状态码与响应头） '''
    return requests.get(f'{server.url}{path}', timeout = 10, **kwargs)

def errors_of(response) -> list[dict]:
    ''' 从校验失败响应里取出 pydantic 的错误列表 '''
    return json.loads(response.text)

def reset_called(server):
    ''' 归零服务端回调执行计数 '''
    fetch(server, '/reset-called')
    server.wait_state('called', 0)

def called(server) -> int:
    return server.state().get('called', -1)

#### form_model ####

def case_form_success(t, server):
    ''' 合法表单：200，且回调拿到的是 pydantic 模型实例 '''
    response = server.post('/login', data = {'username': 'testuser', 'password': 'securepassword'})

    t.check('form 合法：状态码 200', response.status_code == 200, f'status={response.status_code}')
    t.check('form 合法：content-type 为 application/json', response.headers.get('content-type', '').startswith('application/json'), repr(response.headers.get('content-type')))

    body = response.json()
    t.check('form 合法：字段值原样回传', body.get('username') == 'testuser' and body.get('password') == 'securepassword', repr(body))
    t.check('form 合法：form_data 是校验模型实例而非 dict', body.get('type') == 'LoginForm' and body.get('is_model') is True, repr(body))

def case_form_missing_field(t, server):
    ''' 字段缺失：400 + pydantic 的 missing 错误，且回调不执行 '''
    reset_called(server)

    response = server.post('/login', data = {'username': 'testuser'})

    t.check('form 缺 password：状态码 400', response.status_code == 400, f'status={response.status_code}')

    errors = errors_of(response)
    t.check('form 缺 password：错误列表恰好一条', isinstance(errors, list) and len(errors) == 1, repr(errors)[:300])
    t.check('form 缺 password：错误类型为 missing 且定位到 password', errors[0].get('type') == 'missing' and errors[0].get('loc') == ['password'], repr(errors[0])[:300])

    t.check('form 校验失败：回调未被执行', called(server) == 0, f'called={called(server)}')

def case_form_min_length(t, server):
    ''' min_length 不满足：400 + string_too_short，带 min_length 上下文 '''
    response = server.post('/login', data = {'username': 'ab', 'password': 'securepassword'})

    t.check('form username 过短：状态码 400', response.status_code == 400, f'status={response.status_code}')

    errors = errors_of(response)
    t.check('form username 过短：错误类型为 string_too_short 且定位到 username', errors[0].get('type') == 'string_too_short' and errors[0].get('loc') == ['username'], repr(errors[0])[:300])
    t.check('form username 过短：错误上下文带 min_length=3', (errors[0].get('ctx') or {}).get('min_length') == 3, repr(errors[0].get('ctx')))

def case_form_empty_body(t, server):
    ''' 完全不带表单：两个字段都报 missing '''
    reset_called(server)

    response = server.post('/login')

    t.check('form 无请求体：状态码 400', response.status_code == 400, f'status={response.status_code}')

    locations = sorted(error.get('loc', [None])[0] for error in errors_of(response))
    t.check('form 无请求体：username 与 password 都报缺失', locations == ['password', 'username'], repr(locations))
    t.check('form 无请求体：回调未被执行', called(server) == 0, f'called={called(server)}')

def case_form_hide_body(t, server):
    ''' hide_body=True：只回 400 不回错误细节；合法入参正常放行 '''
    response = server.post('/login-hide-body', data = {'username': 'ab', 'password': 'x'})

    t.check('hide_body：校验失败仍返回 400', response.status_code == 400, f'status={response.status_code}')
    t.check('hide_body：响应体只有状态文案，不泄漏校验细节', response.text == 'Bad Request', repr(response.text[:200]))
    t.check('hide_body：响应体不是 pydantic 错误列表', not response.text.lstrip().startswith('['), repr(response.text[:200]))

    reset_called(server)
    ok = server.post('/login-hide-body', data = {'username': 'testuser', 'password': 'securepassword'})
    t.check('hide_body：合法入参返回 200 且回调执行', ok.status_code == 200 and ok.text == 'ok' and called(server) == 1, f'status={ok.status_code}, body={ok.text!r}, called={called(server)}')

#### params_model / query_model ####

def case_params_query_success(t, server):
    ''' 路由参数与 query 校验通过：字符串已转成 int，返回模型实例 '''
    response = fetch(server, '/items/3?size=50')

    t.check('params+query 合法：状态码 200', response.status_code == 200, f'status={response.status_code}')

    body = response.json()
    t.check('params+query 合法：路由参数 page 转换为 int', body.get('page') == 3 and body.get('page_type') == 'int', repr(body))
    t.check('params+query 合法：query 参数 size 转换为 int', body.get('size') == 50 and body.get('size_type') == 'int', repr(body))
    t.check('params+query 合法：params_data / query_data 都是模型实例', body.get('params_is_model') is True and body.get('query_is_model') is True, repr(body))

def case_query_default(t, server):
    ''' 未传 query 时 `Field(10)` 默认值生效 '''
    response = fetch(server, '/items/7')

    body = response.json()
    t.check('query 默认值：不传 size 时取 Field(10) 的 10', response.status_code == 200 and body.get('size') == 10, f'status={response.status_code}, {repr(body)}')
    t.check('query 默认值：显式传值覆盖默认值', fetch(server, '/items/7?size=42').json().get('size') == 42)

def case_params_invalid(t, server):
    ''' 路由参数违反 ge 约束：400 + greater_than_equal '''
    reset_called(server)

    response = fetch(server, '/items/0?size=50')

    t.check('params 非法（page=0）：状态码 400', response.status_code == 400, f'status={response.status_code}')

    errors = errors_of(response)
    t.check('params 非法（page=0）：定位到 page 且类型为 greater_than_equal', errors[0].get('loc') == ['page'] and errors[0].get('type') == 'greater_than_equal', repr(errors[0])[:300])
    t.check('params 非法：回调未被执行', called(server) == 0, f'called={called(server)}')

def case_query_invalid(t, server):
    ''' query 违反 ge / le / int 约束：400 + 对应错误类型 '''
    reset_called(server)

    low = fetch(server, '/items/3?size=0')
    t.check('query 非法（size=0）：400 + greater_than_equal', low.status_code == 400 and errors_of(low)[0].get('type') == 'greater_than_equal', f'status={low.status_code}, {low.text[:200]}')

    high = fetch(server, '/items/3?size=101')
    t.check('query 非法（size=101）：400 + less_than_equal', high.status_code == 400 and errors_of(high)[0].get('type') == 'less_than_equal', f'status={high.status_code}, {high.text[:200]}')

    text = fetch(server, '/items/3?size=abc')
    t.check('query 非法（size=abc）：400 + int_parsing', text.status_code == 400 and errors_of(text)[0].get('type') == 'int_parsing', f'status={text.status_code}, {text.text[:200]}')

    t.check('query 校验失败：回调未被执行', called(server) == 0, f'called={called(server)}')

def case_params_not_matching_route(t, server):
    ''' 路由参数不满足 `<page:int>` 模式时不会进入该路由 '''
    response = fetch(server, '/items/abc')

    t.check('params 非 int：路由不匹配返回 404（不是 400）', response.status_code == 404, f'status={response.status_code}')

#### json_model / headers_model / 未声明 model ####

def case_json_model(t, server):
    ''' json_model：合法 body 通过，缺字段 400 '''
    ok = server.post('/json', json = {'name': 'ab', 'count': 5})
    body = ok.json()
    t.check('json 合法：200 且 json_data 为模型实例', ok.status_code == 200 and body.get('name') == 'ab' and body.get('count') == 5 and body.get('is_model') is True, f'status={ok.status_code}, {repr(body)}')

    bad = server.post('/json', json = {'count': 5})
    errors = errors_of(bad)
    t.check('json 缺 name：400 + missing 且定位到 name', bad.status_code == 400 and errors[0].get('type') == 'missing' and errors[0].get('loc') == ['name'], f'status={bad.status_code}, {bad.text[:200]}')

def case_json_invalid_syntax(t, server):
    ''' 非法 JSON 在解析阶段就被拦下：400，且不是校验器输出的错误列表 '''
    response = server.post('/json', data = 'not-a-json', headers = {'content-type': 'application/json'})

    t.check('非法 JSON：状态码 400', response.status_code == 400, f'status={response.status_code}')
    t.check('非法 JSON：由请求解析阶段拦下（响应体不是 pydantic 错误列表）', not response.text.lstrip().startswith('['), repr(response.text[:200]))

def case_headers_model(t, server):
    ''' headers_model：必填请求头缺失时 400 '''
    ok = fetch(server, '/headers', headers = {'authorization': 'Bearer token'})
    t.check('headers 合法：200 且取到请求头值', ok.status_code == 200 and ok.json().get('authorization') == 'Bearer token', f'status={ok.status_code}, {repr(ok.text[:200])}')

    bad = fetch(server, '/headers')
    errors = errors_of(bad)
    t.check('headers 缺失：400 + missing 且定位到 authorization', bad.status_code == 400 and errors[0].get('type') == 'missing' and errors[0].get('loc') == ['authorization'], f'status={bad.status_code}, {bad.text[:200]}')

def case_no_model(t, server):
    ''' 未声明任何 model 时，各 *_data 都是 None '''
    response = server.post('/no-model')

    body = response.json()
    t.check('未声明 model：各 *_data 均为 None', response.status_code == 200 and all(value is True for value in body.values()), f'status={response.status_code}, {repr(body)}')

CASES = [
    ('form 合法入参', case_form_success),
    ('form 字段缺失', case_form_missing_field),
    ('form 违反 min_length', case_form_min_length),
    ('form 无请求体', case_form_empty_body),
    ('form hide_body', case_form_hide_body),
    ('params + query 合法入参', case_params_query_success),
    ('query 默认值', case_query_default),
    ('params 违反 ge 约束', case_params_invalid),
    ('query 违反 ge/le/int 约束', case_query_invalid),
    ('params 不符合路由模式', case_params_not_matching_route),
    ('json_model 校验', case_json_model),
    ('非法 JSON 请求体', case_json_invalid_syntax),
    ('headers_model 校验', case_headers_model),
    ('未声明 model', case_no_model)
]
