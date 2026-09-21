'''
响应域测试应用

把 `Response` / `FileResponse` / `RedirectResponse` 的真实行为通过路由暴露出来，
供 `tests/response.py` 断言响应头与响应体（测试侧用裸 socket 读原始响应，避免客户端库
自动解压 / 自动跟随重定向掩盖真实行为）。
'''
import datetime, os, sys
from pathlib import Path

# 服务进程以本文件路径启动，`sys.path[0]` 就是 `tests/apps/`；
# 该目录下的应用文件（如 `signal.py`）会遮蔽同名标准库模块，干扰 `multiprocessing` 等导入，
# 因此先把应用目录移出 `sys.path`（`apputils` 由 `PYTHONPATH` 提供，不受影响）
_APP_DIR = str(Path(__file__).parent)
if _APP_DIR in sys.path:
    sys.path.remove(_APP_DIR)

from apputils import capture_warnings

capture_warnings()

from CheeseAPI import CheeseAPI, File, FileResponse, Response
from CheeseAPI.response import RedirectResponse

STATIC_DIR = Path(__file__).parent.parent.parent / 'examples' / 'static'
TEXT_FILE = STATIC_DIR / 'file.txt'
JPEG_FILE = STATIC_DIR / 'file.jpeg'

# 重复性文本：压缩后体积明显变小，便于断言「确实压缩了」
COMPRESSIBLE = 'CheeseAPI 响应压缩测试内容。' * 64

# 长度恰好等于全局 compress_min_length（默认 1024）的响应体
EXACT_COMPRESSIBLE = 'a' * 1024

app = CheeseAPI(
    port = int(os.environ['CHEESE_TEST_PORT'])
)

#### 响应体类型 ####

@app.route.get('/health')
async def health(**_):
    return Response('ok')

@app.route.get('/body/dict')
async def body_dict(**_):
    return Response({'name': '番茄', 'count': 2})

@app.route.get('/body/list')
async def body_list(**_):
    return Response([1, '二', {'三': 3}])

@app.route.get('/body/str')
async def body_str(**_):
    return Response('你好，世界')

@app.route.get('/body/bytes')
async def body_bytes(**_):
    return Response(b'\x00\x01\x02\xff')

@app.route.get('/body/none')
async def body_none(**_):
    return Response()

@app.route.get('/body/async-iter')
async def body_async_iter(**_):
    '''异步可迭代对象：应当使用 chunked 传输编码'''
    return Response(async_chunks())

async def async_chunks():
    yield '第一块 '
    yield '第二块 '
    yield '第三块'

#### 状态码与响应头 ####

@app.route.get('/status/201')
async def status_201(**_):
    return Response('created', status = 201)

@app.route.get('/status/204')
async def status_204(**_):
    '''204 不应携带响应体'''
    return Response('ignored', status = 204)

@app.route.get('/headers/custom')
async def headers_custom(**_):
    '''自定义响应头：`content-type` 已设置时框架不应覆盖'''
    return Response('hello', headers = {'content-type': 'application/xml', 'x-custom': 'v1'})

@app.route.get('/headers/set-cookie-manual')
async def headers_set_cookie_manual(**_):
    '''响应头里已手动设置 `set-cookie` 时，框架不应再用 cookies 覆盖'''
    response = Response('hi', headers = {'set-cookie': 'manual=1'})
    response.set_cookie('extra', '2')
    return response

@app.route.get('/date/high-precision')
async def date_high_precision(**_):
    return Response('hi', high_precision_date = True)

#### Cookie ####

@app.route.get('/cookie/all')
async def cookie_all(**_):
    response = Response('cookie')
    response.set_cookie('session', 'abc', expires = datetime.datetime(2030, 1, 2, 3, 4, 5, tzinfo = datetime.timezone.utc), max_age = 3600, domain = 'example.com', secure = True, http_only = True)
    return response

@app.route.get('/cookie/simple')
async def cookie_simple(**_):
    response = Response('cookie')
    response.set_cookie('a', '1')
    return response

@app.route.get('/cookie/multi')
async def cookie_multi(**_):
    response = Response('cookies')
    response.set_cookie('first', '1')
    response.set_cookie('second', '2', max_age = 60)
    return response

#### 重定向 ####

@app.route.get('/redirect/301')
async def redirect_301(**_):
    return RedirectResponse('/target', status = 301)

@app.route.get('/redirect/302')
async def redirect_302(**_):
    return RedirectResponse('/target')

