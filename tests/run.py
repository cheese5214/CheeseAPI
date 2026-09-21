'''
测试入口

用法：

```bash
python tests/run.py              # 跑全部用例
python tests/run.py websocket    # 只跑指定模块的用例
```

运行依赖：已安装 `CheeseAPI` / `CheeseLog` / `CheeseSignal`（以及 `requests`）。
本地用源码目录开发时，可把它们通过 `PYTHONPATH` 指进去，例如：

```bash
PYTHONPATH=~/Desktop/CheeseLog:~/Desktop/CheeseSignal python tests/run.py
```

每个测试模块声明自己用的测试应用（`APP = 'apps/xxx.py'`），`run.py` 按应用分组，
同一个应用只启动一次服务，跑完该组的用例再关掉。
'''
import importlib.util, sys, time
from pathlib import Path

TESTS_DIR = Path(__file__).parent
sys.path.insert(0, str(TESTS_DIR))

from utils import Server, Tester

MODULES = [
    'chunked',
    'range',
    'route',
    'request',
    'response',
    'cors',
    'validator',
    'static',
    'file',
    'signal_hooks',
    'scheduler',
    'websocket',
    'app_config'
]

def load(name: str):
    '''
    按文件路径加载测试模块

    不用 `importlib.import_module`：模块名会和标准库撞车（如 `signal` 已经被 import 过，
    `sys.modules` 里拿到的是标准库那个），所以用独立命名按路径加载
    '''
    path = TESTS_DIR / f'{name}.py'
    if not path.exists():
        return None

    spec = importlib.util.spec_from_file_location(f'cheese_test_{name}', path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module

def main(argv: list[str]) -> int:
    names = argv or MODULES

    try:
        import CheeseAPI
    except Exception as e:
        print(f'无法导入 CheeseAPI：{e}')
        print('请先安装运行依赖，或用 PYTHONPATH 指向 CheeseAPI / CheeseLog / CheeseSignal 源码目录')
        return 2

    tester = Tester()
    started = time.time()

    groups: dict[str, list[tuple[str, object]]] = {}
    for name in names:
        module = load(name)
        if module is None:
            print(f'跳过未实现的模块：{name}')
            continue
        groups.setdefault(getattr(module, 'APP', 'apps/basic.py'), []).append((name, module))

    for app, modules in groups.items():
        with Server(app = app) as server:
            print(f'\n=== {app}（{server.url}）===')
            for name, module in modules:
                print(f'\n[{name}]')
                for case_name, case in module.CASES:
                    print(f'  · {case_name}')
                    case(tester, server)

    print(f'\n===== {tester.summary}（{time.time() - started:.1f}s）=====')

    if tester.known_issues:
        print('\n已知缺陷：')
        for name, detail in tester.known_issues:
            print(f'  - {name}' + (f'  | {detail}' if detail else ''))

    if tester.failed:
        print('\n失败用例：')
        for name, _, detail in tester.failed:
            print(f'  - {name}' + (f'  | {detail}' if detail else ''))
        return 1

    return 0

if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
