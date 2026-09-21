# tests

CheeseAPI 的功能测试，按「测试域」划分：每个域有**自己的测试应用**（`tests/apps/*.py`）和**自己的测试模块**（`tests/*.py`）。

## 运行

```bash
python tests/run.py                 # 跑全部用例
python tests/run.py websocket route # 只跑指定模块
```

运行依赖：已安装 `CheeseAPI` / `CheeseLog` / `CheeseSignal` 与 `requests`。
本地用源码目录开发时，可通过 `PYTHONPATH` 指进去（测试会把本仓库源码插到 `sys.path` 最前面，
不会被 site-packages 里可能存在的旧版本顶掉）：

```bash
PYTHONPATH=~/Desktop/CheeseLog:~/Desktop/CheeseSignal python tests/run.py
```

## 结构

| 文件 | 用途 |
|------|------|
| `run.py` | 入口：按各模块声明的 `APP` 分组，一个应用只起一次服务，跑完汇总并返回退出码 |
| `utils.py` | **客户端侧**：`Tester`（断言/汇总）、`Server`（服务进程 + HTTP 客户端）、`WebsocketClient`（裸 socket WS 客户端） |
| `apputils.py` | **服务端侧**：`bootstrap()`、`AppState`（状态导出）、`capture_warnings()` |
| `apps/*.py` | 各测试域的测试应用（被测服务） |
| `*.py` | 各测试域的测试模块 |

### 测试模块的契约

```python
APP = 'apps/xxx.py'          # 用哪个测试应用

CASES = [
    ('用例名', case_fn),
]

def case_fn(t, server):
    t.check('断言名', 条件, 失败详情)
```

### 测试应用的契约

```python
from apputils import AppState, capture_warnings
capture_warnings()

import os
from CheeseAPI import CheeseAPI, Response

STATE = AppState(...)        # 可选：需要被测试进程观测的状态

app = CheeseAPI(port = int(os.environ['CHEESE_TEST_PORT']))

@app.route.get('/health')    # 必须：测试框架靠它判断服务就绪
async def health(**_):
    return Response('ok')

if __name__ == '__main__':
    app.start()
```

## 测试域

| 模块 | 覆盖 |
|------|------|
| `chunked.py` | 分块传输（请求体与分块响应） |
| `range.py` | 静态文件读取与 Range 请求 |
| `route.py` | 路由注册与匹配、动态路由、404/405、优先级 |
| `request.py` | 请求解析：headers / query / body / json / form / files / cookies / ranges |
| `response.py` | 响应体类型、状态与头、cookie、重定向、FileResponse、压缩 |
| `cors.py` | 简单请求与预检请求的 CORS 头、应用级与路由级配置 |
| `validator.py` | 表单/查询/路径参数校验与失败响应 |
| `static.py` | 静态目录映射、content-type、404、路径穿越 |
| `file.py` | `File` 的构造、属性与 `save()` |
| `signal_hooks.py` | 生命周期信号与请求周期信号的触发与顺序 |
| `scheduler.py` | 定时任务的增删启停、执行方式、次数与超时 |
| `websocket.py` | 回声、同步静态发送投递、异常断连清理、协程泄漏 |
| `app_config.py` | 应用级配置：全局压缩、`logger_path`、keep-alive、`request_timeout` 等 |

## 三处刻意的设计

**服务跑在子进程。** `app.start()` 内部会 `signal.signal(...)` 注册信号处理器，而 Python 只允许在主线程注册，
所以 `threading.Thread(target = app.start)` 的写法在 Python 3.13 上会直接抛
`ValueError: signal only works in main thread`——服务根本没起来，测试却还在跑。
`utils.Server` 用 `subprocess` 起服务，并 `start_new_session=True`（CheeseAPI 停止时会
`os.killpg(os.getpgid(os.getpid()), SIGINT)`，杀掉整个进程组）。

**服务进程内的状态用文件传出来。** 连接计数、信号触发记录、定时任务执行次数、以及服务进程里捕获的运行时告警
（`CHEESE_TEST_STATE` / `CHEESE_TEST_WARN`）都写到文件，测试进程读文件断言，
这样「服务端是否真的清理了连接」「有没有协程未 await 的告警」这类只能在内侧看到的事实才验得了。

**每个域一个应用进程。** 各域的配置需求不同（压缩、keep-alive、路由模式……），共用一个应用会互相牵制；
分开后各域可独立改动、互不干扰。

## 已知缺陷（known issue）

`Tester.known_issue` 断言的是**正确行为**，用于「实现暂时不满足、但不想让套件变红」的场景：

- 当前无法满足 → 记为 `KNOWN`（不算失败，保持套件绿色）
- 修好之后 → 变成 `FAIL`，提示把该用例转成正式断言 `check`

**当前 0 项**：原先记录的 40 项已知缺陷已全部修复，对应用例都已转成正式断言 `check`，
全量运行是 `504/504 passed，0 FAIL`。`known_issue` 接口保留，供后续新增未修缺陷时使用。
