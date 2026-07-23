import threading

import requests

import __init__
from CheeseAPI import CheeseAPI

app = CheeseAPI(exclude_modules = ['examples', 'tests'], static_path = {
    '/static': './examples/static'
})

if __name__ == '__main__':
    threading.Thread(target = app.start, daemon = True).start()

    print(requests.get('http://0.0.0.0:5214/static/file.jpeg', headers = {
        'range': 'bytes=0-1023'
    }).content)
    print(requests.get('http://0.0.0.0:5214/static/file.jpeg', headers = {
        'range': 'bytes=0-63,128-191'
    }).content)
