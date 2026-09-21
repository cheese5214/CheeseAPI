'''
基础测试应用：分块传输、静态文件/Range、WebSocket

由 `tests/chunked.py`、`tests/range.py`、`tests/websocket.py` 共用。
每个测试域都有自己独立的测试应用文件（`tests/apps/*.py`），互不干扰、可并行改动。
'''
import threading
from pathlib import Path

from apputils import AppState, capture_warnings

capture_warnings()

from CheeseAPI import CheeseAPI, Websocket, Response

STATE = AppState(connect = 0, disconnect = 0, error = 0, chunked_body = None)

class TestPrinter(__import__('CheeseAPI.printer', fromlist = ['Printer']).Printer):
    __slots__ = ()

    def websocket_error(self, e, websocket):
        STATE.inc('error')
        return super().websocket_error(e, websocket)

app = CheeseAPI(
    port = int(__import__('os').environ['CHEESE_TEST_PORT']),
    printer = TestPrinter,
    static_path = {
        '/static': str(Path(__file__).parent.parent.parent / 'examples' / 'static')
    }
)

#### WebSocket ####

@app.route.websocket('/ws')
class TestWebsocket(Websocket):
    async def on_connect(self):
        STATE.inc('connect')

    async def on_message(self, message: str | bytes):
        if message == 'close':
            await self.close()
        else:
            await self.send(message)

    async def on_disconnect(self):
        STATE.inc('disconnect')

@app.route.get('/static-send')
async def static_send(**_):
    ''' 同步静态发送：调用方在事件循环线程内 '''
    Websocket.send('/ws', 'static-hello')
    return Response('sent')

@app.route.get('/static-send-thread')
async def static_send_thread(**_):
    ''' 同步静态发送：调用方在其它线程（该线程没有运行中的事件循环） '''
    threading.Thread(target = lambda: Websocket.send('/ws', 'thread-hello')).start()
    return Response('sent')

@app.route.get('/static-send-after-disconnect')
async def static_send_after_disconnect(**_):
    ''' 连接已断开时发送：不能抛未捕获异常，也不能泄漏协程 '''
    Websocket.send('/ws', 'after-disconnect')
    return Response('sent')

@app.route.get('/connectors')
async def connectors(**_):
    ''' 当前 `Websocket.connectors` 中残留的连接数（用于断言清理干净） '''
    return Response(str(len(Websocket.connectors.get('/ws', []))))

#### HTTP ####

@app.route.post('/chunked')
async def chunked(*, request, **_):
    ''' 分块传输请求体，服务端拼完整后记下；响应用异步生成器分块返回 '''
    body = request.body
    STATE.set('chunked_body', body.decode() if isinstance(body, bytes) else str(body))
    return Response(async_chunked())

async def async_chunked():
    yield 'hello '
    yield 'world '
    yield 'chunked'

@app.route.get('/health')
async def health(**_):
    return Response('ok')

if __name__ == '__main__':
    app.start()
