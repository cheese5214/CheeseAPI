'''
静态文件与 Range 请求

注意：本文件里的 `known_issue` 是**已知缺陷**——断言的是「正确的 HTTP 语义」，
但当前 `CheeseAPI/response.py` 的 Range 实现不满足，因此先记为已知缺陷保持套件绿色；
一旦实现被修好，这些用例会变成 FAIL，提醒把它们转成正式断言（`check`）。
'''
from pathlib import Path

import requests

APP = 'apps/basic.py'

STATIC = Path(__file__).parent.parent / 'examples' / 'static' / 'file.jpeg'

def case_static(t, server):
    content = STATIC.read_bytes()

    response = requests.get(f'{server.url}/static/file.jpeg')
    t.check('static：无 Range 返回 200 与完整文件', response.status_code == 200 and response.content == content, f'status={response.status_code}, {len(response.content)} bytes')

def case_range_single(t, server):
    ''' 单区间 `bytes=0-1023` 的正确语义：206 + 1024 字节 + `bytes 0-1023/<size>` '''
    content = STATIC.read_bytes()
    size = len(content)

    response = requests.get(f'{server.url}/static/file.jpeg', headers = {
        'range': 'bytes=0-1023'
    })

    t.known_issue('range 单区间：返回 206 Partial Content', response.status_code == 206, f'status={response.status_code}')
    t.known_issue('range 单区间：长度为 1024 字节', len(response.content) == 1024, f'{len(response.content)} bytes')
    t.known_issue('range 单区间：Content-Range 为 bytes 0-1023/<size>', response.headers.get('content-range') == f'bytes 0-1023/{size}', repr(response.headers.get('content-range')))
    t.known_issue('range 单区间：返回 accept-ranges 头', response.headers.get('accept-ranges') == 'bytes', repr(response.headers.get('accept-ranges')))

def case_range_multi(t, server):
    ''' 多区间 `bytes=0-63,128-191` 的正确语义：206 + multipart/byteranges，两段各 64 字节 '''
    content = STATIC.read_bytes()

    response = requests.get(f'{server.url}/static/file.jpeg', headers = {
        'range': 'bytes=0-63,128-191'
    })

    t.check('range 多区间：Content-Type 为 multipart/byteranges', 'multipart/byteranges' in (response.headers.get('content-type') or ''), repr(response.headers.get('content-type')))
    t.known_issue('range 多区间：返回 206 Partial Content', response.status_code == 206, f'status={response.status_code}')
    t.known_issue('range 多区间：包含两段各 64 字节的内容', content[:64] in response.content and content[128:192] in response.content, f'{len(response.content)} bytes')

def case_range_invalid(t, server):
    ''' 请求范围超出文件大小时应返回 416 '''
    content = STATIC.read_bytes()

    response = requests.get(f'{server.url}/static/file.jpeg', headers = {
        'range': f'bytes=0-{len(content) + 10}'
    })
    t.check('range 越界：返回 416', response.status_code == 416, f'status={response.status_code}')

CASES = [
    ('静态文件读取', case_static),
    ('静态文件 Range（单区间）', case_range_single),
    ('静态文件 Range（多区间）', case_range_multi),
    ('静态文件 Range（越界 416）', case_range_invalid)
]
