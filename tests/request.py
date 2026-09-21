'''
请求域测试：headers / query / body / json / form / files / file / cookies / ip / ranges 的解析

断言基于实测：回显路由把 `request` 各字段的真实值返回，测试侧据此断言，不照直觉臆测。
'''
import json, socket

import requests

from utils import HOST

APP = 'apps/request.py'

def raw_request(server, method: str, path: str, extra_headers: str = '', body: bytes = b'') -> tuple[int, str]:
    ''' 裸 socket 请求：构造畸形请求头等 requests 不便构造的场景 '''
    with socket.create_connection((HOST, server.port), timeout = 10) as sock:
        sock.sendall((
            f'{method} {path} HTTP/1.1\r\nHost: {HOST}:{server.port}\r\n'
            f'Content-Length: {len(body)}\r\nConnection: close\r\n{extra_headers}\r\n'
        ).encode() + body)

        data = b''
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            data += chunk

    header, _, content = data.partition(b'\r\n\r\n')
    return int(header.split(b'\r\n')[0].split(b' ')[1]), content.decode('utf-8', 'replace')

def call(server, method: str, path: str, **kwargs) -> requests.Response:
    return requests.request(method, f'{server.url}{path}', timeout = 10, **kwargs)

def snapshot(server, method: str = 'POST', path: str = '/echo', **kwargs) -> tuple[int, dict]:
    ''' 请求回显路由，返回 (状态码, 各字段快照)；响应不是 JSON 时返回空字典 '''
    response = call(server, method, path, **kwargs)
    try:
        return response.status_code, json.loads(response.text)
    except Exception:
        return response.status_code, {}

def case_headers(t, server):
    ''' 请求头 key 统一转小写，同名的原始大小写键不存在 '''
    status, data = snapshot(server, 'GET', '/echo', headers = {'X-Custom': 'Mixed', 'x-another': 'low'})
    t.check('回显路由可用', status == 200 and data.get('method') == 'GET', f'status={status} data={data}')

    headers = data.get('headers') or {}
    t.check(
        '自定义头按小写 key 存放，值原样保留',
        headers.get('x-custom') == 'Mixed' and headers.get('x-another') == 'low',
        f'headers={headers}'
    )
    t.check(
        '不保留原始大小写键（X-Custom 不存在）',
        data.get('has_original_case_key') is False and data.get('header_keys_all_lowercase') is True,
        f'headers={headers}'
    )
    t.check(
        'host / content-length 等标准头同样是小写 key',
        headers.get('host') == f'{HOST}:{server.port}',
        f'headers={headers}'
    )

def case_query(t, server):
    ''' query 解析：重复键取最后一个、URL 解码、空值丢弃 '''
    status, data = snapshot(server, 'GET', '/echo?a=1&b=%E4%B8%AD%E6%96%87&c=x+y&a=2&d=')
    t.check(
        '重复参数取最后一个、%XX 与 + 解码、空值丢弃',
        status == 200 and data.get('query') == {'a': '2', 'b': '中文', 'c': 'x y'},
        f'status={status} query={data.get("query")}'
    )
    t.check(
        'full_path 保留原始查询串',
        data.get('full_path') == '/echo?a=1&b=%E4%B8%AD%E6%96%87&c=x+y&a=2&d=',
        f'full_path={data.get("full_path")}'
    )

    status, data = snapshot(server, 'GET', '/echo')
    t.check('无查询串时 query 为空字典', status == 200 and data.get('query') == {}, f'query={data.get("query")}')

    status, data = snapshot(server, 'GET', '/echo?a=&b=')
    t.check('全部为空值时不产生键', status == 200 and data.get('query') == {}, f'query={data.get("query")}')

    status, data = snapshot(server, 'GET', '/echo?k=1&k=&k=3')
    t.check(
        '同名键中的空值被丢弃，取最后一个非空值',
        status == 200 and data.get('query') == {'k': '3'},
        f'query={data.get("query")}'
    )

