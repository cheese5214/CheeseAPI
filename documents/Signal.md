# **Signal**

```python
from CheeseAPI import CheeseAPI

app = CheeseAPI()

@app.signal.before_server_start.connect()
def before_server_start():
    ...
```

## **`self.before_load_module: CheeseSignal`**

绑定函数`def func(*, index: int, module: str)`

## **`self.after_load_module: CheeseSignal`**

绑定函数`def func(*, index: int, module: str)`

## **`self.before_load_modules: CheeseSignal`**

绑定函数`def func(*, modules: list[str])`

## **`self.after_load_modules: CheeseSignal`**

绑定函数`def func(*, modules: list[str])`

## **`self.before_server_start: CheeseSignal`**

## **`self.after_server_start: CheeseSignal`**

## **`self.before_app_stop: CheeseSignal`**

## **`self.after_app_stop: CheeseSignal`**

## **`self.before_workers_start: CheeseSignal`**

绑定函数`def func(*, workers: int)`

## **`self.after_workers_start: CheeseSignal`**

绑定函数`def func(*, workers: int)`

## **`self.before_worker_start: CheeseSignal`**

绑定函数`def func(*, is_first: bool)`

## **`self.after_worker_start: CheeseSignal`**

绑定协程函数`async def func(*, is_first: bool)`

## **`self.before_worker_stop: CheeseSignal`**

绑定协程函数`async def func(*, is_first: bool)`

## **`self.after_worker_stop: CheeseSignal`**

绑定函数`def func(*, is_first: bool)`

## **`self.before_request: CheeseSignal`**

绑定协程函数`async def func(*, client_socket: socket.socket, addr: tuple[str, int])`

## **`self.after_request: CheeseSignal`**

绑定协程函数`async def func(*, request: Request | None)`

## **`self.before_response: CheeseSignal`**

绑定协程函数`async def func(*, response: Response) -> Response`

## **`self.after_response: CheeseSignal`**

绑定协程函数`async def func(*, response: Response)`
