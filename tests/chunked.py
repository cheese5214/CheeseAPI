import threading, requests, time
from typing import TYPE_CHECKING

import __init__
from CheeseAPI import CheeseAPI, Response

if TYPE_CHECKING:
    from CheeseAPI import Request

app = CheeseAPI(exclude_modules = ['examples', 'tests'])

@app.route.post('/chunked')
async def chunked(*, request: 'Request', **_):
    print(request.body)
    return Response(async_gen())

async def async_gen():
    yield 'hello '
    yield 'world '
    yield 'chunked'

def gen():
    yield 'hello '
    yield 'world '
    yield 'chunked'

if __name__ == '__main__':
    threading.Thread(target = app.start, daemon = True).start()

    response = requests.post('http://0.0.0.0:5214/chunked', data = gen(), headers = {
        'transfer-encoding': 'chunked'
    })
    print(response.text)
