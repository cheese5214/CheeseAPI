'''
static（静态文件服务）功能测试

覆盖 `CheeseAPI(static_path = {...})` 映射后的：文件读取、content-type / content-disposition 推断、
404、子目录、目录索引（index.html）、二进制类型，以及路径穿越防护。

Range 请求的缺陷在 `tests/range.py` 里单独覆盖，这里不重复。
'''
import socket
from pathlib import Path

import requests

APP = 'apps/static.py'

REPO_STATIC = Path(__file__).parent.parent / 'examples' / 'static'

def raw_get(port: int, request_line: str, extra_headers: str = '') -> tuple[str, str, bytes]:
    '''
    用裸 socket 发 GET，返回 (状态行, 响应头, 响应体)

    路径穿越用例必须绕过客户端（requests/urllib3 会规范化 URL 里的 `..`），否则测不到服务端。
    '''
    sock = socket.create_connection(('127.0.0.1', port), timeout = 10)
    sock.sendall(f'GET {request_line} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n{extra_headers}\r\n'.encode())

    buffer = b''
    while True:
        try:
            chunk = sock.recv(65536)
        except Exception:
            break
        if not chunk:
            break
        buffer += chunk
    sock.close()

    head, _, body = buffer.partition(b'\r\n\r\n')
    lines = head.decode(errors = 'replace').split('\r\n')
    return (lines[0] if lines else ''), '\r\n'.join(lines[1:]), body

def status_code(status_line: str) -> int:
    parts = status_line.split(' ')
    return int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0

#### 正常读取 ####

def case_text_file(t, server):
    ''' 读取仓库里的 .txt：内容与本地一致，推断为 text/plain 并内联预览 '''
    expected = (REPO_STATIC / 'file.txt').read_bytes()
    response = requests.get(f'{server.url}/static/file.txt')

    t.check('static：.txt 返回 200', response.status_code == 200, f'status={response.status_code}')
    t.check('static：.txt 内容与磁盘文件逐字节一致', response.content == expected, f'{len(response.content)} bytes vs {len(expected)} bytes')

    content_type = response.headers.get('content-type', '')
    t.check('static：.txt 推断为 text/plain', content_type.startswith('text/plain'), repr(content_type))

    disposition = response.headers.get('content-disposition', '')
    t.check('static：可预览类型使用 inline 且带文件名', disposition.startswith('inline') and 'file.txt' in disposition, repr(disposition))

def case_image_file(t, server):
    ''' 读取 .jpeg：内容一致、推断为 image/jpeg（响应体即使被压缩，客户端解压后仍应一致） '''
    expected = (REPO_STATIC / 'file.jpeg').read_bytes()
    response = requests.get(f'{server.url}/static/file.jpeg')

    t.check('static：.jpeg 返回 200', response.status_code == 200, f'status={response.status_code}')
    t.check('static：.jpeg 内容与磁盘文件逐字节一致', response.content == expected, f'{len(response.content)} bytes vs {len(expected)} bytes')

    content_type = response.headers.get('content-type', '')
    t.check('static：.jpeg 推断为 image/jpeg', content_type.startswith('image/jpeg'), repr(content_type))

def case_missing_file(t, server):
    ''' 不存在的文件返回 404 '''
    response = requests.get(f'{server.url}/static/not-exist.txt')

    t.check('static：文件不存在返回 404', response.status_code == 404, f'status={response.status_code}')

def case_subdirectory(t, server):
    ''' 子目录内的文件可以访问 '''
    response = requests.get(f'{server.url}/extra/sub/nested.txt')

    t.check('static：子目录文件返回 200', response.status_code == 200, f'status={response.status_code}')
    t.check('static：子目录文件内容正确', response.content == b'nested-content', repr(response.content[:60]))