def case_body_types(t, server):
    ''' body / json / form 按 content-type 分派解析 '''
    status, data = snapshot(server, 'GET', '/echo')
    t.check(
        '无 body 的 GET：body / json / form 均为 None',
        status == 200 and data.get('body') == {'type': 'NoneType', 'text': None} and data.get('json') is None and data.get('form') is None,
        f'status={status} body={data.get("body")} json={data.get("json")} form={data.get("form")}'
    )

    status, data = snapshot(server, 'POST', '/echo')
    t.check(
        'Content-Length: 0 的 POST：body 被解析成空字符串（而非 None）',
        status == 200 and data.get('body') == {'type': 'str', 'text': ''},
        f'status={status} body={data.get("body")}'
    )

    status, data = snapshot(server, 'POST', '/echo', data = b'\xe4\xb8\xad\xe6\x96\x87body')
    t.check(
        '未指定 content-type 时 body 被解码为 str',
        status == 200 and data.get('body') == {'type': 'str', 'text': '中文body'},
        f'status={status} body={data.get("body")}'
    )

    status, data = snapshot(server, 'POST', '/echo', data = 'hello', headers = {'Content-Type': 'text/plain'})
    t.check(
        'text/plain 的 body 为 str',
        status == 200 and data.get('body') == {'type': 'str', 'text': 'hello'} and data.get('json') is None,
        f'status={status} body={data.get("body")}'
    )

    status, data = snapshot(server, 'POST', '/echo', json = {'a': 1, 'b': ['x']})
    t.check(
        'application/json：body 保持 bytes 原文，json 为解析结果',
        status == 200 and data.get('body') == {'type': 'bytes', 'text': '{"a": 1, "b": ["x"]}'} and data.get('json') == {'a': 1, 'b': ['x']},
        f'status={status} body={data.get("body")} json={data.get("json")}'
    )

    status, data = snapshot(server, 'POST', '/echo', json = [1, 2, 3])
    t.check(
        'application/json 的数组体解析为 list',
        status == 200 and data.get('json') == [1, 2, 3],
        f'json={data.get("json")}'
    )

    status, data = snapshot(server, 'POST', '/echo', data = 'not-json', headers = {'Content-Type': 'application/json'})
    t.check('非法 JSON 返回 400', status == 400, f'status={status} data={data}')

    status, data = snapshot(server, 'POST', '/echo', data = '', headers = {'Content-Type': 'application/json'})
    t.check('空体的 JSON 请求返回 400（json.loads 抛错）', status == 400, f'status={status}')

    status, data = snapshot(server, 'POST', '/echo', data = '{"a": 1}', headers = {'Content-Type': 'application/json; charset=utf-8'})
    t.check(
        'content-type 带参数（application/json; charset=utf-8）仍按 JSON 解析，body 保持 bytes',
        status == 200 and data.get('json') == {'a': 1} and data.get('body') == {'type': 'bytes', 'text': '{"a": 1}'},
        f'status={status} body={data.get("body")} json={data.get("json")}'
    )

def case_form(t, server):
    ''' application/x-www-form-urlencoded 解析为 form '''
    status, data = snapshot(server, 'POST', '/echo', data = {'a': '1', 'b': '中文', 'c': 'x y'})
    t.check(
        '表单字段解码后放入 form，body 保持 bytes',
        status == 200 and data.get('form') == {'a': '1', 'b': '中文', 'c': 'x y'} and data.get('body', {}).get('type') == 'bytes',
        f'status={status} form={data.get("form")} body={data.get("body")}'
    )

    status, data = snapshot(server, 'POST', '/echo', data = 'a=1&a=2&b=x+y', headers = {'Content-Type': 'application/x-www-form-urlencoded'})
    t.check(
        '同名表单字段取第一个值（与 query 的取最后一个不同）',
        status == 200 and data.get('form') == {'a': '1', 'b': 'x y'},
        f'form={data.get("form")}'
    )

    status, data = snapshot(server, 'POST', '/echo', data = '', headers = {'Content-Type': 'application/x-www-form-urlencoded'})
    t.check(
        '空表单体解析成空字典（而非 None）',
        status == 200 and data.get('form') == {},
        f'form={data.get("form")}'
    )

def case_multipart(t, server):
    ''' multipart/form-data：文件进 files，普通字段进 form '''
    status, data = snapshot(
        server, 'POST', '/echo',
        files = {'upload': ('a.txt', b'file-bytes', 'text/plain')},
        data = {'field': 'value'}
    )
    t.check(
        '上传文件按 name 落在 files，普通字段落在 form',
        status == 200 and data.get('files') == {'upload': {'name': 'a.txt', 'data_type': 'bytes', 'text': 'file-bytes'}} and data.get('form') == {'field': 'value'},
        f'status={status} files={data.get("files")} form={data.get("form")}'
    )
    t.check(
        'multipart 请求不会填充 request.file（单数）',
        data.get('file') is None,
        f'file={data.get("file")}'
    )

    status, data = snapshot(
        server, 'POST', '/echo',
        files = [('a', ('a.txt', b'A', 'text/plain')), ('b', ('b.txt', b'B', 'text/plain'))],
        data = {'f': 'v'}
    )
    t.check(
        '多个文件字段都进 files',
        status == 200 and data.get('files') == {
            'a': {'name': 'a.txt', 'data_type': 'bytes', 'text': 'A'},
            'b': {'name': 'b.txt', 'data_type': 'bytes', 'text': 'B'}
        },
        f'files={data.get("files")}'
    )

