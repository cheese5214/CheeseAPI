'''
static（静态文件服务）测试应用

主映射指到仓库里的 `examples/static/`（只读、不污染仓库）；
另外在 `/tmp` 下造一棵静态目录树，用于测试子目录访问、目录索引（index.html）、
二进制文件的 content-type，以及路径穿越的边界目标（`_secret` 兄弟目录）。
'''
import os, sys
from pathlib import Path

''' 脚本所在目录（tests/apps）会占据 `sys.path[0]`：若该目录里存在与标准库同名的模块（如 signal.py），
    标准库会被顶掉，连 `CheeseAPI` 都 import 不进来。应用依赖的 apputils 由 PYTHONPATH 提供，
    不依赖脚本目录，所以这里先把它移出 sys.path。 '''
sys.path = [path for path in sys.path if os.path.realpath(path or '.') != os.path.dirname(os.path.realpath(__file__))]

from apputils import capture_warnings

capture_warnings()

from CheeseAPI import CheeseAPI, Response

PORT = int(os.environ['CHEESE_TEST_PORT'])

''' 仓库自带的静态目录：file.jpeg / file.txt '''
REPO_STATIC = Path(__file__).parent.parent.parent / 'examples' / 'static'

''' /tmp 下的临时静态目录树，供子目录 / index.html / 路径穿越边界用例使用 '''
TEMP_ROOT = Path(f'/tmp/cheeseapi_static_{PORT}')
TEMP_SECRET = Path(f'/tmp/cheeseapi_static_{PORT}_secret')

TEMP_ROOT.mkdir(parents = True, exist_ok = True)
TEMP_ROOT.joinpath('sub').mkdir(exist_ok = True)
TEMP_ROOT.joinpath('indexdir').mkdir(exist_ok = True)
TEMP_ROOT.joinpath('indexdir', 'index.html').write_text('<h1>index</h1>', encoding = 'utf-8')
TEMP_ROOT.joinpath('sub', 'nested.txt').write_text('nested-content', encoding = 'utf-8')
TEMP_ROOT.joinpath('data.bin').write_bytes(bytes(range(256)))

''' 与静态根同前缀的兄弟目录：路径穿越校验若用 startswith 会被绕过 '''
TEMP_SECRET.mkdir(parents = True, exist_ok = True)
TEMP_SECRET.joinpath('secret.txt').write_text('SECRET', encoding = 'utf-8')

app = CheeseAPI(
    port = PORT,
    static_path = {
        '/static': str(REPO_STATIC),
        '/extra': str(TEMP_ROOT)
    }
)

@app.route.get('/health')
async def health(**_):
    return Response('ok')

@app.route.get('/paths')
async def paths(**_):
    ''' 把服务进程看到的临时目录绝对路径交给测试进程，避免两边 cwd 不一致 '''
    return Response({
        'root': str(TEMP_ROOT),
        'secret': str(TEMP_SECRET)
    })

if __name__ == '__main__':
    app.start()
