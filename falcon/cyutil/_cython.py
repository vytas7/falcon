# Copyright 2023 by Vytautas Liuolia.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Pure Python mode shim in the case Cython is unavailable."""

import typing

Decorable = typing.Union[typing.Callable, type]


def _identity_func(entity: Decorable) -> Decorable:
    return entity


def _flag_decorator(value: bool) -> typing.Callable:
    return _identity_func


annotation_typing = _flag_decorator

ccall = _identity_func
cclass = _identity_func
cfunc = _identity_func

char = int
uchar = int
Py_ssize_t = int
int = int
double = float
float = float

p_uchar = bytes

compiled = False

__all__ = [
    'ccall',
    'cclass',
    'cfunc',
    'compiled',
]
