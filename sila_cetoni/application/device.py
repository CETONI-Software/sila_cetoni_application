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
from typing import TYPE_CHECKING, Any, Dict, Generic, List, TypeVar

from sila_cetoni.device_driver_abc import DeviceDriverABC

if TYPE_CHECKING:
    from qmixsdk import qmixcontroller, qmixvalve

    from sila_cetoni.io.device_drivers import cetoni

    from .application_configuration import ApplicationConfiguration


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

    @abstractmethod
    def set_device_simulated_or_raise(self, config: ApplicationConfiguration, err: Exception) -> None:
        """
        Swaps the device driver of this device to a simulated driver or raises `err` if this is not possible

        Parameters
        ----------
        config : ApplicationConfiguration
            The current application configuration that should be used to check if this device should be simulated
            automatically or not
        err : Exception
            The error that occurred while creating the device
        """
        raise NotImplementedError()


try:
    from qmixsdk import qmixbus

    _QmixBusDeviceT = TypeVar("_QmixBusDeviceT", bound=qmixbus.Device)

    class CetoniDevice(Device, Generic[_QmixBusDeviceT]):
        """
        A CETONI device represented by a device handle, (optional) device properties, and optional I/O channels,
        controller channels and valves (some devices may have I/O channels, controller channels or valves attached to them
        which are not handled as individual devices but are considered part of the device they are attached to).

        Template Parameters
        -------------------
        _QmixBusDeviceT: type
            The type of the device handle (e.g. `qmixpump.Pump`)
        """

        _device_handle: _QmixBusDeviceT

        _valves: List[qmixvalve.Valve]
        _controller_channels: List[qmixcontroller.ControllerChannel]
        _io_channels: List[cetoni.IOChannelInterface]

        _device_properties: Dict[str, Any]

        def __init__(self, name: str, device_type: str = "", handle: _QmixBusDeviceT = None) -> None:
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
                f", {[c.get_name() for c in self._controller_channels]}, {[c.get_name() for c in self._io_channels]})"
            )

        @property
        def device_handle(self) -> _QmixBusDeviceT:
            return self._device_handle

        @property
        def valves(self) -> List[qmixvalve.Valve]:
            return self._valves

        @valves.setter
        def valves(self, valves: List[qmixvalve.Valve]):
            self._valves = valves

        @property
        def controller_channels(self) -> List[qmixcontroller.ControllerChannel]:
            return self._controller_channels

        @controller_channels.setter
        def controller_channels(self, controller_channels: List[qmixcontroller.ControllerChannel]):
            self._controller_channels = controller_channels

        @property
        def io_channels(self) -> List[cetoni.IOChannelInterface]:
            return self._io_channels

        @io_channels.setter
        def io_channels(self, io_channels: List[cetoni.IOChannelInterface]):
            self._io_channels = io_channels

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

        def set_device_simulated_or_raise(self, config: ApplicationConfiguration, err: Exception) -> None:
            # TODO: implement
            raise err

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

    _device: _DeviceInterfaceT

    def __init__(self, name: str, json_data: Dict) -> None:

        # avoid circular import
        from .application_configuration import SCHEMA

        logger.info(json_data)
        super().__init__(
            name=name,
            device_type=json_data["type"],
            manufacturer=json_data["manufacturer"],
            simulated=json_data.get("simulated", SCHEMA["definitions"]["Device"]["properties"]["simulated"]["default"]),
        )
        self._device = None

    def __repr__(self) -> str:
        return (
            super().__repr__() + f"\b{(', ' + repr(self.port)) if hasattr(self, 'port') else ''}"
            f"{', ' + repr(self.server_url) if hasattr(self, 'server_url') else ''}"
            f"{', ' + repr(self.device) if hasattr(self, 'device') else ''})"
        )

    @property
    def device(self) -> _DeviceInterfaceT:
        return self._device

    @device.setter
    def device(self, device: _DeviceInterfaceT):
        self._device = device
