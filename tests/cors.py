'''
CORS 域：简单请求 / 预检请求的跨域响应头，应用级与路由级配置

框架里 CORS 有两个入口：预检请求（`OPTIONS` + `Origin` + `Access-Control-Request-Method`）
走 `CheeseAPI/app.py` 的 `get_cors_response`（路由级配置优先、否则回退应用级），
简单请求（带 `Origin` 的普通方法）由 `attach_cors_headers` 把 CORS 头并入路由响应。
因此这里分两层验证：

1. 集成层：跨域请求（预检、简单请求）实际收到的响应头 —— 用 `requests` 直接发
2. 判定层：`CORS.get_response` 的判定结果 —— 由 `apps/cors.py` 的 `/cors/echo/*` 路由回显
'''
import requests

APP = 'apps/cors.py'

ALLOWED = 'http://allowed.example'
ROUTE = 'http://route.example'
OTHER = 'http://other.example'

def cors_headers(response) -> dict[str, str]:
    ''' 只挑出跨域相关响应头 '''
    return {key: value for key, value in response.headers.items() if key.lower().startswith('access-control-')}

def echo(server, path: str, origin: str, requested_headers: str | None = None) -> dict:
    ''' 请求 `/cors/echo/*`，拿回 `CORS.get_response` 生成的状态码与响应头 '''
    headers = {'origin': origin}
    if requested_headers is not None:
        headers['access-control-request-headers'] = requested_headers
    return requests.get(f'{server.url}{path}', headers = headers).json()

#### 集成层 ####

def case_preflight(t, server):
    ''' 预检请求：`OPTIONS` + `Origin` + `Access-Control-Request-Method` '''
    response = requests.options(f'{server.url}/cors/app-only', headers = {
        'origin': ALLOWED,
        'access-control-request-method': 'GET',
        'access-control-request-headers': 'X-App-Header'
    })
    headers = cors_headers(response)

    t.check('预检（应用级）：返回 204 并带上应用级 CORS 头', response.status_code == 204 and response.headers.get('access-control-allow-origin') == ALLOWED and response.headers.get('access-control-allow-methods') == 'GET, POST' and response.headers.get('access-control-allow-headers') == 'X-App-Header' and response.headers.get('access-control-max-age') == '600', f'status={response.status_code}, {headers}')

    response = requests.options(f'{server.url}/cors/route-level', headers = {
        'origin': ROUTE,
        'access-control-request-method': 'PATCH'
    })
    t.check('预检（路由级）：返回 204 并使用路由级 CORS 配置', response.status_code == 204 and response.headers.get('access-control-allow-origin') == ROUTE and response.headers.get('access-control-allow-methods') == 'GET, PATCH' and response.headers.get('access-control-max-age') == '99', f'status={response.status_code}, {cors_headers(response)}')

    response = requests.options(f'{server.url}/cors/missing', headers = {
        'origin': ALLOWED,
        'access-control-request-method': 'GET'
    })
    t.check('预检：路径不存在时返回 404 且无 CORS 头', response.status_code == 404 and cors_headers(response) == {}, f'status={response.status_code}, {cors_headers(response)}')

    response = requests.options(f'{server.url}/cors/app-only', headers = {'origin': ALLOWED})
    t.check('预检：缺少 access-control-request-method 时不当作预检，仍是裸 405', response.status_code == 405 and cors_headers(response) == {}, f'status={response.status_code}, {cors_headers(response)}')

def case_simple_request(t, server):
    ''' 简单请求：`GET` + `Origin` '''
    response = requests.get(f'{server.url}/cors/plain', headers = {'origin': ALLOWED})
    headers = cors_headers(response)

    t.check('简单请求：路由正常执行并返回正文', response.status_code == 200 and response.text == 'plain', f'status={response.status_code}, body={response.text!r}')
    t.check('简单请求：返回 access-control-allow-origin', response.headers.get('access-control-allow-origin') in (ALLOWED, '*'), f'{headers}')

    response = requests.get(f'{server.url}/cors/app-only', headers = {'origin': OTHER})
    t.check('简单请求：白名单外来源只拿到普通响应，不附加 CORS 头', response.status_code == 200 and cors_headers(response) == {}, f'status={response.status_code}, {cors_headers(response)}')

#### 判定层 ####

def case_logic_app(t, server):
    ''' 应用级 CORS 配置的判定结果 '''
    result = echo(server, '/cors/echo/app', ALLOWED)
    headers = result['headers']

    t.check('CORS 应用级：白名单内来源回显具体 origin', headers.get('access-control-allow-origin') == ALLOWED, headers)
    t.check('CORS 应用级：allow_methods 按配置输出', headers.get('access-control-allow-methods') == 'GET, POST', headers.get('access-control-allow-methods'))
    t.check('CORS 应用级：allow_headers 非通配时按配置输出', headers.get('access-control-allow-headers') == 'X-App-Header', headers.get('access-control-allow-headers'))
    t.check('CORS 应用级：allow_credentials 为 True 时输出 access-control-allow-credentials', headers.get('access-control-allow-credentials') == 'true', headers.get('access-control-allow-credentials'))
    t.check('CORS 应用级：expose_headers 输出到 access-control-expose-headers', headers.get('access-control-expose-headers') == 'X-Expose', headers.get('access-control-expose-headers'))
    t.check('CORS 应用级：max_age 以字符串输出', headers.get('access-control-max-age') == '600', headers.get('access-control-max-age'))
    t.check('CORS 应用级：状态码为 204', result['status'] == 204, result['status'])

    result = echo(server, '/cors/echo/app', OTHER)
    t.check('CORS 应用级：白名单外来源返回 403 且不输出任何 CORS 头', result['status'] == 403 and result['headers'] == {}, result)

    result = echo(server, '/cors/echo/app', ALLOWED, 'X-Whatever')
    t.check('CORS 应用级：allow_headers 非通配时不回显请求头', result['headers'].get('access-control-allow-headers') == 'X-App-Header', result['headers'].get('access-control-allow-headers'))

