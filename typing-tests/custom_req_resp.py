import dataclasses
from typing import Optional
from uuid import UUID

import falcon


@dataclasses.dataclass
class RichContext:
    userid: Optional[UUID] = None
    role: str = 'anonymous'


class FancyRequest(falcon.Request):
    context_type = RichContext


class FancyResponse(falcon.Response):
    context_type = RichContext


USERS = {
    'am9objoxMjM0': ('user', UUID('51e4b478-3825-4e46-9fd7-be7b61d616dc')),
    'dnl0YXM6MTIz': ('admin', UUID('5e50d2c4-1c52-42c7-b4c5-879d9bd390ee')),
}


class AuthMiddleware:
    def process_request(self, req: FancyRequest, resp: FancyResponse) -> None:
        if req.method == 'OPTIONS':
            return

        if req.auth:
            for key, user_role in USERS.items():
                if req.auth == f'Basic {key}':
                    req.context.role, req.context.userid = user_role
                    break
            else:
                raise falcon.HTTPUnauthorized()


app = falcon.App(request_type=FancyRequest, response_type=FancyResponse)
app.add_middleware(AuthMiddleware())
