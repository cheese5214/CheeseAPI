'''
CORS 域测试应用

除正常的跨域请求路由外，另有 `/cors/echo/*` 系列路由：直接调用 `CORS.get_response`
并把生成的响应头回显出来，用来观察 CORS 的判定逻辑本身
（预检请求走 `get_cors_response`：先按路径取路由级 CORS 配置，未配置则回退应用级）。
'''
import os, sys
from pathlib import Path

# 服务进程以本文件路径启动，`sys.path[0]` 就是 `tests/apps/`；
# 该目录下的应用文件会遮蔽同名标准库模块（如 `signal.py`），先把应用目录移出 `sys.path`
_APP_DIR = str(Path(__file__).parent)
if _APP_DIR in sys.path:
    sys.path.remove(_APP_DIR)

from apputils import capture_warnings

capture_warnings()

from CheeseAPI import CheeseAPI, Response
from CheeseAPI.cors import CORS

app = CheeseAPI(
    port = int(os.environ['CHEESE_TEST_PORT']),
    cors_allow_origins = ['http://allowed.example'],
    cors_allow_methods = ['GET', 'POST'],
    cors_allow_headers = ['X-App-Header'],
    cors_allow_credentials = True,
    cors_expose_headers = ['X-Expose'],
    cors_max_age = 600
)

@app.route.get('/health')
async def health(**_):
    return Response('ok')

@app.route.get('/cors/plain')
async def plain(**_):
    return Response('plain')

@app.route.get('/cors/route-level', allow_origins = ['http://route.example'], allow_methods = ['GET', 'PATCH'], allow_headers = ['X-Route-Header'], allow_credentials = False, expose_headers = ['X-Route-Expose'], max_age = 99)
async def route_level(**_):
    '''路由级 CORS 配置：应当覆盖应用级配置'''
    return Response('route-level')

@app.route.get('/cors/app-only')
async def app_only(**_):
    '''仅注册 GET：用于观察 OPTIONS 预检的走向'''
    return Response('app-only')

def echo(response: Response):
    return Response({'status': response.status, 'headers': response.headers})

@app.route.get('/cors/echo/app')
async def echo_app(*, request, **_):
    '''应用级 CORS 配置生成的响应'''
    return echo(app.cors.get_response(request))

@app.route.get('/cors/echo/route')
async def echo_route(*, request, **_):
    '''路由级 CORS 配置生成的响应'''
    route = app.route.routes['/cors/route-level']['GET']
    return echo(route['cors'].get_response(request))

@app.route.get('/cors/echo/wildcard')
async def echo_wildcard(*, request, **_):
    '''`allow_origins=['*']` 且不携带凭证'''
    return echo(CORS(allow_origins = ['*']).get_response(request))

@app.route.get('/cors/echo/wildcard-credentials')
async def echo_wildcard_credentials(*, request, **_):
    '''`allow_origins=['*']` 且携带凭证'''
    return echo(CORS(allow_origins = ['*'], allow_credentials = True).get_response(request))

@app.route.get('/cors/echo/any-header')
async def echo_any_header(*, request, **_):
    '''`allow_headers=['*']`：应回显请求的 `access-control-request-headers`'''
    return echo(CORS(allow_origins = ['http://allowed.example'], allow_headers = ['*'], allow_credentials = False).get_response(request))

@app.route.get('/cors/route-cors-none')
async def route_cors_none(**_):
    '''未传任何 CORS 参数的路由：不应生成路由级 CORS 配置'''
    return Response({'cors_is_none': app.route.routes['/cors/plain']['GET']['cors'] is None})

@app.route.get('/cors/config')
async def config(**_):
    '''服务端实际生效的应用级 CORS 配置'''
    return Response({
        'allow_origins': app.cors.allow_origins,
        'allow_methods': app.cors.allow_methods,
        'allow_headers': app.cors.allow_headers,
        'allow_credentials': app.cors.allow_credentials,
        'expose_headers': app.cors.expose_headers,
        'max_age': app.cors.max_age,
        'route_level': {
            'allow_origins': app.route.routes['/cors/route-level']['GET']['cors'].allow_origins,
            'allow_methods': app.route.routes['/cors/route-level']['GET']['cors'].allow_methods,
            'allow_headers': app.route.routes['/cors/route-level']['GET']['cors'].allow_headers,
            'allow_credentials': app.route.routes['/cors/route-level']['GET']['cors'].allow_credentials,
            'expose_headers': app.route.routes['/cors/route-level']['GET']['cors'].expose_headers,
            'max_age': app.route.routes['/cors/route-level']['GET']['cors'].max_age
        }
    })

if __name__ == '__main__':
    app.start()
