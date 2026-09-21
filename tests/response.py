'''
响应域：响应体类型、状态码与响应头、Cookie、重定向、文件响应、压缩

断言基于**裸 socket** 读到的原始响应（不经客户端库），
避免自动解压、自动跟随重定向把真实行为掩盖掉。
'''
import gzip, json, re, socket, zlib
from pathlib import Path

import brotli, zstandard

import CheeseAPI
from CheeseAPI.response import RedirectResponse

APP = 'apps/response.py'

COMPRESSIBLE = 'CheeseAPI 响应压缩测试内容。' * 64
''' 与 `apps/response.py` 里的同名常量一致：长度远超全局 `compress_min_length = 1024` '''

EXACT_COMPRESSIBLE = 'a' * 1024
''' 与 `apps/response.py` 里的同名常量一致：长度恰好等于全局 `compress_min_length = 1024` '''

STATIC_DIR = Path(__file__).parent.parent / 'examples' / 'static'
TEXT_FILE = STATIC_DIR / 'file.txt'
JPEG_FILE = STATIC_DIR / 'file.jpeg'

class RawResponse:
    ''' 裸 socket 拿到的原始响应 '''

    __slots__ = ('status', 'header_lines', 'body')

    def __init__(self, status: int | None, header_lines: list[str], body: bytes):
        self.status: int | None = status
        self.header_lines: list[str] = header_lines
        self.body: bytes = body

    def header(self, name: str) -> str | None:
        ''' 取某个响应头的第一个值 '''
        for line in self.header_lines:
            key, _, value = line.partition(':')
            if key.strip().lower() == name.lower():
                return value.strip()
        return None

    def all_headers(self, name: str) -> list[str]:
        ''' 取某个响应头的全部行（如多行 set-cookie） '''
        values = []
        for line in self.header_lines:
            key, _, value = line.partition(':')
            if key.strip().lower() == name.lower():
                values.append(value.strip())
        return values

def request(server, path: str, headers: dict[str, str] | None = None, method: str = 'GET') -> RawResponse:
    ''' 裸 socket 请求；`Connection: close` 保证能读到响应结束 '''
    sock = socket.create_connection(('127.0.0.1', server.port), timeout = 10)
    lines = [f'{method} {path} HTTP/1.1', f'Host: 127.0.0.1:{server.port}', 'Connection: close']
    lines.extend(f'{key}: {value}' for key, value in (headers or {}).items())
    sock.sendall(('\r\n'.join(lines) + '\r\n\r\n').encode())

    data = b''
    while True:
        chunk = sock.recv(65536)
        if not chunk:
            break
        data += chunk
    sock.close()

    head, _, body = data.partition(b'\r\n\r\n')
    head_lines = head.decode('utf-8', 'replace').split('\r\n')
    status = int(head_lines[0].split(' ')[1]) if head_lines[0].startswith('HTTP/') else None
    return RawResponse(status, head_lines[1:], body)

def chunk_size_lines(body: bytes) -> list[bytes]:
    ''' 取出分块编码里每一行的块长度（含结尾的 0） '''
    lines = []
    rest = body
    while rest:
        line, _, rest = rest.partition(b'\r\n')
        lines.append(line)
        size = int(line, 16)
        if size == 0:
            break
        rest = rest[size + 2:]
    return lines

def chunked_payload(body: bytes) -> bytes:
    ''' 按分块编码取出各块内容（容忍实现里块长度的 `0x` 前缀） '''
    payload = b''
    rest = body
    while rest:
        line, _, rest = rest.partition(b'\r\n')
        size = int(line, 16)
        if size == 0:
            break
        payload += rest[:size]
        rest = rest[size + 2:]
    return payload

