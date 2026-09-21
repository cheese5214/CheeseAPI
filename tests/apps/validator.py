'''
validator（参数校验）测试应用

覆盖 `@validator(form_model / query_model / params_model / json_model / headers_model)`：
合法入参的类型转换与默认值、非法入参的状态码与响应体、`hide_body` 的差异，
以及校验失败时回调是否被执行。
'''
import os, sys

''' 脚本所在目录（tests/apps）会占据 `sys.path[0]`：若该目录里存在与标准库同名的模块（如 signal.py），
    标准库会被顶掉，连 `CheeseAPI` 都 import 不进来。应用依赖的 apputils 由 PYTHONPATH 提供，
    不依赖脚本目录，所以这里先把它移出 sys.path。 '''
sys.path = [path for path in sys.path if os.path.realpath(path or '.') != os.path.dirname(os.path.realpath(__file__))]

from apputils import AppState, capture_warnings

capture_warnings()

import pydantic

from CheeseAPI import CheeseAPI, Response, validator

''' 记录回调被执行的次数：校验失败时回调不应被执行 '''
STATE = AppState(called = 0)

app = CheeseAPI(port = int(os.environ['CHEESE_TEST_PORT']))

class LoginForm(pydantic.BaseModel):
    username: str = pydantic.Field(..., min_length = 3, max_length = 20)
    password: str = pydantic.Field(..., min_length = 6)

class PageParams(pydantic.BaseModel):
    page: int = pydantic.Field(1, ge = 1)

class PageQuery(pydantic.BaseModel):
    size: int = pydantic.Field(10, ge = 1, le = 100)

class ItemJson(pydantic.BaseModel):
    name: str = pydantic.Field(..., min_length = 2)
    count: int = pydantic.Field(1, ge = 0)

class AuthHeaders(pydantic.BaseModel):
    authorization: str = pydantic.Field(..., min_length = 1)

@app.route.get('/health')
async def health(**_):
    return Response('ok')

#### form_model ####

@app.route.post('/login')
@validator(form_model = LoginForm)
async def login(*, form_data: LoginForm, **_):
    STATE.inc('called')
    return Response({
        'username': form_data.username,
        'password': form_data.password,
        # 校验通过时拿到的应是 pydantic 模型实例，而不是 dict
        'type': type(form_data).__name__,
        'is_model': isinstance(form_data, pydantic.BaseModel)
    })

@app.route.post('/login-hide-body')
@validator(form_model = LoginForm, hide_body = True)
async def login_hide_body(*, form_data: LoginForm, **_):
    STATE.inc('called')
    return Response('ok')

#### query_model / params_model ####

@app.route.get('/items/<page:int>')
@validator(query_model = PageQuery, params_model = PageParams)
async def items(*, params_data: PageParams, query_data: PageQuery, **_):
    STATE.inc('called')
    return Response({
        # 路由参数与 query 都是字符串，校验后应已转换为 int
        'page': params_data.page,
        'size': query_data.size,
        'page_type': type(params_data.page).__name__,
        'size_type': type(query_data.size).__name__,
        'params_is_model': isinstance(params_data, pydantic.BaseModel),
        'query_is_model': isinstance(query_data, pydantic.BaseModel)
    })

@app.route.get('/defaults')
@validator(query_model = PageQuery)
async def defaults(*, query_data: PageQuery, **_):
    ''' 不传任何 query 参数，验证 `Field(10)` 默认值生效 '''
    return Response({'size': query_data.size})

#### json_model ####

@app.route.post('/json')
@validator(json_model = ItemJson)
async def json_route(*, json_data: ItemJson, **_):
    STATE.inc('called')
    return Response({
        'name': json_data.name,
        'count': json_data.count,
        'is_model': isinstance(json_data, pydantic.BaseModel)
    })

#### headers_model ####

@app.route.get('/headers')
@validator(headers_model = AuthHeaders)
async def headers_route(*, headers_data: AuthHeaders, **_):
    STATE.inc('called')
    return Response({'authorization': headers_data.authorization})

#### 未声明任何 model ####

@app.route.post('/no-model')
@validator()
async def no_model(*, json_data, form_data, query_data, params_data, headers_data, **_):
    ''' 未声明 model 时，各 *_data 均为 None '''
    return Response({
        'json_data': json_data is None,
        'form_data': form_data is None,
        'query_data': query_data is None,
        'params_data': params_data is None,
        'headers_data': headers_data is None
    })

@app.route.get('/called')
async def called(**_):
    ''' 回调执行计数 '''
    return Response(str(STATE.data.get('called', 0)))

@app.route.get('/reset-called')
async def reset_called(**_):
    STATE.set('called', 0)
    return Response('0')

if __name__ == '__main__':
    app.start()
