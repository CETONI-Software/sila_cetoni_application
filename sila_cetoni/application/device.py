"""
________________________________________________________________________

:PROJECT: sila_cetoni

*Device*

:details: Device:
    Helper and wrapper classes for the Application class

:file:    application.py
:authors: Florian Meinicke

:date: (creation)          2021-07-15
:date: (last modification) 2022-07-18

________________________________________________________________________

**Copyright**:
  This file is provided "AS IS" with NO WARRANTY OF ANY KIND,
  INCLUDING THE WARRANTIES OF DESIGN, MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE.

  For further Information see LICENSE file that comes with this distribution.
________________________________________________________________________
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Dict, Generic, List, Type, TypeVar

from sila_cetoni.device_driver_abc import DeviceDriverABC
from typing_extensions import Self

if TYPE_CHECKING:
    from sila_cetoni.io.device_drivers import cetoni

from .application_configuration import SCHEMA

logger = logging.getLogger(__name__)


class Device(ABC):
    """
    An abstract interface for a device as it is represented in a device configuration file (e.g. a config.json or a
    CETONI device configuration)
    """

    _name: str
    _device_type: str
    _manufacturer: str
    _simulated: bool

    @abstractmethod
    def __init__(self, name: str, device_type: str, manufacturer: str, simulated: bool) -> None:
        self._name = name
        self._device_type = device_type
        self._manufacturer = manufacturer
        self._simulated = simulated

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}({self._name!r}, {self._device_type!r}, {self.manufacturer!r}"
            f"{', simulated' if self.simulated else ''})"
        )

    @property
    def name(self) -> str:
        return self._name

    @property
    def device_type(self) -> str:
        return self._device_type

    @property
    def manufacturer(self) -> str:
        return self._manufacturer

    @property
    def simulated(self) -> bool:
        return self._simulated

    @simulated.setter
    def simulated(self, simulated: bool):
        self._simulated = simulated


_T = TypeVar("_T")


class PumpDevice(Device):
    """
    Simple class to represent a pump device
    """

    pass


class AxisSystemDevice(Device):
    """
    Simple class to represent an axis system device
    """

    pass


class ValveDevice(Device, Generic[_T]):
    """
    Simple class to represent a device with (possibly) multiple valves

    Template Parameters
    -------------------
    _T: type
        The type of the valves (e.g. `qmixvalve.Valve`)
    """

    _valves: List[_T]

    def __init__(self, name: str, manufacturer: str, simulated: bool, *, device_type="valve", **kwargs) -> None:
        # `**kwargs` for additional arguments that are not used and that might come from `ThirdPartyDevice.__init__` as
        # the result of `ThirdPartyValveDevice.__init__`
        super().__init__(name=name, device_type=device_type or "valve", manufacturer=manufacturer, simulated=simulated)

    @property
    def valves(self) -> List[_T]:
        return self._valves

    @valves.setter
    def valves(self, valves: List[_T]):
        self._valves = valves


class ControllerDevice(Device, Generic[_T]):
    """
    Simple class to represent a controller device with (possibly) multiple controller channels

    Template Parameters
    -------------------
    _T: type
        The type of the controller channels (e.g. `qmixcontroller.ControllerChannels`)
    """

    _controller_channels: List[_T]

    def __init__(self, name: str, manufacturer: str, simulated: bool, *, device_type="controller", **kwargs) -> None:
        # `**kwargs` for additional arguments that are not used and that might come from `ThirdPartyDevice.__init__` as
        # the result of `ThirdPartyControllerDevice.__init__`
        super().__init__(
            name=name, device_type=device_type or "controller", manufacturer=manufacturer, simulated=simulated
        )

    @property
    def controller_channels(self) -> List[_T]:
        return self._controller_channels

    @controller_channels.setter
    def controller_channels(self, controller_channels: List[_T]):
        self._controller_channels = controller_channels


class IODevice(Device, Generic[_T]):
    """
    Simple class to represent an I/O device with (possibly) multiple I/O channels

    Template Parameters
    -------------------
    _T: type
        The type of the I/O channels (e.g. `cetoni.IOChannelInterface`)
    """

    _io_channels: List[_T]

    def __init__(self, name: str, manufacturer: str, simulated: bool, *, device_type="io", **kwargs) -> None:
        # `**kwargs` for additional arguments that are not used and that might come from `ThirdPartyDevice.__init__` as
        # the result of `ThirdPartyIODevice.__init__`
        super().__init__(name=name, device_type=device_type or "io", manufacturer=manufacturer, simulated=simulated)

    @property
    def io_channels(self) -> List[_T]:
        return self._io_channels

    @io_channels.setter
    def io_channels(self, io_channels: List[_T]):
        self._io_channels = io_channels


try:
    from qmixsdk import qmixbus, qmixcontroller, qmixmotion, qmixpump, qmixvalve
    from sila_cetoni.io.device_drivers import cetoni

    _QmixBusDeviceT = TypeVar("_QmixBusDeviceT", bound=qmixbus.Device)

    class CetoniDevice(
        ValveDevice[qmixvalve.Valve],
        ControllerDevice[qmixcontroller.ControllerChannel],
        IODevice[cetoni.IOChannelInterface],
        Device,
        Generic[_QmixBusDeviceT],
    ):
        """
        A CETONI device represented by a device handle, (optional) device properties, and optional I/O channels,
        controller channels and valves (some devices may have I/O channels, controller channels or valves attached to
        them which are not handled as individual devices but a re considered part of the device they are attaches to).

        Template Parameters
        -------------------
        _QmixBusDeviceT: type
            The type of the device handle (e.g. `qmixpump.Pump`)
        """

        _device_handle: Type[_QmixBusDeviceT]
        _device_properties: Dict[str, Any]

        def __init__(self, name: str, device_type: str = "", handle: Type[_QmixBusDeviceT] = None) -> None:
            super().__init__(name=name, device_type=device_type, manufacturer="CETONI", simulated=False)

            self._device_handle = handle
            self._device_properties = {}

            # a device *might* have any combination and number of the following
            self._valves = []
            self._controller_channels = []
            self._io_channels = []

        def __str__(self) -> str:
            return super().__str__() + f"\b, {self._device_handle}, {self._device_properties!r})"

        def __repr__(self) -> str:
            return super().__repr__() + (
                f"\b, {self._device_handle}, {self._device_properties!r}, {[v.get_device_name() for v in self._valves]}"
                f", {[c.get_name() for c in self._controller_channels]}, {[c.get_name() for c in self._io_channels]}="
            )

        @property
        def device_handle(self) -> Type[_QmixBusDeviceT]:
            return self._device_handle

        @property
        def device_properties(self) -> Dict[str, Any]:
            return self._device_properties

        def set_device_property(self, name: str, value: Any):
            """
            Set the device property `name` to the given value `value`
            If the property is not present yet it will be added automatically
            """
            self._device_properties[name] = value

        def set_operational(self):
            """
            Set the device (and all of its valves, if present) into operational state
            """
            logger.info("cetoni set_operational")
            self._device_handle.set_communication_state(qmixbus.CommState.operational)
            for valve in self._valves:
                valve.set_communication_state(qmixbus.CommState.operational)

    class CetoniPumpDevice(CetoniDevice[qmixpump.Pump]):
        """
        Simple wrapper around `qmixpump.Pump` with additional information from the `CetoniDevice` class
        """

        _is_peristaltic_pump: bool

        def __init__(self, name: str, handle: qmixpump.Pump) -> None:
            super().__init__(name, "contiflow_pump" if isinstance(handle, qmixpump.ContiFlowPump) else "pump", handle)
            self._is_peristaltic_pump = False

        @property
        def is_peristaltic_pump(self) -> bool:
            return self._is_peristaltic_pump

        @is_peristaltic_pump.setter
        def is_peristaltic_pump(self, is_peristaltic_pump):
            self._is_peristaltic_pump = is_peristaltic_pump
            self._device_type = "peristaltic_pump" if is_peristaltic_pump else "pump"

        def set_operational(self):
            super().set_operational()
            self._device_handle.clear_fault()
            self._device_handle.enable(False)
            while not self._device_handle.is_enabled():
                self._device_handle.enable(True)

    class CetoniAxisSystemDevice(CetoniDevice[qmixmotion.AxisSystem]):
        """
        Simple wrapper around `qmixmotion.AxisSystem` with additional information from the `CetoniDevice` class
        """

        def __init__(self, name: str, handle: qmixmotion.AxisSystem) -> None:
            super().__init__(name, "axis_system", handle)

        def set_operational(self):
            super().set_operational()
            self._device_handle.enable(False)

    class CetoniValveDevice(CetoniDevice[qmixvalve.Valve]):
        """
        Simple class to represent a valve device that has an arbitrary number of valves (inherited from the
        `CetoniDevice` class)
        """

        def __init__(self, name: str) -> None:
            super().__init__(name, "valve")

    class CetoniControllerDevice(CetoniDevice[qmixcontroller.ControllerChannel]):
        """
        Simple class to represent a controller device that has an arbitrary number of controller channels
        (inherited from the `CetoniDevice` class)
        """

        def __init__(self, name: str) -> None:
            super().__init__(name, "controller")

    class CetoniIODevice(CetoniDevice[cetoni.IOChannelInterface]):
        """
        Simple class to represent an I/O device that has an arbitrary number of analog and digital I/O channels
        (inherited from the `CetoniDevice` class)
        """

        def __init__(self, name: str) -> None:
            super().__init__(name, "io")

except (ModuleNotFoundError, ImportError):
    pass


_DeviceInterfaceT = TypeVar("_DeviceInterfaceT", bound=DeviceDriverABC)


class ThirdPartyDevice(Device, Generic[_DeviceInterfaceT]):
    """
    A generic third-party (i.e. non-CETONI) device represented by a device driver interface

        Template Parameters
        -------------------
        _DeviceInterfaceT: type
            The type of the device driver interface (e.g. `BalanceInterface`)
    """

    _device: Type[_DeviceInterfaceT]

    def __new__(cls, name: str, json_data: Dict, *args, **kwargs) -> Self:
        device_type = json_data["type"]
        manufacturer = json_data["manufacturer"]
        if device_type == "balance":
            return super().__new__(BalanceDevice)
        elif device_type == "heating_cooling":
            if manufacturer == "Huber":
                return super().__new__(HuberChillerDevice)
            elif manufacturer == "Memmert":
                return super().__new__(MemmertOvenDevice)
        elif device_type == "lcms":
            return super().__new__(LCMSDevice)
        elif device_type == "purification":
            return super().__new__(PurificationDevice)
        elif device_type == "stirring":
            return super().__new__(StirringDevice)
        elif device_type == "io":
            return super().__new__(ThirdPartyIODevice)
        else:
            raise RuntimeError(f"Unknown device type {device_type!r} for {cls.__name__!r}")

    def __init__(self, name: str, json_data: Dict) -> None:
        logger.info(json_data)
        super().__init__(
            name=name,
            device_type=json_data["type"],
            manufacturer=json_data["manufacturer"],
            simulated=json_data.get("simulated", SCHEMA["definitions"]["Device"]["properties"]["simulated"]["default"]),
        )

    def __repr__(self) -> str:
        return (
            super().__repr__() + f"\b{(', ' + repr(self.port)) if hasattr(self, 'port') else ''}"
            f"{', ' + repr(self.server_url) if hasattr(self, 'server_url') else ''}"
            f"{', ' + repr(self.device) if hasattr(self, 'device') else ''})"
        )

    @property
    def device(self) -> Type[_DeviceInterfaceT]:
        return self._device

    @device.setter
    def device(self, device: Type[_DeviceInterfaceT]):
        self._device = device


from sila_cetoni.io.device_drivers import IOChannelInterface


class ThirdPartyIODevice(ThirdPartyDevice[IOChannelInterface], IODevice[IOChannelInterface]):
    """
    A third party I/O device
    """

    def __init__(self, name: str, json_data: Dict) -> None:
        super().__init__(name, json_data)

        self._device = None


try:
    from sila_cetoni.balance.device_drivers import BalanceInterface

    class BalanceDevice(ThirdPartyDevice[BalanceInterface]):
        """
        Simple class to represent a balance device
        """

        __port: str

        def __init__(self, name: str, json_data: Dict) -> None:
            super().__init__(name, json_data)
            self.__port = json_data["port"]

        @property
        def port(self) -> str:
            return self.__port

except (ModuleNotFoundError, ImportError):
    logger.warning(f"Could not find sila_cetoni.balance module! No support for balance devices.")

try:
    from sila_cetoni.lcms.device_drivers import LCMSInterface

    class LCMSDevice(ThirdPartyDevice[LCMSInterface]):
        """
        Simple class to represent an LC/MS device
        """

except (ModuleNotFoundError, ImportError):
    logger.warning(f"Could not find sila_cetoni.lcms module! No support for lcms devices.")

try:
    from sila_cetoni.heating_cooling.device_drivers import HuberChillerInterface, MemmertOvenInterface

    class HeatingCoolingDevice(Generic[_DeviceInterfaceT], ThirdPartyDevice[_DeviceInterfaceT]):
        """
        Simple class to represent a heating/cooling device
        """

        def __init__(self, name: str, json_data: Dict) -> None:
            super().__init__(name, json_data)

    class HuberChillerDevice(HeatingCoolingDevice[HuberChillerInterface]):
        """
        Simple class to represent a Huber Chiller device
        """

        __port: str

        def __init__(self, name: str, json_data: Dict) -> None:
            super().__init__(name, json_data)
            self.__port = json_data["port"]

        @property
        def port(self) -> str:
            return self.__port

    class MemmertOvenDevice(HeatingCoolingDevice[MemmertOvenInterface]):
        """
        Simple class to represent a Memmert Oven device
        """

        __server_url: str

        def __init__(self, name: str, json_data: Dict) -> None:
            super().__init__(name, json_data)
            self.__server_url = json_data["server_url"]

        @property
        def server_url(self) -> str:
            return self.__server_url

except (ModuleNotFoundError, ImportError):
    logger.warning(f"Could not find sila_cetoni.heating_cooling module! No support for heating/cooling devices.")

try:
    from sila_cetoni.purification.device_drivers import PurificationDeviceInterface

    class PurificationDevice(ThirdPartyDevice[PurificationDeviceInterface]):
        """
        Simple class to represent a purification device
        """

        __server_url: str
        __trigger_port: str

        def __init__(self, name: str, json_data: Dict) -> None:
            super().__init__(name, json_data)
            self.__server_url = json_data["server_url"]
            self.__trigger_port = json_data["trigger_port"]

        def __repr__(self) -> str:
            return super().__repr__() + f"\b, {self.__trigger_port!r})"

        @property
        def server_url(self) -> str:
            return self.__server_url

        @property
        def trigger_port(self) -> str:
            return self.__trigger_port

except (ModuleNotFoundError, ImportError):
    logger.warning(f"Could not find sila_cetoni.purification module! No support for purification devices.")

try:
    from sila_cetoni.stirring.device_drivers import StirringDeviceInterface

    class StirringDevice(ThirdPartyDevice[StirringDeviceInterface]):
        """
        Simple class to represent a stirring device
        """

        __port: str

        def __init__(self, name: str, json_data: Dict) -> None:
            super().__init__(name, json_data)
            self.__port = json_data["port"]

        @property
        def port(self) -> str:
            return self.__port

except (ModuleNotFoundError, ImportError):
    logger.warning(f"Could not find sila_cetoni.stirring module! No support for stirring devices.")