def decoded(response: RawResponse) -> bytes:
    ''' 还原响应体：先拆分块编码，再按 `content-encoding` 解压 '''
    body = response.body
    if response.header('transfer-encoding') == 'chunked':
        body = chunked_payload(body)

    encoding = response.header('content-encoding')
    if encoding == 'gzip':
        return gzip.decompress(body)
    elif encoding == 'deflate':
        return zlib.decompress(body)
    elif encoding == 'br':
        return brotli.decompress(body)
    elif encoding == 'zstd':
        return zstandard.ZstdDecompressor().decompress(body)

    return body

#### 响应体类型 ####

def case_body_types(t, server):
    ''' `dict` / `list` / `str` / `bytes` / `None` 各自推断出的 content-type 与正文 '''
    response = request(server, '/body/dict')
    t.check('dict：content-type 为 application/json; charset=utf-8', response.header('content-type') == 'application/json; charset=utf-8', repr(response.header('content-type')))
    t.check('dict：正文为 JSON 序列化结果', json.loads(response.body) == {'name': '番茄', 'count': 2}, response.body.decode())
    t.check('dict：content-length 与正文长度一致', response.header('content-length') == str(len(response.body)), f'{response.header("content-length")} vs {len(response.body)}')

    response = request(server, '/body/list')
    t.check('list：content-type 为 application/json; charset=utf-8', response.header('content-type') == 'application/json; charset=utf-8', repr(response.header('content-type')))
    t.check('list：正文为 JSON 序列化结果', json.loads(response.body) == [1, '二', {'三': 3}], response.body.decode())

    response = request(server, '/body/str')
    t.check('str：content-type 为 text/plain; charset=utf-8', response.header('content-type') == 'text/plain; charset=utf-8', repr(response.header('content-type')))
    t.check('str：正文按 UTF-8 编码', response.body == '你好，世界'.encode(), repr(response.body))

    response = request(server, '/body/bytes')
    t.check('bytes：content-type 为 application/octet-stream; charset=utf-8', response.header('content-type') == 'application/octet-stream; charset=utf-8', repr(response.header('content-type')))
    t.check('bytes：字节原样返回', response.body == b'\x00\x01\x02\xff', repr(response.body))
    t.check('bytes：content-length 为 4', response.header('content-length') == '4', repr(response.header('content-length')))

    response = request(server, '/body/none')
    t.check('None：正文为状态码描述文本', response.body == b'OK', repr(response.body))
    t.check('None：content-type 为 text/plain; charset=utf-8', response.header('content-type') == 'text/plain; charset=utf-8', repr(response.header('content-type')))

def case_async_iterable(t, server):
    ''' 异步可迭代对象：自动使用分块传输编码 '''
    response = request(server, '/body/async-iter')

    t.check('异步可迭代：transfer-encoding 为 chunked', response.header('transfer-encoding') == 'chunked', repr(response.header('transfer-encoding')))
    t.check('异步可迭代：不返回 content-length', response.header('content-length') is None, repr(response.header('content-length')))
    t.check('异步可迭代：content-type 取自首块的 str 推断', response.header('content-type') == 'text/plain; charset=utf-8', repr(response.header('content-type')))
    t.check('异步可迭代：各块拼接后内容正确', chunked_payload(response.body) == '第一块 第二块 第三块'.encode(), repr(chunked_payload(response.body)))
    t.check('异步可迭代：以 0 长度块结束分块流', response.body.endswith(b'0\r\n\r\n'), repr(response.body[-12:]))

    sizes = chunk_size_lines(response.body)
    t.check('异步可迭代：块长度应为纯十六进制（RFC 7230 不允许 0x 前缀）', all(re.fullmatch(r'[0-9a-f]+', size.decode()) is not None for size in sizes), f'实际块长度行：{sizes}')

#### 状态码与响应头 ####

def case_status(t, server):
    response = request(server, '/status/201')
    t.check('status：自定义 201 被采用', response.status == 201, f'status={response.status}')
    t.check('status：201 仍返回正文', response.body == b'created', repr(response.body))

    response = request(server, '/status/204')
    t.check('status：204 不携带响应体', response.body == b'', repr(response.body))
    t.check('status：204 不返回 content-type 与 content-length', response.header('content-type') is None and response.header('content-length') is None, f'content-type={response.header("content-type")!r}, content-length={response.header("content-length")!r}')

