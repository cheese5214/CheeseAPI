from typing import Literal, TYPE_CHECKING

from CheeseAPI.response import Response

if TYPE_CHECKING:
    from CheeseAPI.request import Request

HTTP_METHOD_TYPE = Literal['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS', 'HEAD', 'PATCH', 'CONNECT']

class CORS:
    __slots__ = ('allow_origins', 'allow_methods', 'allow_headers', 'allow_credentials', 'expose_headers', 'max_age')

    def __init__(self, allow_origins: list[str] = ['*'], allow_methods: list[HTTP_METHOD_TYPE] = ['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS', 'HEAD', 'PATCH', 'CONNECT'], allow_headers: list[str] = ['*'], allow_credentials: bool = False, expose_headers: list[str] = [], max_age: int | None = None):
        self.allow_origins: list[str] = allow_origins
        self.allow_methods: list[HTTP_METHOD_TYPE] = allow_methods
        self.allow_headers: list[str] = allow_headers
        self.allow_credentials: bool = allow_credentials
        self.expose_headers: list[str] = expose_headers
        self.max_age: int | None = max_age

    def get_response(self, request: 'Request'):
        origin = request.headers.get('Origin', '')
        if '*' not in self.allow_origins and origin not in self.allow_origins:
            return Response(status = 403)

        headers = {}

        if origin in self.allow_origins:
            headers['Access-Control-Allow-Origin'] = origin
        elif '*' in self.allow_origins and not self.allow_credentials:
            headers['Access-Control-Allow-Origin'] = '*'

        headers['Access-Control-Allow-Methods'] = ', '.join(self.allow_methods)

        if '*' in self.allow_headers:
            headers['Access-Control-Allow-Headers'] = request.headers.get('Access-Control-Request-Headers') or '*'
        else:
            headers['Access-Control-Allow-Headers'] = ', '.join(self.allow_headers)

        if self.allow_credentials:
            headers['Access-Control-Allow-Credentials'] = 'true'

        if self.expose_headers:
            headers['Access-Control-Expose-Headers'] = ', '.join(self.expose_headers)

        if self.max_age is not None:
            headers['Access-Control-Max-Age'] = str(self.max_age)

        return Response(status = 204, headers = headers)
