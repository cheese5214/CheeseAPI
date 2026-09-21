'''
路由域测试应用：HTTP 方法注册与匹配、静态/动态路由、参数类型转换、匹配优先级

回显路由把 `request` 的真实解析结果（命中处理函数、方法、路径、参数及参数类型名）以 JSON 返回，
测试侧据此断言，避免凭直觉臆测。
'''
import json, os, re, sys
from typing import TYPE_CHECKING

''' 脚本方式启动时 `sys.path[0]` 是 `tests/apps/`，该目录下与标准库同名的文件（如 `signal.py`）
    会顶掉标准库，导致 `import CheeseAPI` 时 `multiprocessing` 导入 `signal` 失败；先把脚本目录移出 `sys.path` '''
sys.path = [path for path in sys.path if os.path.abspath(path) != os.path.dirname(os.path.abspath(__file__))]

from apputils import AppState, capture_warnings

capture_warnings()

from CheeseAPI import CheeseAPI, Response

if TYPE_CHECKING:
    from CheeseAPI.request import Request

''' 记录各处理函数的命中情况；HEAD / CONNECT 这类响应无 body，只能靠它观测 '''
STATE = AppState()

app = CheeseAPI(
    port = int(os.environ['CHEESE_TEST_PORT']),
    route_patterns = [
        {
            'key': 'email',
            'pattern': re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+'),
            'type': str,
            'weight': 10
        }
    ]
)

def echo(request: 'Request', handler: str) -> Response:
    ''' 回显路由：返回命中的处理函数名、方法、路径与参数（带真实类型名） '''
    STATE.set(f'hit_{handler}', STATE.data.get(f'hit_{handler}', 0) + 1)

    return Response(
        json.dumps({
            'handler': handler,
            'method': request.method,
            'path': request.path,
            'full_path': request.full_path,
            'params': {
                key: f'{type(value).__name__}:{value}'
                for key, value in (request.params or {}).items()
            }
        }, ensure_ascii = False),
        headers = {'content-type': 'application/json'}
    )

#### 各 HTTP 方法的注册与匹配 ####

@app.route.get('/m/get')
async def method_get(*, request, **_):
    return echo(request, 'get')

@app.route.post('/m/post')
async def method_post(*, request, **_):
    return echo(request, 'post')

@app.route.put('/m/put')
async def method_put(*, request, **_):
    return echo(request, 'put')

@app.route.patch('/m/patch')
async def method_patch(*, request, **_):
    return echo(request, 'patch')

@app.route.delete('/m/delete')
async def method_delete(*, request, **_):
    return echo(request, 'delete')

@app.route.head('/m/head')
async def method_head(*, request, **_):
    return echo(request, 'head')

@app.route.options('/m/options')
async def method_options(*, request, **_):
    return echo(request, 'options')

@app.route.trace('/m/trace')
async def method_trace(*, request, **_):
    return echo(request, 'trace')

@app.route.connect('/m/connect')
async def method_connect(*, request, **_):
    return echo(request, 'connect')

#### 同一路径注册多个方法 ####

@app.route.get('/m/multi')
async def multi_get(*, request, **_):
    return echo(request, 'multi_get')

@app.route.post('/m/multi')
async def multi_post(*, request, **_):
    return echo(request, 'multi_post')

@app.route.put('/m/multi')
async def multi_put(*, request, **_):
    return echo(request, 'multi_put')

@app.route.get('/m/only-get')
async def only_get(*, request, **_):
    return echo(request, 'only_get')

#### 动态路由：四种内置类型 ####

@app.route.get('/dyn/str/<value:str>')
async def dyn_str(*, request, **_):
    return echo(request, 'dyn_str')

@app.route.get('/dyn/int/<value:int>')
async def dyn_int(*, request, **_):
    return echo(request, 'dyn_int')

@app.route.get('/dyn/float/<value:float>')
async def dyn_float(*, request, **_):
    return echo(request, 'dyn_float')

@app.route.get('/dyn/uuid/<value:uuid>')
async def dyn_uuid(*, request, **_):
    return echo(request, 'dyn_uuid')

@app.route.get('/dyn/email/<value:email>')
async def dyn_email(*, request, **_):
    return echo(request, 'dyn_email')

@app.route.get('/dyn/two/<a:int>/<b:str>')
async def dyn_two(*, request, **_):
    return echo(request, 'dyn_two')

#### 静态路径 vs 动态路径优先级 ####

@app.route.get('/priority/fixed')
async def priority_fixed(*, request, **_):
    return echo(request, 'priority_fixed')

@app.route.get('/priority/<value:str>')
async def priority_str(*, request, **_):
    return echo(request, 'priority_str')

#### 同形状动态路由的权重（int / float / uuid 权重 5，str 权重 0） ####

@app.route.get('/weight/<value:int>')
async def weight_int(*, request, **_):
    return echo(request, 'weight_int')

@app.route.get('/weight/<value:float>')
async def weight_float(*, request, **_):
    return echo(request, 'weight_float')

@app.route.get('/weight/<value:str>')
async def weight_str(*, request, **_):
    return echo(request, 'weight_str')

#### 自定义类型（email，权重 10）与内置 str 的优先级 ####

@app.route.get('/custom/<value:email>')
async def custom_email(*, request, **_):
    return echo(request, 'custom_email')

@app.route.get('/custom/<value:str>')
async def custom_str(*, request, **_):
    return echo(request, 'custom_str')

#### 同一动态路径注册多个方法 / 动态路径的方法不匹配 ####

@app.route.get('/dyn/multi/<value:str>')
async def dyn_multi_get(*, request, **_):
    return echo(request, 'dyn_multi_get')

@app.route.post('/dyn/multi/<value:str>')
async def dyn_multi_post(*, request, **_):
    return echo(request, 'dyn_multi_post')

''' 命中权更高（int）但方法不匹配的路由；用于观测是否回退到低权重路由 '''
@app.route.post('/blocked/<value:int>')
async def blocked_int(*, request, **_):
    return echo(request, 'blocked_int')

@app.route.get('/blocked/<value:str>')
async def blocked_str(*, request, **_):
    return echo(request, 'blocked_str')

''' 多路径之间互不干扰 '''
@app.route.get('/isolate/a')
async def isolate_a(*, request, **_):
    return echo(request, 'isolate_a')

@app.route.get('/isolate/b')
async def isolate_b(*, request, **_):
    return echo(request, 'isolate_b')

@app.route.get('/health')
async def health(**_):
    return Response('ok')

if __name__ == '__main__':
    app.start()