def case_headers(t, server):
    response = request(server, '/headers/custom')
    t.check('headers：自定义 content-type 不被框架覆盖', response.header('content-type') == 'application/xml', repr(response.header('content-type')))
    t.check('headers：自定义响应头原样返回', response.header('x-custom') == 'v1', repr(response.header('x-custom')))

    response = request(server, '/headers/set-cookie-manual')
    t.check('headers：已手动设置 set-cookie 时不再附加 cookies', response.header('set-cookie') == 'manual=1', repr(response.all_headers('set-cookie')))

    response = request(server, '/date/high-precision')
    date = response.header('date') or ''
    t.check('high_precision_date：date 头带微秒', re.fullmatch(r'\w{3}, \d{2} \w{3} \d{4} \d{2}:\d{2}:\d{2}\.\d{6} GMT', date) is not None, repr(date))

#### Cookie ####

def case_cookie_attributes(t, server):
    response = request(server, '/cookie/all')
    t.check('cookie：max_age / domain / secure / http_only / expires 全部写入 set-cookie', response.header('set-cookie') == 'session=abc; Expires=Wed, 02 Jan 2030 03:04:05 GMT; Max-Age=3600; Domain=example.com; Secure; HttpOnly', repr(response.header('set-cookie')))

    response = request(server, '/cookie/simple')
    t.check('cookie：只设置 value 时不带其它属性', response.header('set-cookie') == 'a=1', repr(response.header('set-cookie')))

def case_cookie_multi(t, server):
    response = request(server, '/cookie/multi')
    set_cookie = response.all_headers('set-cookie')

    t.check('cookie：两个 cookie 的内容都出现在响应里', 'first=1' in set_cookie and 'second=2; Max-Age=60' in set_cookie, repr(set_cookie))
    t.check('cookie：多个 cookie 应写成多行 set-cookie（RFC 6265）', set_cookie == ['first=1', 'second=2; Max-Age=60'], repr(set_cookie))

#### 重定向 ####

def case_redirect(t, server):
    ''' `RedirectResponse` 各状态码：期望的状态码与 location 头 '''
    for code in (301, 302, 303, 307, 308):
        response = request(server, f'/redirect/{code}')
        t.check(
            f'重定向 {code}：返回 {code} 且 location 为 /target',
            response.status == code and response.header('location') == '/target',
            f'实际 status={response.status}，location={response.header("location")!r}'
        )

    response = request(server, '/health')
    t.check('重定向：多次重定向后服务仍存活', response.status == 200 and response.body == b'ok', f'status={response.status}, body={response.body!r}')

#### 文件响应 ####

