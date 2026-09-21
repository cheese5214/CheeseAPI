# **Response**

每个路由都应该返回一个响应

```python
from CheeseAPI import Request, Response

app = CheeseAPI()

@app.route.get('/')
async def test(*, request: Request):
    return Response()
```

## **`class Response`**

```python
from CheeseAPI import Response
```

### **`def __init__(self, body: dict | list | str | bytes | AsyncIterable | None = None, status: int = 200, headers: dict[str, str] = {}, *, high_precision_date: bool = False, compress: Literal['gzip', 'deflate', 'br', 'zstd'] | None = None, compress_level: int | None = None)`**

- **Args**

    - **body**

        当为 `AsyncIterable` 时，自动使用 chunked 传输编码

    - **headers**

        若某些特殊 headers 被设置，则不会被框架自动处理

    - **high_precision_date**

        是否使用高精度时间戳

    - **compress**

        强制使用的压缩算法，若不指定则根据请求头自动协商

    - **compress_level**

        压缩等级；每种算法的取值范围不同，请参考相应文档

### **`def set_cookie(self, key: str, value: str, expires: datetime.datetime | None = None, max_age: int | None = None, domain: str | None = None, secure: bool | None = None, http_only: bool | None = None)`**

## **`class RedirectResponse(Response)`**

既可从 `CheeseAPI.response` 导入，也可从 `CheeseAPI` 顶层导入：

```python
from CheeseAPI import RedirectResponse
```

### **`def __init__(self, location: str, status: Literal[301, 302, 303, 307, 308] = 302, headers: dict[str, str] = {}, body: bytes | str | list | dict | None = None)`**

## **`class FileResponse(Response)`**

### **`def __init__(self, file_path_or_file: str | File, *, status: int = 200, headers: dict[str, str] = {}, preview: bool = True, transmission_type: Literal['CONTENT_LENGTH', 'CHUNKED'] = 'CONTENT_LENGTH', chunked_size: int | None = None, compress: Literal['gzip', 'deflate', 'br', 'zstd'] | None = None, compress_level: int | None = None)`**

- **Args**

    - **preview**

        优先预览文件

    - **transmission_type**

        传输方式，'CONTENT_LENGTH' 使用 Content-Length 头，'CHUNKED' 使用分块传输编码

    - **chunked_size**

        分块传输时每块的大小
