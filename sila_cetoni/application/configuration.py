import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Generic, List, Type, TypeVar

from .device import Device

logger = logging.getLogger(__name__)


class Configuration(ABC):
    """
    Abstract interface for any kind of configuration that has a name and can be parsed from a file
    """

    _name: str
    _file_path: Path

    def __init__(self, name: str, config_file_path: Path) -> None:
        self._name = name
        self._file_path = config_file_path
        self._parse()

    @abstractmethod
    def _parse(self) -> None:
        raise NotImplementedError()

    @property
    def name(self) -> str:
        return self._name

    @property
    def file_path(self) -> str:
        return self._file_path

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self._name!r}, {self._file_path!r})"


_T = TypeVar("_T", bound=Device)


class DeviceConfiguration(Configuration, Generic[_T]):
    """
    An abstract interface for a device configuration (i.e. a configuration with any number of devices)

    Template Parameters
    -------------------
    _T: type
        The device type of the devices in this configuration
    """

    _devices: List[Type[_T]]

    def __init__(self, name: str, config_file_path: Path) -> None:
        self._devices = []
        super().__init__(name, config_file_path)

    @property
    def devices(self) -> List[Type[_T]]:
        return self._devices

    def __str__(self) -> str:
        return super().__str__() + f"\b, devices: {self._devices})"
