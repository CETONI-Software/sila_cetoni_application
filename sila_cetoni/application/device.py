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
from typing import Any, Dict, Generic, List, Type, TypeVar, Union

from sila_cetoni.device_driver_abc import DeviceDriverABC
from typing_extensions import Self

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
            f"{', simulated' if self.manufacturer else ''})"
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
    def simulated(self) -> str:
        return self._simulated


try:
    from qmixsdk import qmixanalogio, qmixbus, qmixcontroller, qmixdigio, qmixmotion, qmixpump, qmixvalve

    _QmixBusDeviceT = TypeVar("_QmixBusDeviceT", bound=qmixbus.Device)

    class CetoniDevice(Device, Generic[_QmixBusDeviceT]):
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

        # a device *might* have any combination and number of the following
        _io_channels: List[Union[qmixanalogio.AnalogChannel, qmixdigio.DigitalChannel]]
        _controller_channels: List[qmixcontroller.ControllerChannel]
        _valves: List[qmixvalve.Valve]

        def __init__(self, name: str, device_type: str = "dummy", handle: Type[_QmixBusDeviceT] = None) -> None:
            super().__init__(name, device_type, "CETONI", False)

            self._device_handle = handle
            self._device_properties = {}

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

        @property
        def io_channels(self) -> List[Union[qmixanalogio.AnalogChannel, qmixdigio.DigitalChannel]]:
            return self._io_channels

        @io_channels.setter
        def io_channels(self, io_channels: List[Union[qmixanalogio.AnalogChannel, qmixdigio.DigitalChannel]]):
            self._io_channels = io_channels

        @property
        def controller_channels(self) -> List[qmixcontroller.ControllerChannel]:
            return self._controller_channels

        @controller_channels.setter
        def controller_channels(self, controller_channels: List[qmixcontroller.ControllerChannel]):
            self._controller_channels = controller_channels

        @property
        def valves(self) -> List[qmixvalve.Valve]:
            return self._valves

        @valves.setter
        def valves(self, valves: List[qmixvalve.Valve]):
            self._valves = valves

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

    class CetoniIODevice(CetoniDevice[Union[qmixanalogio.AnalogChannel, qmixdigio.DigitalChannel]]):
        """
        Simple class to represent an I/O device that has an arbitrary number of analog and digital I/O channels
        (inherited from the `CetoniDevice` class)
        """

        def __init__(self, name: str) -> None:
            super().__init__(name, "io")

except (ModuleNotFoundError, ImportError):
    pass


_DeviceInterfaceT = TypeVar("_DeviceInterfaceT", bound=DeviceDriverABC)


class ThirdPartyDevice(Generic[_DeviceInterfaceT], Device):
    """
    A generic third-party (i.e. non-CETONI) device represented by a device driver interface

        Template Parameters
        -------------------
        _DeviceInterfaceT: type
            The type of the device driver interface (e.g. `BalanceInterface`)
    """

    _device: Type[_DeviceInterfaceT]

    def __init__(self, name: str, json_data: Dict) -> None:
        logger.info(json_data)
        super().__init__(
            name,
            json_data["type"],
            json_data["manufacturer"],
            json_data.get("simulated", SCHEMA["definitions"]["Device"]["properties"]["simulated"]["default"]),
        )
        if "port" in json_data:
            self._port: str = json_data["port"]
            ThirdPartyDevice.port = property(lambda s: s._port)
        if "server_url" in json_data:
            self._server_url: str = json_data["server_url"]
            ThirdPartyDevice.server_url = property(lambda s: s._server_url)

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


class PumpDevice(ThirdPartyDevice):
    """
    Simple class to represent a pump device
    """

    pass


class AxisSystemDevice(ThirdPartyDevice):
    """
    Simple class to represent an axis system device
    """

    pass


class ValveDevice(ThirdPartyDevice):
    """
    Simple class to represent a valve device
    """

    pass


class ControllerDevice(ThirdPartyDevice):
    """
    Simple class to represent a controller device
    """

    pass


class IODevice(ThirdPartyDevice):
    """
    Simple class to represent an I/O device
    """

    pass


try:
    from sila_cetoni.balance.device_drivers import BalanceInterface

    class BalanceDevice(ThirdPartyDevice[BalanceInterface]):
        """
        Simple class to represent a balance device
        """

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
    from sila_cetoni.heating_cooling.device_drivers import TemperatureControllerInterface

    class HeatingCoolingDevice(ThirdPartyDevice[TemperatureControllerInterface]):
        """
        Simple class to represent a heating/cooling device
        """

except (ModuleNotFoundError, ImportError):
    logger.warning(f"Could not find sila_cetoni.heating_cooling module! No support for heating/cooling devices.")

try:
    from sila_cetoni.purification.device_drivers import PurificationDeviceInterface

    class PurificationDevice(ThirdPartyDevice[PurificationDeviceInterface]):
        """
        Simple class to represent a purification device
        """

except (ModuleNotFoundError, ImportError):
    logger.warning(f"Could not find sila_cetoni.purification module! No support for purification devices.")
