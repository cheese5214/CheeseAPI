'''
测试应用（服务端）侧的工具

只在被测服务进程里使用：负责路径引导、状态导出、告警捕获。
客户端侧的工具见 `utils.py`。
'''
import json, os, sys, warnings
from pathlib import Path

TESTS_DIR = Path(__file__).parent
PROJECT_ROOT = TESTS_DIR.parent

def bootstrap():
    ''' 确保被测进程 import 到的是本仓库源码，而不是 site-packages 里的旧版本 '''
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

bootstrap()

class AppState:
    '''
    服务进程内需要被测试观测的状态

    测试跑在另一个进程，所以状态通过 `CHEESE_TEST_STATE` 指向的文件传递；
    写入用「临时文件 + 替换」保证读取方不会看到写了一半的内容。
    '''

    __slots__ = ('path', 'data')

    def __init__(self, **initial):
        self.path: str = os.environ['CHEESE_TEST_STATE']
        self.data: dict = dict(initial)
        self.dump()

    def dump(self):
        temporary = f'{self.path}.tmp'
        with open(temporary, 'w', encoding = 'utf-8') as f:
            json.dump(self.data, f, ensure_ascii = False)
        os.replace(temporary, self.path)

    def set(self, key: str, value):
        self.data[key] = value
        self.dump()
        return value

    def inc(self, key: str, step: int = 1) -> int:
        return self.set(key, self.data.get(key, 0) + step)

def capture_warnings():
    ''' 把运行时告警（如协程未 await 的 RuntimeWarning）写到文件，供测试断言 '''
    path = os.environ['CHEESE_TEST_WARN']

    def show(message, category, filename, lineno, file = None, line = None):
        with open(path, 'a', encoding = 'utf-8') as f:
            f.write(f'{category.__name__}: {message}\n')

    warnings.simplefilter('always')
    warnings.showwarning = show

def printer(error_key: str = 'error'):
    '''
    生成一个把 WebSocket 错误计数进状态的 Printer 子类

    需要在 `bootstrap()` 之后调用（要能 import CheeseAPI）
    '''
    from CheeseAPI.printer import Printer

    class _Printer(Printer):
        __slots__ = ()

    return _Printer
