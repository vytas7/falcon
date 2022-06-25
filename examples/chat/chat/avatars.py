import itertools

import falcon
import numpy as np
from PIL import Image


def voronoi(resolution, points):
    extent = 1 - 2 / resolution
    xc = np.linspace(-extent, +extent, resolution)
    yc = np.linspace(-extent, +extent, resolution)
    x, y = np.meshgrid(xc, yc)

    result = np.ones((resolution, resolution))

    for px, py in points:
        for point_x, point_y in itertools.product((px, -px), (py, -py)):
            np.minimum(result, np.hypot(x - point_x, y - point_y), out=result)
            np.minimum(result, np.hypot(x - point_y, y - point_x), out=result)

    # np.minimum(result, np.abs(1-x), out=result)
    # np.minimum(result, np.abs(-1-x), out=result)
    # np.minimum(result, np.abs(1-y), out=result)
    # np.minimum(result, np.abs(-1-y), out=result)

    return result


class Avatar:
    @classmethod
    def generate(cls, uid):
        return cls(uid, None)

    def __init__(self, uid, data):
        self._uid = uid
        self._data = data

    def to_resp(self, resp):
        resp.content_type = falcon.MEDIA_PNG
        resp.data = self._data


if __name__ == '__main__':
    a = voronoi(256, [np.random.random(2) * 0.75 for _ in range(10)])
    a = (a < 0.2) * (1 - a)
    a = a**5

    data = np.zeros((256, 256, 4), dtype=np.uint8)
    data[:, :, 0] = a * 255
    data[:, :, 1] = a * 192
    data[:, :, 3] = (a > 0.01) * 255

    Image.fromarray(data).show()