def case_file_response(t, server):
    ''' `FileResponse` 的 content-type 与 content-disposition 推断 '''
    content = TEXT_FILE.read_bytes()

    response = request(server, '/file/text')
    t.check('文件：content-type 按扩展名推断为 text/plain', response.header('content-type') == 'text/plain; charset=utf-8', repr(response.header('content-type')))
    t.check('文件：preview=True 时为 inline', response.header('content-disposition') == 'inline; filename="file.txt"', repr(response.header('content-disposition')))
    t.check('文件：content-length 为文件大小', response.header('content-length') == str(len(content)), f'{response.header("content-length")} vs {len(content)}')
    t.check('文件：内容与磁盘文件一致', response.body == content, f'{len(response.body)} bytes')

    response = request(server, '/file/text-attachment')
    t.check('文件：preview=False 时为 attachment', response.header('content-disposition') == 'attachment; filename="file.txt"', repr(response.header('content-disposition')))

    response = request(server, '/file/jpeg')
    t.check('文件：jpeg 推断为 image/jpeg', response.header('content-type') == 'image/jpeg; charset=utf-8', repr(response.header('content-type')))
    t.check('文件：jpeg 可预览时为 inline', response.header('content-disposition') == 'inline; filename="file.jpeg"', repr(response.header('content-disposition')))

    response = request(server, '/file/jpeg-attachment')
    t.check('文件：jpeg 关闭预览时为 attachment', response.header('content-disposition') == 'attachment; filename="file.jpeg"', repr(response.header('content-disposition')))

    response = request(server, '/file/memory-binary')
    t.check('文件：内存文件（不可预览类型）推断为 octet-stream', response.header('content-type') == 'application/octet-stream; charset=utf-8', repr(response.header('content-type')))
    t.check('文件：不可预览类型即使 preview=True 也是 attachment', response.header('content-disposition') == 'attachment; filename="数据.bin"', repr(response.header('content-disposition')))
    t.check('文件：内存字节原样返回', response.body == b'\x00\x01\x02\x03binary', repr(response.body))

    response = request(server, '/file/content-type-custom')
    t.check('文件：自定义 content-type 生效且不再推断 content-disposition', response.header('content-type') == 'text/csv; charset=utf-8' and response.header('content-disposition') is None, f'content-type={response.header("content-type")!r}, content-disposition={response.header("content-disposition")!r}')

    response = request(server, '/file/status-201')
    t.check('文件：自定义 status 生效', response.status == 201 and response.body == content, f'status={response.status}, {len(response.body)} bytes')

def case_file_chunked(t, server):
    ''' `transmission_type='CHUNKED'` 的文件响应 '''
    content = TEXT_FILE.read_bytes()

    response = request(server, '/file/chunked')
    t.check('文件分块：不返回 content-length', response.header('content-length') is None, repr(response.header('content-length')))
    t.check('文件分块：完整文件内容到达客户端', chunked_payload(response.body) == content, f'{len(chunked_payload(response.body))} vs {len(content)} bytes')
    t.check('文件分块：应声明 transfer-encoding: chunked 并按分块编码发送', response.header('transfer-encoding') == 'chunked' and response.body != content, f'transfer-encoding={response.header("transfer-encoding")!r}，正文 {len(response.body)} bytes')

    response = request(server, '/file/chunked-size')
    t.check('文件分块：chunked_size=64 时全部内容都应到达客户端', chunked_payload(response.body) == COMPRESSIBLE.encode(), f'实际只到达 {len(chunked_payload(response.body))} / {len(COMPRESSIBLE.encode())} bytes')

#### 压缩 ####

def case_compress_algorithms(t, server):
    ''' `Response(compress=...)` 强制压缩：请求不携带 Accept-Encoding 也应压缩 '''
    for algorithm in ('gzip', 'deflate', 'br', 'zstd'):
        response = request(server, f'/compress/{algorithm}')
        t.check(f'压缩 {algorithm}：content-encoding 为 {algorithm}', response.header('content-encoding') == algorithm, repr(response.header('content-encoding')))
        t.check(f'压缩 {algorithm}：解压后内容与原文一致', decoded(response) == COMPRESSIBLE.encode(), f'{len(decoded(response))} bytes')
        t.check(f'压缩 {algorithm}：content-length 为压缩后长度', response.header('content-length') == str(len(response.body)), f'{response.header("content-length")} vs {len(response.body)}')
        t.check(f'压缩 {algorithm}：压缩后比原文短', len(response.body) < len(COMPRESSIBLE.encode()), f'{len(response.body)} vs {len(COMPRESSIBLE.encode())}')

def case_compress_level(t, server):
    ''' `compress_level` 影响压缩结果，但解压后内容必须一致 '''
    level_1 = request(server, '/compress/level-1')
    level_9 = request(server, '/compress/level-9')

    t.check('压缩等级：两档都解压出同一份内容', decoded(level_1) == decoded(level_9) == COMPRESSIBLE.encode(), f'{len(decoded(level_1))} vs {len(decoded(level_9))} bytes')
    t.check('压缩等级：等级 9 的压缩结果不大于等级 1', len(level_9.body) <= len(level_1.body), f'level1={len(level_1.body)} bytes, level9={len(level_9.body)} bytes')

