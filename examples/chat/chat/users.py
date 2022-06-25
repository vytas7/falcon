import dataclasses
import re

import falcon
import ulid


class UserResource:
    _NAME_PATTERN = re.compile(r'^\w+$')

    def __init__(self, store):
        self._store = store

    async def on_get_collection(self, req, resp):
        resp.media = [user.to_dict() for user in self._store.list_all()]

    async def on_post_collection(self, req, resp):
        media = await req.get_media()
        if not isinstance(media, dict):
            raise falcon.HTTPBadRequest

        name = media.get('name')
        if not isinstance(name, str) or not self._NAME_PATTERN.match(name):
            raise falcon.HTTPInvalidParam('A string identifier is expected.', 'name')

        user = self._store.find(name, create_if_missing=True)
        resp.status = falcon.HTTP_CREATED
        resp.location = f'{req.path}/{user.userid}'


@dataclasses.dataclass
class User:
    userid: ulid.ULID
    name: str

    @classmethod
    def create(cls, name):
        return cls(ulid.ULID(), name)

    @property
    def created(self):
        return self.userid.datetime.isoformat()

    def to_dict(self):
        return {
            'created': self.created,
            'id': str(self.userid),
            'name': self.name,
        }

    def __hash__(self):
        return hash(str(self.userid))

    def __eq__(self, other):
        return isinstance(other, User) and self.userid == other.userid


class UserStore:
    def __init__(self):
        self._store = {}

    def get(self, userid):
        return self._store.get(str(userid))

    def find(self, name, create_if_missing=True):
        for user in self._store.values():
            if user.name == name:
                return user

        if create_if_missing:
            user = User.create(name)
            self._store[str(user.userid)] = user
            return user

        return None

    def list_all(self):
        return list(self._store.values())
