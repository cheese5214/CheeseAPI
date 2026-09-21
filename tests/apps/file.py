'''
file（File 抽象）测试应用

`File` 的用例是纯单元测试（在测试进程里直接构造 `File`），不需要服务路由；
这里只保留 `/health` 供测试框架判断服务就绪。
'''
import os, sys

''' 脚本所在目录（tests/apps）会占据 `sys.path[0]`：若该目录里存在与标准库同名的模块（如 signal.py），
    标准库会被顶掉，连 `CheeseAPI` 都 import 不进来。应用依赖的 apputils 由 PYTHONPATH 提供，
    不依赖脚本目录，所以这里先把它移出 sys.path。 '''
sys.path = [path for path in sys.path if os.path.realpath(path or '.') != os.path.dirname(os.path.realpath(__file__))]

from apputils import capture_warnings

capture_warnings()

from CheeseAPI import CheeseAPI, Response

app = CheeseAPI(port = int(os.environ['CHEESE_TEST_PORT']))

@app.route.get('/health')
async def health(**_):
    return Response('ok')

if __name__ == '__main__':
    app.start()
