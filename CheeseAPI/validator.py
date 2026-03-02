import json
from typing import Callable, TYPE_CHECKING
from functools import wraps

import pydantic

from CheeseAPI.response import Response

if TYPE_CHECKING:
    from CheeseAPI.request import Request

def validator(*, json_model: pydantic.BaseModel | None = None, form_model: pydantic.BaseModel | None = None, params_model: pydantic.BaseModel | None = None, headers_model: pydantic.BaseModel | None = None, query_model: pydantic.BaseModel | None = None, hide_body: bool = False) -> Callable:
    '''
    对 request 的各个部分进行验证的装饰器
    根据不同的 xx_model 参数，返回 **kwargs 中的 xx_data 参数

    - Args
        - hide_body: 是否在验证失败时隐藏错误信息，若为 True 则仅返回 400 状态码，否则返回 400 状态码和错误信息
    '''

    def wrapper(fn: Callable) -> Callable:
        @wraps(fn)
        async def decorator(*args, **kwargs):
            try:
                request: 'Request' = kwargs.get('request', None)

                json_data = None
                if json_model is not None:
                    json_data = json_model.model_validate(request.json or {}, by_alias = True)
                if kwargs.get('json_data') is None:
                    kwargs['json_data'] = json_data

                form_data = None
                if form_model is not None:
                    form_data = form_model.model_validate(request.form or {}, by_alias = True)
                if kwargs.get('form_data') is None:
                    kwargs['form_data'] = form_data

                params_data = None
                if params_model is not None:
                    params_data = params_model.model_validate(request.params or {}, by_alias = True)
                if kwargs.get('params_data') is None:
                    kwargs['params_data'] = params_data

                headers_data = None
                if headers_model is not None:
                    headers_data = headers_model.model_validate(request.headers or {}, by_alias = True)
                if kwargs.get('headers_data') is None:
                    kwargs['headers_data'] = headers_data

                query_data = None
                if query_model is not None:
                    query_data = query_model.model_validate(request.query or {}, by_alias = True)
                if kwargs.get('query_data') is None:
                    kwargs['query_data'] = query_data
            except Exception as e:
                if hide_body:
                    return Response(status = 400)
                else:
                    return Response(json.loads(e.json()), 400)

            return await fn(*args, **kwargs)
        return decorator
    return wrapper
