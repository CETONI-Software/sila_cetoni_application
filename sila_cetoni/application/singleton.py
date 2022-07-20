"""
________________________________________________________________________

:PROJECT: sila_cetoni

*Singleton*

:details: Singleton:
    A singleton class to be used as metaclass of another class in order to turn
    that class into a singleton

:file:    singleton.py
:authors: Florian Meinicke

:date: (creation)          2021-07-19
:date: (last modification) 2021-07-19

________________________________________________________________________

**Copyright**:
  This file is provided "AS IS" with NO WARRANTY OF ANY KIND,
  INCLUDING THE WARRANTIES OF DESIGN, MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE.

  For further Information see LICENSE file that comes with this distribution.
________________________________________________________________________
"""

from abc import ABCMeta


# taken from https://stackoverflow.com/questions/6760685/creating-a-singleton-in-python
class SingletonMeta(type):
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(SingletonMeta, cls).__call__(*args, **kwargs)
        return cls._instances[cls]


# https://stackoverflow.com/a/33364149/12780516
class ABCSingletonMeta(ABCMeta, SingletonMeta):
    pass


class Singleton(metaclass=SingletonMeta):
    """
    Helper class that provides a standard way to create a Singleton using inheritance.

    (inspired by abc.ABC)
    """

    __slots__ = ()


class ABCSingleton(metaclass=ABCSingletonMeta):
    __slots__ = ()