def case_compress_negotiation(t, server):
    ''' 依据 Accept-Encoding 自动协商，受全局 `compress` 顺序与 `compress_min_length` 约束 '''
    response = request(server, '/compress/auto-big', {'accept-encoding': 'gzip'})
    t.check('自动协商：正文大于 compress_min_length 时压缩', response.header('content-encoding') == 'gzip' and decoded(response) == COMPRESSIBLE.encode(), f'content-encoding={response.header("content-encoding")!r}')

    response = request(server, '/compress/auto-small', {'accept-encoding': 'gzip'})
    t.check('自动协商：正文小于 compress_min_length 时不压缩', response.header('content-encoding') is None and response.body == '小响应体'.encode(), f'content-encoding={response.header("content-encoding")!r}')

    response = request(server, '/compress/auto-big', {'accept-encoding': 'br, gzip'})
    t.check('自动协商：不带 q 值时按全局 compress 顺序选中 gzip', response.header('content-encoding') == 'gzip', repr(response.header('content-encoding')))

    response = request(server, '/compress/auto-big', {'accept-encoding': 'br'})
    t.check('自动协商：只接受 br 时选中 br', response.header('content-encoding') == 'br' and decoded(response) == COMPRESSIBLE.encode(), repr(response.header('content-encoding')))

    response = request(server, '/compress/auto-big', {'accept-encoding': 'br;q=0.9, gzip;q=0.5'})
    t.check('自动协商：带 q 值时按 q 值降序选中 br', response.header('content-encoding') == 'br', repr(response.header('content-encoding')))

    response = request(server, '/compress/auto-big', {'accept-encoding': '*'})
    t.check('自动协商：Accept-Encoding 为 * 时选中全局首选 gzip', response.header('content-encoding') == 'gzip', repr(response.header('content-encoding')))

    response = request(server, '/compress/auto-exact', {'accept-encoding': 'gzip'})
    t.check('自动协商：正文长度恰好等于 compress_min_length 时也压缩', response.header('content-encoding') == 'gzip' and decoded(response) == EXACT_COMPRESSIBLE.encode(), f'content-encoding={response.header("content-encoding")!r}')

    response = request(server, '/compress/auto-big', {'accept-encoding': 'identity'})
    t.check('自动协商：identity 时不压缩', response.header('content-encoding') is None and response.body == COMPRESSIBLE.encode(), f'content-encoding={response.header("content-encoding")!r}')

    response = request(server, '/compress/auto-big')
    t.check('自动协商：未携带 Accept-Encoding 时不压缩', response.header('content-encoding') is None and response.body == COMPRESSIBLE.encode(), f'content-encoding={response.header("content-encoding")!r}')

    response = request(server, '/compress/auto-chunked', {'accept-encoding': 'gzip'})
    t.check('自动协商：分块响应不做压缩（无 content-length 可判断）', response.header('transfer-encoding') == 'chunked' and response.header('content-encoding') is None, f'content-encoding={response.header("content-encoding")!r}')
    t.check('自动协商：分块响应解压后内容为各块拼接', chunked_payload(response.body) == ''.join(f'第 {i} 块：{COMPRESSIBLE}' for i in range(8)).encode(), f'{len(chunked_payload(response.body))} bytes')

