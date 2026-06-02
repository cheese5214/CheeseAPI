# **Request**

每个路由都会在 `**kwargs` 传输一个 `request: Request`

若出现部分属性为 `None` 的情况，代表该属性未被解析

```python
from CheeseAPI import Request

app = CheeseAPI()

@app.route.get('/')
async def test(*, request: Request):
    ...
```

## **`self.ip: str`**

## **`self.method: str`**

## **`self.path: str`**

## **`self.params: dict[str, str]`**

## **`self.headers: dict[str, str]`**

## **`self.query: dict[str, str]`**

## **`self.body: bytes | str`**

## **`self.json: dict | list`**

## **`self.form: dict[str, str]`**

## **`self.files: dict[str, File]`**

## **`self.cookies: dict[str, str]`**

## **`self.full_path: str`**

## **`self.ranges: list[tuple[int, int | None]]`**

## **`self.files: dict[str, File]`**

上传的文件字典，key 为表单字段名，value 为 `File` 对象

## **`self.file: File | None`**

单文件上传对象

## **`async def recv_body(self, get_all: bool = False) -> bool | Response`**

若在路由中设置了 `auto_recv_body = False`，则需要手动调用此方法接收请求体

- **Args**

    - **get_all**

        是否接收完整请求体。若设置为 `False`，则在接收到部分请求体后立即返回 `False`，直到完整请求体接收完毕才返回 `True`

- **Returns**

    - **True**

        表示请求体已完整接收

    - **False**

        表示请求体未完整接收（仅在 `get_all = False` 时可能返回此值）

    - **Response**

        表示在接收请求体时发生错误，需立即返回此响应

## **`async def parse_body(self)`**

若在路由中设置了 `auto_recv_body = False`，则需要手动调用此方法解析请求体
