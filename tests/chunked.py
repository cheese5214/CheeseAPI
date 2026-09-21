''' 分块传输（Transfer-Encoding: chunked） '''

APP = 'apps/basic.py'

def case_chunked(t, server):
    def body():
        yield 'hello '
        yield 'world '
        yield 'chunked'

    response = server.post('/chunked', data = body(), headers = {
        'transfer-encoding': 'chunked'
    })

    t.check('chunked：分块响应内容正确', response.text == 'hello world chunked', repr(response.text))
    t.check('chunked：服务端完整收到分块请求体', server.wait_state('chunked_body', 'hello world chunked'), repr(server.state().get('chunked_body')))

CASES = [
    ('chunked 请求体与分块响应', case_chunked)
]
