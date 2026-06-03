# **Scheduler**

任务调度数据不在分布式环境下共享，若要在分布式环境下管理任务调度，请自行实现功能

```python
from CheeseAPI import CheeseAPI, Websocket, Response

app = CheeseAPI()

def task(*args, **kwargs):
    print('Task')

@app.signal.after_server_start.connect()
def tasks():
    app.scheduler.add(1, task)

if __name__ == '__main__':
    app.start()
```

## **`class Scheduler`**

### **`tasks: dict[str, Task]`**

当前所有任务

### **`def add(self, interval_time: float, fn: Callable | None = None, *, first_run_timer: datetime.datetime | None = None, expected_run_num: int | None = None, key: str | None = None, run_type: Literal['THREAD', 'PROCESS'] = 'THREAD', args: tuple = (), kwargs: dict = {}, auto_remove: bool = False, timeout: float | None = None) -> Callable | Task`**

使用装饰器会自动执行任务，使用函数调用会返回 Task 对象，需手动调用 `start` 方法启动任务

- **Args**

    - **interval_time**

        任务执行间隔

    - **first_run_timer**

        首次执行时间，若值小于当前时间则立刻执行

    - **expected_run_num**

        预期执行次数，若未设置则无限次执行

    - **key**

        默认为 uuid

    - **run_type**

        任务执行方式，支持线程和进程

    - **args**

        默认首位是 `app: CheeseAPI`

    - **auto_remove**

        任务执行完毕后是否自动移除

    - **timeout**

        当 app.sync_server_url 存在时，任务超过多少秒没有执行完毕则认为执行失败，在 sync_server 中会视为任务删除，None 默认为 `interval_time * 2` 的值；恢复执行后会在 sync_server 上自动恢复

### **`async def async_add(self, interval_time: float, fn: Callable | None = None, *, first_run_timer: datetime.datetime | None = None, expected_run_num: int | None = None, key: str | None = None, args: tuple = (), kwargs: dict = {}, auto_remove: bool = False, timeout: float | None = None) -> Callable | Task`**

使用协程方式添加任务

使用装饰器会自动执行任务，使用函数调用会返回 Task 对象，需手动调用 `start` 方法启动任务

- **Args**

    - **interval_time**

        任务执行间隔

    - **first_run_timer**

        首次执行时间，若值小于当前时间则立刻执行

    - **expected_run_num**

        预期执行次数，若未设置则无限次执行

    - **key**

        默认为 uuid

    - **args**

        默认首位是 `app: CheeseAPI`

    - **auto_remove**

        任务执行完毕后是否自动移除

    - **timeout**

        当 app.sync_server_url 存在时，任务超过多少秒没有执行完毕则认为执行失败，在 sync_server 中会视为任务删除，None 默认为 `interval_time * 2` 的值；恢复执行后会在 sync_server 上自动恢复

### **`def start(self, key: str)`**

启动任务

### **`async def async_start(self, key: str)`**

启动任务

### **`def stop(self, key: str)`**

停止任务

### **`def remove(self, key: str)`**

移除任务

### **`async def async_stop(self, key: str)`**

停止任务

### **`async def async_remove(self, key: str)`**

移除任务

### **`def get_tasks(self) -> dict[str, Task]`**

获取所有任务

### **`async def async_get_tasks(self) -> dict[str, Task]`**

获取所有任务

### **`def get_task(self, key: str) -> Task | None`**

获取任务

### **`async def async_get_task(self, key: str) -> Task | None`**

获取任务

## **`class Task`**

在 `is_running` 为 `False` 时，修改任务属性是可行的，在下一次运行时会生效

### **`def __init__(self, fn: Callable, interval_time: float, *, first_run_timer: datetime.datetime | float | None = None, expected_run_num: int | None = None, key: str | None = None, run_type: Literal['THREAD', 'PROCESS', 'ASYNC'] = 'THREAD', args: tuple = (), kwargs: dict = {}, auto_remove: bool = False, timeout: float | None = None)`**

- **Args**

    - **interval_time**

        任务执行间隔

    - **first_run_timer**

        首次执行时间，若小于当前时间则立刻执行，若大于当前时间则在指定时间执行；支持 `datetime.datetime` 或 `float` 时间戳

    - **expected_run_num**

        预期执行次数，若未设置则无限次执行

    - **key**

        默认为随机 uuid

    - **run_type**

        任务执行方式，可选线程、协程、进程

    - **args**

        默认首位是 `app: CheeseAPI`

    - **auto_remove**

        任务完成期望次数后是否自动移除

    - **timeout**

        当 app.sync_server_url 存在时，任务超过多少秒没有执行完毕则认为执行失败，在 sync_server 中会视为任务删除，None 默认为 `interval_time * 2` 的值；恢复执行后会在 sync_server 上自动恢复

### **`self.fn: Callable`**

### **`self.interval_time: float`**

任务执行间隔

### **`self.first_run_timer: datetime.datetime | float | None`**

首次执行时间，若小于当前时间则立刻执行，若大于当前时间则在指定时间执行

### **`self.expected_run_num: int | None`**

预期执行次数，若未设置则无限次执行

### **`self.key: str`**

### **`self.run_type: Literal['THREAD', 'PROCESS', 'ASYNC']`**

任务执行方式，支持线程、进程和协程

### **`self.args: tuple`**

默认首位是 `app: CheeseAPI`

### **`self.kwargs: dict`**

### **`self.auto_remove: bool`**

任务完成期望次数后是否自动移除

### **`self.timeout: float`**

当 app.sync_server_url 存在时，任务超时时间

### **`self.is_running: bool`**

任务是否在运行中

### **`self.last_run_timer: datetime.datetime | None`**

上一次的运行时刻

### **`self.last_run_time: float | None`**

上一次的运行耗时

### **`self.run_num: int`**

运行次数

### **`self.run_num_completed: bool`**

任务是否已完成预期运行次数

### **`def start(self)`**

启动任务

### **`async def async_start(self)`**

启动任务

上一次的运行耗时

### **`run_num: int`**

运行次数
