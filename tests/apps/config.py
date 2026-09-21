'''
应用级配置测试应用：全局压缩、`logger_path`、keep-alive、`request_timeout`、`workers`、`manual_modules`

配置项可用环境变量覆盖，这样同一份应用文件能起出不同配置的服务进程
（例如 `keep_alive = False`、多 worker、只加载指定模块），供 `tests/app_config.py` 断言。
'''
from apputils import capture_warnings

capture_warnings()

import os, sys

# `tests/apps`（脚本目录）与 `tests` 都在 `sys.path` 里且排在标准库之前，其中与标准库同名的文件
# （如其它测试域用作测试应用的 `apps/signal.py`）会顶掉标准库的 `signal`，
# 而 `CheeseAPI` 依赖的 `multiprocessing` 正好要导入它。
# 把这两个目录挪到 `sys.path` 末尾：既不影响 `apputils` 的导入（多 worker 用 spawn 起子进程时会重新执行本文件），
# 也让标准库优先命中。
_APPS_DIR = os.path.dirname(os.path.abspath(__file__))
_TESTS_DIR = os.path.dirname(_APPS_DIR)
sys.path[:] = [path for path in sys.path if os.path.abspath(path or os.getcwd()) not in (_APPS_DIR, _TESTS_DIR)] + [_TESTS_DIR]

from CheeseAPI import CheeseAPI, Response

PORT: int = int(os.environ['CHEESE_TEST_PORT'])

COMPRESS_MIN_LENGTH: int = 1024
''' 与框架默认一致；测试用 1023 / 1024 / 12000 三种长度的响应体来划分压缩边界 '''

COMPRESS_LEVEL: int = 1
''' 刻意取 1（框架默认是 6）；这样「压缩后长度 == gzip.compress(body, 1) 的长度」就能证明应用级 `compress_level` 真的生效 '''

BIG: str = 'compress-me ' * 1000
''' 12000 字节的高压缩比响应体 '''

def env_bool(key: str, default: bool) -> bool:
    value = os.environ.get(key)
    return default if value is None else value == '1'

def env_list(key: str, default: list[str] | None = None) -> list[str]:
    ''' 环境变量存在时按其内容切分（可以为空列表），不存在时用默认值 '''
    if key not in os.environ:
        return default if default is not None else []
    return [item for item in os.environ[key].split(',') if item]

app = CheeseAPI(
    port = PORT,
    logger_path = f'/tmp/cheeseapi_test_log_{PORT}.log',
    compress = env_list('CHEESE_TEST_COMPRESS', ['gzip', 'deflate']),
    compress_min_length = COMPRESS_MIN_LENGTH,
    compress_level = COMPRESS_LEVEL,
    keep_alive = env_bool('CHEESE_TEST_KEEP_ALIVE', True),
    keep_alive_timeout = 0.5,
    keep_alive_max_requests = 3,
    request_timeout = 1.5,
    workers = int(os.environ.get('CHEESE_TEST_WORKERS', '1')),
    manual_modules = env_list('CHEESE_TEST_MANUAL_MODULES'))

@app.route.get('/health')
async def health(**_):
    return Response('ok')

@app.route.get('/big')
async def big(**_):
    ''' 超过 `compress_min_length` 的响应体 '''
    return Response(BIG)

@app.route.get('/exact')
async def exact(**_):
    ''' 响应体长度恰好等于 `compress_min_length` '''
    return Response('x' * COMPRESS_MIN_LENGTH)

@app.route.get('/under')
async def under(**_):
    ''' 响应体长度比 `compress_min_length` 少 1 '''
    return Response('y' * (COMPRESS_MIN_LENGTH - 1))

@app.route.get('/pid')
async def pid(**_):
    ''' 多 worker 时用来观测请求被分发到了哪个进程 '''
    return Response(str(os.getpid()))

@app.route.post('/echo')
async def echo(*, request, **_):
    ''' 回显收到的请求体长度；用于观测 `request_timeout` 对半截请求体的处理 '''
    return Response(str(len(request.body)))

if __name__ == '__main__':
    app.start()