def case_compress_min_length_forced(t, server):
    ''' 显式 `compress` 与 `compress_min_length` 的关系 '''
    response = request(server, '/compress/forced-small', {'accept-encoding': 'gzip'})
    t.check('显式压缩：compress 指定的算法应无视 compress_min_length 生效', response.header('content-encoding') == 'gzip' and decoded(response) == '小响应体'.encode(), f'content-encoding={response.header("content-encoding")!r}，正文 {len(response.body)} bytes')

    response = request(server, '/compress/auto-big', {'accept-encoding': 'gzip;q=0'})
    t.check('自动协商：q=0 表示不可接受，不应选中 gzip', response.header('content-encoding') is None and response.body == COMPRESSIBLE.encode(), f'content-encoding={response.header("content-encoding")!r}')

#### 异常 ####

def case_error(t, server):
    ''' 路由内抛异常时返回 500，且不影响服务继续处理请求 '''
    response = request(server, '/error/raise')
    t.check('异常：返回 500', response.status == 500, f'status={response.status}')
    t.check('异常：正文为 Internal Server Error', response.body == b'Internal Server Error', repr(response.body))
    t.check('异常：content-type 为 text/plain; charset=utf-8', response.header('content-type') == 'text/plain; charset=utf-8', repr(response.header('content-type')))

    response = request(server, '/health')
    t.check('异常：后续请求仍正常处理', response.status == 200 and response.body == b'ok', f'status={response.status}, body={response.body!r}')

def case_error_async_iter(t, server):
    ''' 异步生成器中途抛异常：已发送的部分内容到达客户端 '''
    response = request(server, '/error/raise-async-iter')

    t.check('异步生成器异常：状态码与首块仍正常发送', response.status == 200 and b'ok' in response.body, f'status={response.status}, body={response.body!r}')
    t.check('异步生成器异常：应补发 0 长度块结束分块流', response.body.endswith(b'0\r\n\r\n'), f'实际正文结尾：{response.body[-12:]!r}')

def case_no_warnings(t, server):
    ''' 整个响应域跑下来不应产生运行时告警（如协程未 await） '''
    warnings = server.warnings()
    t.check('告警：响应域未产生运行时告警', warnings == '', repr(warnings))

def case_public_api(t, server):
    ''' 公开 API：响应相关类型在包顶层的导出情况 '''
    t.check('公开 API：Response 与 FileResponse 由包顶层导出', CheeseAPI.Response.__name__ == 'Response' and issubclass(CheeseAPI.FileResponse, CheeseAPI.Response), f'Response={CheeseAPI.Response!r}, FileResponse={CheeseAPI.FileResponse!r}')
    t.check('公开 API：RedirectResponse 是 Response 的子类', RedirectResponse.__mro__[1] is CheeseAPI.Response, RedirectResponse.__mro__)
    t.check('公开 API：RedirectResponse 应能从 CheeseAPI 顶层导入', CheeseAPI.RedirectResponse is RedirectResponse, repr(getattr(CheeseAPI, 'RedirectResponse', None)))

CASES = [
    ('响应体类型：dict / list / str / bytes / None', case_body_types),
    ('响应体类型：异步可迭代（分块传输）', case_async_iterable),
    ('状态码：自定义 status 与 204 无正文', case_status),
    ('响应头：自定义头、手动 set-cookie、高精度 date', case_headers),
    ('Cookie：各属性写入 set-cookie', case_cookie_attributes),
    ('Cookie：多个 cookie', case_cookie_multi),
    ('重定向：301 / 302 / 303 / 307 / 308', case_redirect),
    ('文件响应：content-type 与 content-disposition', case_file_response),
    ('文件响应：分块传输', case_file_chunked),
    ('压缩：gzip / deflate / br / zstd 强制压缩', case_compress_algorithms),
    ('压缩：compress_level 生效', case_compress_level),
    ('压缩：按 Accept-Encoding 自动协商', case_compress_negotiation),
    ('压缩：显式 compress 与 compress_min_length', case_compress_min_length_forced),
    ('异常：路由内抛异常返回 500', case_error),
    ('异常：异步生成器中途抛异常', case_error_async_iter),
    ('告警：无运行时告警', case_no_warnings),
    ('公开 API：响应类型导出情况', case_public_api)
]