@app.route.get('/redirect/303')
async def redirect_303(**_):
    return RedirectResponse('/target', status = 303)

@app.route.get('/redirect/307')
async def redirect_307(**_):
    return RedirectResponse('/target', status = 307)

@app.route.get('/redirect/308')
async def redirect_308(**_):
    return RedirectResponse('/target', status = 308)

@app.route.get('/redirect/target')
async def redirect_target(**_):
    return Response('target')

#### 文件响应 ####

@app.route.get('/file/text')
async def file_text(**_):
    return FileResponse(str(TEXT_FILE))

@app.route.get('/file/text-attachment')
async def file_text_attachment(**_):
    return FileResponse(str(TEXT_FILE), preview = False)

@app.route.get('/file/jpeg')
async def file_jpeg(**_):
    return FileResponse(str(JPEG_FILE))

@app.route.get('/file/jpeg-attachment')
async def file_jpeg_attachment(**_):
    return FileResponse(str(JPEG_FILE), preview = False)

@app.route.get('/file/memory-binary')
async def file_memory_binary(**_):
    '''内存文件、不可预览类型：content-disposition 应为 attachment'''
    return FileResponse(File('数据.bin', b'\x00\x01\x02\x03binary'))

@app.route.get('/file/content-type-custom')
async def file_content_type_custom(**_):
    '''已手动设置 `content-type`：框架不应再推断'''
    return FileResponse(str(TEXT_FILE), headers = {'content-type': 'text/csv; charset=utf-8'})

@app.route.get('/file/chunked')
async def file_chunked(**_):
    '''分块传输文件响应'''
    return FileResponse(str(TEXT_FILE), transmission_type = 'CHUNKED')

@app.route.get('/file/chunked-size')
async def file_chunked_size(**_):
    '''指定分块大小'''
    return FileResponse(File('chunked.txt', COMPRESSIBLE.encode()), transmission_type = 'CHUNKED', chunked_size = 64)

@app.route.get('/file/status-201')
async def file_status_201(**_):
    return FileResponse(str(TEXT_FILE), status = 201)

#### 压缩 ####

@app.route.get('/compress/gzip')
async def compress_gzip(**_):
    return Response(COMPRESSIBLE, compress = 'gzip')

@app.route.get('/compress/deflate')
async def compress_deflate(**_):
    return Response(COMPRESSIBLE, compress = 'deflate')

@app.route.get('/compress/br')
async def compress_br(**_):
    return Response(COMPRESSIBLE, compress = 'br')

@app.route.get('/compress/zstd')
async def compress_zstd(**_):
    return Response(COMPRESSIBLE, compress = 'zstd')

@app.route.get('/compress/level-1')
async def compress_level_1(**_):
    '''指定压缩等级：等级不同，压缩后长度不同'''
    return Response(COMPRESSIBLE, compress = 'gzip', compress_level = 1)

@app.route.get('/compress/level-9')
async def compress_level_9(**_):
    return Response(COMPRESSIBLE, compress = 'gzip', compress_level = 9)

@app.route.get('/compress/forced-small')
async def compress_forced_small(**_):
    '''显式压缩 + 小于 `compress_min_length` 的响应体'''
    return Response('小响应体', compress = 'gzip')

@app.route.get('/compress/auto-small')
async def compress_auto_small(**_):
    '''自动协商 + 小于 `compress_min_length` 的响应体'''
    return Response('小响应体')

@app.route.get('/compress/auto-big')
async def compress_auto_big(**_):
    '''自动协商 + 大于 `compress_min_length` 的响应体'''
    return Response(COMPRESSIBLE)

@app.route.get('/compress/auto-exact')
async def compress_auto_exact(**_):
    '''自动协商 + 长度恰好等于 `compress_min_length` 的响应体'''
    return Response(EXACT_COMPRESSIBLE)

@app.route.get('/compress/auto-chunked')
async def compress_auto_chunked(**_):
    '''自动协商 + 异步可迭代响应体'''
    return Response(chunked_compressible())

async def chunked_compressible():
    for i in range(8):
        yield f'第 {i} 块：{COMPRESSIBLE}'

#### 异常 ####

@app.route.get('/error/raise')
async def error_raise(**_):
    raise RuntimeError('路由内的测试异常')

@app.route.get('/error/raise-async-iter')
async def error_raise_async_iter(**_):
    async def broken():
        yield 'ok'
        raise RuntimeError('生成器内的测试异常')
    return Response(broken())

if __name__ == '__main__':
    app.start()