def case_logic_route(t, server):
    ''' 路由级 CORS 配置覆盖应用级 '''
    result = echo(server, '/cors/echo/route', ROUTE)
    headers = result['headers']

    t.check('CORS 路由级：白名单覆盖应用级', headers.get('access-control-allow-origin') == ROUTE, headers)
    t.check('CORS 路由级：allow_methods 覆盖应用级', headers.get('access-control-allow-methods') == 'GET, PATCH', headers.get('access-control-allow-methods'))
    t.check('CORS 路由级：allow_headers 覆盖应用级', headers.get('access-control-allow-headers') == 'X-Route-Header', headers.get('access-control-allow-headers'))
    t.check('CORS 路由级：expose_headers 覆盖应用级', headers.get('access-control-expose-headers') == 'X-Route-Expose', headers.get('access-control-expose-headers'))
    t.check('CORS 路由级：max_age 覆盖应用级', headers.get('access-control-max-age') == '99', headers.get('access-control-max-age'))
    t.check('CORS 路由级：allow_credentials=False 时不输出凭证头', 'access-control-allow-credentials' not in headers, headers)

    result = echo(server, '/cors/echo/route', ALLOWED)
    t.check('CORS 路由级：应用级白名单里的来源在路由级被拒', result['status'] == 403 and result['headers'] == {}, result)

def case_logic_wildcard(t, server):
    ''' `allow_origins=['*']` 与凭证的相互影响 '''
    result = echo(server, '/cors/echo/wildcard', OTHER)
    t.check('CORS 通配：allow_origins=["*"] 时返回 *', result['headers'].get('access-control-allow-origin') == '*', result['headers'])
    t.check('CORS 通配：allow_origins=["*"] 时默认不输出凭证头', 'access-control-allow-credentials' not in result['headers'], result['headers'])

    result = echo(server, '/cors/echo/wildcard-credentials', OTHER)
    t.check('CORS 通配：携带凭证时输出 access-control-allow-credentials', result['headers'].get('access-control-allow-credentials') == 'true', result['headers'])
    t.check('CORS 通配：携带凭证时回显具体 origin（规范禁止 * 与凭证同用）', result['headers'].get('access-control-allow-origin') == OTHER, f'{result["headers"]}')

def case_logic_any_header(t, server):
    ''' `allow_headers=['*']` 时回显请求头 '''
    result = echo(server, '/cors/echo/any-header', ALLOWED, 'X-Foo, X-Bar')
    t.check('CORS 通配请求头：回显 access-control-request-headers', result['headers'].get('access-control-allow-headers') == 'X-Foo, X-Bar', result['headers'].get('access-control-allow-headers'))

    result = echo(server, '/cors/echo/any-header', ALLOWED)
    t.check('CORS 通配请求头：未携带请求头时回退为 *', result['headers'].get('access-control-allow-headers') == '*', result['headers'].get('access-control-allow-headers'))

def case_config(t, server):
    ''' 服务端实际生效的 CORS 配置 '''
    config = requests.get(f'{server.url}/cors/config').json()

    t.check('CORS 配置：应用级 cors_allow_* 参数全部生效', config['allow_origins'] == [ALLOWED] and config['allow_methods'] == ['GET', 'POST'] and config['allow_headers'] == ['X-App-Header'] and config['allow_credentials'] is True and config['expose_headers'] == ['X-Expose'] and config['max_age'] == 600, config)

    route_level = config['route_level']
    t.check('CORS 配置：路由级参数覆盖应用级', route_level['allow_origins'] == [ROUTE] and route_level['allow_methods'] == ['GET', 'PATCH'] and route_level['allow_headers'] == ['X-Route-Header'] and route_level['allow_credentials'] is False and route_level['expose_headers'] == ['X-Route-Expose'] and route_level['max_age'] == 99, route_level)

    t.check('CORS 配置：未传 CORS 参数的路由不生成路由级配置', requests.get(f'{server.url}/cors/route-cors-none').json()['cors_is_none'] is True, '路由级 cors 应为 None')

CASES = [
    ('预检请求（OPTIONS）', case_preflight),
    ('简单请求（带 Origin）', case_simple_request),
    ('CORS 判定：应用级配置', case_logic_app),
    ('CORS 判定：路由级覆盖', case_logic_route),
    ('CORS 判定：通配来源与凭证', case_logic_wildcard),
    ('CORS 判定：allow_headers 通配', case_logic_any_header),
    ('CORS 配置生效情况', case_config)
]