def case_content_disposition_file(t, server):
    ''' content-disposition 请求头声明文件名时填充 request.file '''
    status, data = snapshot(
        server, 'POST', '/echo',
        data = b'raw-body',
        headers = {'Content-Disposition': 'attachment; filename="c.bin"', 'Content-Type': 'application/octet-stream'}
    )
    t.check(
        '从 content-disposition 取文件名，body 作为文件数据（bytes）',
        status == 200 and data.get('file') == {'name': 'c.bin', 'data_type': 'bytes', 'text': 'raw-body'} and data.get('files') is None,
        f'status={status} file={data.get("file")}'
    )

    status, data = snapshot(
        server, 'POST', '/echo',
        data = b'raw-body',
        headers = {'Content-Disposition': 'attachment; filename="a.txt"', 'Content-Type': 'text/plain'}
    )
    t.check(
        '文件名同样从 content-disposition 取到',
        status == 200 and (data.get('file') or {}).get('name') == 'a.txt',
        f'status={status} file={data.get("file")}'
    )
    t.check(
        'content-disposition 单文件的 File.data 为 bytes（即使 content-type 是 text/plain）',
        status == 200 and data.get('file') == {'name': 'a.txt', 'data_type': 'bytes', 'text': 'raw-body'},
        f'status={status} file={data.get("file")}'
    )

def case_cookies(t, server):
    ''' Cookie 头解析为 cookies 字典 '''
    status, data = snapshot(server, 'GET', '/echo', headers = {'Cookie': 'a=1; b=2; c=x y'})
    t.check(
        'Cookie 头按 `;` 分隔、`=` 切分，值保留空格',
        status == 200 and data.get('cookies') == {'a': '1', 'b': '2', 'c': 'x y'},
        f'status={status} cookies={data.get("cookies")}'
    )

    status, data = snapshot(server, 'GET', '/echo')
    t.check('无 Cookie 头时 cookies 为 None', status == 200 and data.get('cookies') is None, f'cookies={data.get("cookies")}')

    status, text = raw_request(server, 'GET', '/echo', extra_headers = 'Cookie: a=1; flag\r\n')
    t.check(
        '缺少 `=` 的畸形 Cookie 使请求返回 400',
        status == 400,
        f'status={status} text={text[:80]!r}'
    )

def case_ip(t, server):
    ''' ip：默认取 socket 对端地址，代理头优先 '''
    status, data = snapshot(server, 'GET', '/echo')
    t.check('默认 ip 为直连地址', status == 200 and data.get('ip') == HOST, f'ip={data.get("ip")}')

    status, data = snapshot(server, 'GET', '/echo', headers = {'X-Real-IP': '9.9.9.9'})
    t.check('x-real-ip 覆盖 ip', status == 200 and data.get('ip') == '9.9.9.9', f'ip={data.get("ip")}')

    status, data = snapshot(server, 'GET', '/echo', headers = {'X-Forwarded-For': '1.2.3.4, 5.6.7.8'})
    t.check('x-forwarded-for 取第一个地址（并去除空格）', status == 200 and data.get('ip') == '1.2.3.4', f'ip={data.get("ip")}')

