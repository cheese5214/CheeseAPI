'''
WebSocket 用例

覆盖：回声、连接计数、同步静态发送投递、异常断连后的清理、以及不出现协程未 await 的告警
'''
import time

from utils import WebsocketClient

APP = 'apps/basic.py'

def case_echo(t, server):
    before = server.state()

    client = WebsocketClient(server.port)
    try:
        t.check('websocket 回声：on_connect 触发', server.wait_state('connect', before.get('connect', 0) + 1), f'state={server.state()}')

        client.send('ping')
        t.check('websocket 回声：文本消息原样返回', client.recv() == 'ping')
    finally:
        client.abort()

    t.check('websocket 回声：断开后 on_disconnect 触发', server.wait_state('disconnect', before.get('disconnect', 0) + 1), f'state={server.state()}')

def case_static_send(t, server):
    '''
    同步静态入口 `Websocket.send(path, data)`

    这里同时覆盖两种调用上下文：事件循环线程内、以及没有事件循环的其它线程
    '''
    client = WebsocketClient(server.port)
    try:
        server.get('/static-send')
        t.check('websocket 静态发送：循环内调用能真正送达', client.recv() == 'static-hello')

        server.get('/static-send-thread')
        t.check('websocket 静态发送：其它线程调用能真正送达', client.recv() == 'thread-hello')
    finally:
        client.abort()

def case_abnormal_disconnect(t, server):
    ''' 对端异常掉线（RST）后连接必须被清理，且不能持续报错 '''
    before = server.state()

    client = WebsocketClient(server.port)
    client.send('ping')
    client.recv()
    client.abort()

    t.check('websocket 异常断连：on_disconnect 被调用', server.wait_state('disconnect', before.get('disconnect', 0) + 1), f'state={server.state()}')
    t.check('websocket 异常断连：connectors 无残留', server.get('/connectors') == '0', f"connectors={server.get('/connectors')}")

    errors = server.state().get('error', 0)
    time.sleep(5.0)
    t.check('websocket 异常断连：不再反复报错', server.state().get('error', 0) == errors, f"error {errors} -> {server.state().get('error', 0)}")

def case_send_after_disconnect(t, server):
    ''' 连接已断开时再走同步静态发送：不能抛未捕获异常，也不能留下未 await 的协程 '''
    client = WebsocketClient(server.port)
    client.send('ping')
    client.recv()
    client.abort()

    before = server.state()
    server.wait_state('disconnect', before.get('disconnect', 0))
    time.sleep(1.0)

    errors = server.state().get('error', 0)
    try:
        server.get('/static-send-after-disconnect')
        server.get('/static-send-after-disconnect')
        crashed = False
    except Exception as e:
        crashed = True

    t.check('websocket 断连后发送：服务端未异常', not crashed)
    time.sleep(1.0)
    t.check('websocket 断连后发送：不产生新错误', server.state().get('error', 0) == errors, f"error {errors} -> {server.state().get('error', 0)}")

def case_no_never_awaited(t, server):
    ''' 静态入口不能被写成「拿到协程直接丢弃」，否则会刷 coroutine was never awaited '''
    server.get('/health')
    time.sleep(1.0)

    warnings = server.warnings()
    t.check('websocket：无 coroutine was never awaited 告警', 'never awaited' not in warnings, repr(warnings[:200]))

CASES = [
    ('websocket 回声与连接计数', case_echo),
    ('websocket 同步静态发送投递', case_static_send),
    ('websocket 异常断连清理', case_abnormal_disconnect),
    ('websocket 断连后发送', case_send_after_disconnect),
    ('websocket 无协程泄漏告警', case_no_never_awaited)
]
