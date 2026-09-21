'''
请求域测试应用：headers / query / body / json / form / files / file / cookies / ip / ranges 的解析

回显路由把 `request` 各字段的真实值以 JSON 返回，测试侧据此断言，避免凭直觉臆测。
'''
import json, os, sys
from typing import TYPE_CHECKING

''' 脚本方式启动时 `sys.path[0]` 是 `tests/apps/`，该目录下与标准库同名的文件（如 `signal.py`）
    会顶掉标准库，导致 `import CheeseAPI` 时 `multiprocessing` 导入 `signal` 失败；先把脚本目录移出 `sys.path` '''
sys.path = [path for path in sys.path if os.path.abspath(path) != os.path.dirname(os.path.abspath(__file__))]

from apputils import AppState, capture_warnings

capture_warnings()

from CheeseAPI import CheeseAPI, Response

if TYPE_CHECKING:
    from CheeseAPI.request import Request

''' 记录手动接收请求体的路由是否被命中 '''
STATE = AppState()

app = CheeseAPI(port = int(os.environ['CHEESE_TEST_PORT']))

def to_text(value: bytes | str) -> str:
    ''' bytes 按 utf-8 解码；str 原样返回（`File.data` 在部分分支里可能是 str） '''
    return value.decode('utf-8', 'replace') if isinstance(value, bytes) else value

def snapshot(request: 'Request') -> dict:
    ''' 把 `request` 各字段打包成可 JSON 序列化的结构（bytes 用 type + 文本表示） '''
    body = request.body
    if isinstance(body, bytes):
        body = {'type': 'bytes', 'text': body.decode('utf-8', 'replace')}
    else:
        body = {'type': type(body).__name__, 'text': body}

    files = None
    if request.files is not None:
        files = {
            key: {'name': item.name, 'data_type': type(item.data).__name__, 'text': to_text(item.data)}
            for key, item in request.files.items()
        }

    file = None
    if request.file is not None:
        file = {'name': request.file.name, 'data_type': type(request.file.data).__name__, 'text': to_text(request.file.data)}

    headers = request.headers or {}

    return {
        'method': request.method,
        'path': request.path,
        'full_path': request.full_path,
        'query': request.query,
        'headers': headers,
        'header_keys_all_lowercase': all(key == key.lower() for key in headers),
        'has_original_case_key': 'X-Custom' in headers,
        'body': body,
        'json': request.json,
        'form': request.form,
        'files': files,
        'file': file,
        'cookies': request.cookies,
        'ip': request.ip,
        'ranges': request.ranges
    }

@app.route.get('/echo')
async def echo_get(*, request, **_):
    return Response(json.dumps(snapshot(request), ensure_ascii = False), headers = {'content-type': 'application/json'})

@app.route.post('/echo')
async def echo_post(*, request, **_):
    return Response(json.dumps(snapshot(request), ensure_ascii = False), headers = {'content-type': 'application/json'})

@app.route.put('/echo')
async def echo_put(*, request, **_):
    return Response(json.dumps(snapshot(request), ensure_ascii = False), headers = {'content-type': 'application/json'})

@app.route.patch('/echo')
async def echo_patch(*, request, **_):
    return Response(json.dumps(snapshot(request), ensure_ascii = False), headers = {'content-type': 'application/json'})

@app.route.delete('/echo')
async def echo_delete(*, request, **_):
    return Response(json.dumps(snapshot(request), ensure_ascii = False), headers = {'content-type': 'application/json'})

@app.route.post('/norecv', auto_recv_body = False)
async def norecv(*, request, **_):
    ''' 未自动接收请求体：直接回显此刻各字段的值 '''
    STATE.inc('norecv')
    return Response(json.dumps(snapshot(request), ensure_ascii = False), headers = {'content-type': 'application/json'})

@app.route.post('/manual', auto_recv_body = False)
async def manual(*, request, **_):
    ''' 未自动接收请求体：手动接收并解析后再回显 '''
    STATE.inc('manual')
    received = await request.recv_body(True)
    await request.parse_body()
    data = snapshot(request)
    data['recv_body_result'] = str(received)
    return Response(json.dumps(data, ensure_ascii = False), headers = {'content-type': 'application/json'})

@app.route.get('/health')
async def health(**_):
    return Response('ok')

if __name__ == '__main__':
    app.start()