def case_ranges(t, server):
    ''' Range 头解析为 ranges（左闭区间 + 可选的右端点） '''
    status, data = snapshot(server, 'GET', '/echo', headers = {'Range': 'bytes=0-99'})
    t.check('单区间两端都给出', status == 200 and data.get('ranges') == [[0, 99]], f'ranges={data.get("ranges")}')

    status, data = snapshot(server, 'GET', '/echo', headers = {'Range': 'bytes=5-'})
    t.check('区间只给起点时终点为 None', status == 200 and data.get('ranges') == [[5, None]], f'ranges={data.get("ranges")}')

    status, data = snapshot(server, 'GET', '/echo', headers = {'Range': 'bytes=0-1,3-4'})
    t.check('多区间按顺序解析', status == 200 and data.get('ranges') == [[0, 1], [3, 4]], f'ranges={data.get("ranges")}')

    status, data = snapshot(server, 'GET', '/echo')
    t.check('无 Range 头时 ranges 为 None', status == 200 and data.get('ranges') is None, f'ranges={data.get("ranges")}')

    status, data = snapshot(server, 'GET', '/echo', headers = {'Range': 'bytes='})
    t.check('`bytes=` 空 Range 解析为空列表', status == 200 and data.get('ranges') == [], f'ranges={data.get("ranges")}')

    status, data = snapshot(server, 'GET', '/echo', headers = {'Range': 'bytes=-50'})
    t.check(
        '后缀 Range（bytes=-50）解析为负起点 + 开放终点，表示末尾 50 字节',
        status == 200 and data.get('ranges') == [[-50, None]],
        f'ranges={data.get("ranges")}'
    )

    status, data = snapshot(server, 'GET', '/echo', headers = {'Range': 'bytes=0-9,-5'})
    t.check(
        '普通区间与后缀区间混用时各自正确解析',
        status == 200 and data.get('ranges') == [[0, 9], [-5, None]],
        f'ranges={data.get("ranges")}'
    )

def case_auto_recv_body(t, server):
    ''' auto_recv_body=False：不自动接收，body 为空；手动接收后可正常解析 '''
    response = call(
        server, 'POST', '/norecv',
        data = 'body-here',
        headers = {'Content-Type': 'text/plain', 'Connection': 'close'}
    )
    data = json.loads(response.text)
    t.check(
        'auto_recv_body=False 时 request.body / json / form 均为 None（即使请求带了 body）',
        response.status_code == 200 and data.get('body') == {'type': 'NoneType', 'text': None} and data.get('json') is None and data.get('form') is None,
        f'status={response.status_code} body={data.get("body")} json={data.get("json")} form={data.get("form")}'
    )
    t.check(
        '该请求头本身仍被解析（content-length 可见）',
        (data.get('headers') or {}).get('content-length') == '9',
        f'headers={data.get("headers")}'
    )

    status, data = snapshot(server, 'POST', '/manual', data = 'manual-body', headers = {'Content-Type': 'text/plain'})
    t.check(
        '手动 recv_body + parse_body 后字段可正常取得',
        status == 200 and data.get('body') == {'type': 'str', 'text': 'manual-body'} and data.get('recv_body_result') == 'True',
        f'status={status} body={data.get("body")} recv={data.get("recv_body_result")}'
    )

    t.check(
        '上述路由不产生运行时告警',
        server.warnings() == '',
        f'warnings={server.warnings()[:200]!r}'
    )

def case_malformed_headers(t, server):
    ''' 畸形请求头返回 400 '''
    status, text = raw_request(server, 'GET', '/echo', extra_headers = 'X-Bad-No-Colon\r\n')
    t.check('请求头缺少 `: ` 分隔符时返回 400', status == 400, f'status={status} text={text[:80]!r}')

    status, text = raw_request(server, 'GET', '/echo', extra_headers = 'X-Good: v\r\n')
    t.check(
        '正常请求头可被解析（对照组）',
        status == 200 and json.loads(text).get('headers', {}).get('x-good') == 'v',
        f'status={status} text={text[:120]}'
    )

def case_other_methods(t, server):
    ''' PUT / PATCH / DELETE 同样回显请求字段 '''
    for method in ('PUT', 'PATCH', 'DELETE'):
        status, data = snapshot(server, method, '/echo', data = 'p', headers = {'Content-Type': 'text/plain'})
        t.check(
            f'{method} 回显 method 与已解析的 body',
            status == 200 and data.get('method') == method and data.get('body') == {'type': 'str', 'text': 'p'},
            f'status={status} data={data}'
        )

CASES = [
    ('headers：key 统一小写', case_headers),
    ('query：重复键 / URL 解码 / 空值', case_query),
    ('body 按 content-type 解析（裸 body / text / json）', case_body_types),
    ('form：application/x-www-form-urlencoded', case_form),
    ('files：multipart/form-data 上传', case_multipart),
    ('file：content-disposition 单文件', case_content_disposition_file),
    ('cookies：Cookie 头解析', case_cookies),
    ('ip：直连地址与代理头', case_ip),
    ('ranges：Range 头解析', case_ranges),
    ('auto_recv_body=False 与手动接收', case_auto_recv_body),
    ('畸形请求头返回 400', case_malformed_headers),
    ('PUT / PATCH / DELETE 的回显', case_other_methods)
]