def case_binary_type(t, server):
    ''' 未知扩展名推断为 application/octet-stream，且不使用 inline '''
    response = requests.get(f'{server.url}/extra/data.bin')

    t.check('static：.bin 返回 200 且内容为 256 字节', response.status_code == 200 and response.content == bytes(range(256)), f'status={response.status_code}, {len(response.content)} bytes')

    content_type = response.headers.get('content-type', '')
    t.check('static：.bin 推断为 application/octet-stream', content_type.startswith('application/octet-stream'), repr(content_type))

    disposition = response.headers.get('content-disposition', '')
    t.check('static：不可预览类型使用 attachment', disposition.startswith('attachment'), repr(disposition))

#### 目录 ####

def case_directory(t, server):
    ''' 目录：有 index.html 则返回它；没有 index.html（含映射根与仓库静态目录）返回 404 '''
    slash = requests.get(f'{server.url}/extra/indexdir/')
    t.check('static：目录带 index.html（结尾 /）返回 200 且为 index.html 内容', slash.status_code == 200 and slash.content == b'<h1>index</h1>', f'status={slash.status_code}, {slash.content[:40]!r}')

    without_slash = requests.get(f'{server.url}/extra/indexdir')
    t.check('static：目录不带结尾 /（无重定向）同样返回 index.html', without_slash.status_code == 200 and without_slash.content == b'<h1>index</h1>', f'status={without_slash.status_code}, {without_slash.content[:40]!r}')

    root = requests.get(f'{server.url}/extra')
    t.check('static：映射根目录（无 index.html）返回 404', root.status_code == 404, f'status={root.status_code}')

    repo_root = requests.get(f'{server.url}/static/')
    t.check('static：仓库静态目录（无 index.html）返回 404', repo_root.status_code == 404, f'status={repo_root.status_code}')

#### 路径穿越 ####

def case_traversal_blocked(t, server):
    ''' 穿越出静态根目录的请求必须被拦下（不能读到根目录之外的文件） '''
    status_line, _, body = raw_get(server.port, '/static/../file.txt')
    t.check('static 穿越：/static/../file.txt 被拒绝（403）', status_code(status_line) == 403, f'{status_line!r}, body={body[:60]!r}')

    status_line, _, body = raw_get(server.port, '/static/../../etc/passwd')
    t.check('static 穿越：/static/../../etc/passwd 不泄漏系统文件', status_code(status_line) == 403 and b'root:' not in body, f'{status_line!r}, body={body[:60]!r}')

    status_line, _, body = raw_get(server.port, f'/extra/%2e%2e/cheeseapi_static_{server.port}_secret/secret.txt')
    t.check('static 穿越：URL 编码的 %2e%2e 未被解码，落到 404', status_code(status_line) == 404, f'{status_line!r}, body={body[:60]!r}')

    status_line, _, body = raw_get(server.port, '/static//file.txt')
    t.check('static 穿越：//前导斜杠不会让 os.path.join 丢弃静态根（返回 403 而非文件内容）', status_code(status_line) == 403, f'{status_line!r}, body={body[:60]!r}')

def case_traversal_prefix_bypass(t, server):
    '''
    前缀校验绕过：`static_path` 的兄弟目录（名字以静态根路径为前缀）本不该被访问

    `app.py` 用 `abspath(path).startswith(abspath(static_root))` 判断越界，
    前缀匹配不是路径边界匹配，兄弟目录 `/tmp/xxx_secret` 会被判为「在根内」而直接放行。
    '''
    paths = requests.get(f'{server.url}/paths').json()
    secret = paths['secret']

    relative = secret[len('/tmp/'):]
    status_line, _, body = raw_get(server.port, f'/extra/../{relative}/secret.txt')

    t.known_issue(
        'static 穿越：同名前缀的兄弟目录不可访问',
        status_code(status_line) != 200,
        f'{status_line!r}, body={body[:40]!r}（{secret} 在静态根之外，却被当作根内文件返回）'
    )

CASES = [
    ('静态文本文件', case_text_file),
    ('静态图片文件', case_image_file),
    ('不存在的文件', case_missing_file),
    ('子目录文件', case_subdirectory),
    ('二进制文件类型', case_binary_type),
    ('目录与 index.html', case_directory),
    ('路径穿越防护', case_traversal_blocked),
    ('路径穿越（前缀绕过）', case_traversal_prefix_bypass)
]
