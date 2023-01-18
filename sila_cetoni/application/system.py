"""
________________________________________________________________________

:PROJECT: sila_cetoni

*System*

:details: System:
    The whole application system representing all physical devices

:file:    system.py
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

from __future__ import annotations

import logging
import os
import threading
import time
from abc import abstractmethod
from enum import Enum
from typing import TYPE_CHECKING, List, Optional, Union

# import qmixsdk
try:
    from qmixsdk import qmixbus

    from .device import CetoniPumpDevice
except (ModuleNotFoundError, ImportError):
    pass

from sila2.framework import UndefinedExecutionError

from .application_configuration import ApplicationConfiguration
from .configuration import DeviceConfiguration
from .device import Device
from .server_configuration import ServerConfiguration
from .singleton import ABCSingleton

if TYPE_CHECKING:
    from sila2.framework import Command, Feature, Property

    from ....device_driver_abc import DeviceDriverABC
    from .cetoni_device_configuration import CetoniDeviceConfiguration
    from .device import (
        BalanceDevice,
        HeatingCoolingDevice,
        PurificationDevice,
        StirringDevice,
        ThirdPartyDevice,
        CetoniMobDosDevice,
    )

logger = logging.getLogger(__name__)


class ApplicationSystemState(Enum):
    """
    The state of the overall application system
    """

    OPERATIONAL = "Operational"
    STOPPED = "Stopped"
    SHUTDOWN = "Shutting Down"

    def is_operational(self):
        return self.value == self.OPERATIONAL.value

    def is_stopped(self):
        return self.value == self.STOPPED.value

    def shutting_down(self):
        return self.value == self.SHUTDOWN.value


class ApplicationSystemBase(ABCSingleton):
    """
    An abstract interface for an application system consisting of a device configuration and a system state
    """

    _config: DeviceConfiguration
    _state: ApplicationSystemState

    def __init__(self, config: DeviceConfiguration) -> None:
        self._config = config
        logger.info(f"{type(self).__name__} config: {self._config}")
        self._state = ApplicationSystemState.STOPPED

    @property
    def device_config(self) -> DeviceConfiguration:
        return self._config

    @property
    def state(self) -> ApplicationSystemState:
        return self._state

    @abstractmethod
    def start(self):
        raise NotImplementedError()

    @abstractmethod
    def stop(self):
        raise NotImplementedError()

    @abstractmethod
    def shutdown(self, force: bool = False):
        raise NotImplementedError()


class CetoniApplicationSystem(ApplicationSystemBase):
    """
    Special application system for a CETONI device configuration
    """

    _config: CetoniDeviceConfiguration

    __bus_monitoring_thread: threading.Thread

    __mobdos: Optional[CetoniMobDosDevice]
    __MAX_SECONDS_WITHOUT_BATTERY = 20

    def __init__(self, config: CetoniDeviceConfiguration) -> None:
        super().__init__(config)

        try:
            self.__mobdos = list(filter(lambda d: d.device_type == "mobdos", self._config.devices))[0]
        except IndexError:
            self.__mobdos = None

    def start(self):
        """
        Starts the CAN bus communications and the bus monitoring and enables devices
        """
        self._state = ApplicationSystemState.OPERATIONAL
        self._config.start_bus_and_enable_devices()
        if self._config.has_battery:
            self.__start_bus_monitoring()

    def stop(self):
        """
        Stops the CAN bus monitoring and the bus communication
        """
        logger.info("Stopping CETONI application system...")
        previous_state = self._state
        self._state = ApplicationSystemState.SHUTDOWN
        if self.__mobdos is not None:
            self.__mobdos.stop()
        logger.info("Closing bus...")
        if previous_state.is_operational():
            self._config.stop_bus()
        self._config.close_bus()

    def shutdown(self, force: bool = False):
        """
        Shuts down the operating system if we are battery powered

        Parameters
        ----------
        force: bool
            If `True` immediately shuts down the system without attempting to stop the sila-cetoni process first,
            otherwise the process is stopped first and then the system is shut down
        """
        if self._config.has_battery:
            logger.info(f"Shutting down {'forced' if force else ''}...")
            os.system(f"({'sleep 30 &&' if not force else ''} sudo shutdown now) &")

    def __start_bus_monitoring(self):
        """
        Starts monitoring the CAN bus for events (esp. emergency and error events)
        """
        self.__bus_monitoring_thread = threading.Thread(target=self.__monitor_events, name="QmixBusMonitoringThread")
        self.__bus_monitoring_thread.start()

    def __monitor_events(self):
        """
        Runs an infinite loop that polls the bus for any events.

        If an emergency event is received that suggests that the controller was turned
        off (i.e. DC link under-voltage and a heartbeat error) all SiLA servers will
        be stopped.
        If a "heartbeat error resolved" event is received after the controller was turned
        off it is interpreted to mean that the controller is up and running again and
        the SiLA servers are attempted to start.
        """

        DC_LINK_UNDER_VOLTAGE = 0x3220

        def is_dc_link_under_voltage_event(event: qmixbus.Event):
            return event.event_id == qmixbus.EventId.device_emergency.value and event.data[0] == DC_LINK_UNDER_VOLTAGE

        def is_heartbeat_err_occurred_event(event: qmixbus.Event):
            return (
                event.event_id == qmixbus.EventId.device_guard.value
                and event.data[0] == qmixbus.GuardEventId.heartbeat_err_occurred.value
            )

        def is_heartbeat_err_resolved_event(event: qmixbus.Event):
            return (
                event.event_id == qmixbus.EventId.device_guard.value
                and event.data[0] == qmixbus.GuardEventId.heartbeat_err_resolved.value
            )

        seconds_stopped = 0
        while not self._state.shutting_down():
            time.sleep(1)

            event = self._config.read_bus_event()
            if event.is_valid():
                logger.debug(
                    f"event id: {event.event_id}, device handle: {event.device.handle}, "
                    f"node id: {event.device.get_node_id()}, data: {event.data}, message: {event.string}"
                )

                if self._state.is_operational() and is_dc_link_under_voltage_event(event):
                    self._state = ApplicationSystemState.STOPPED
                    logger.info("System entered 'Stopped' state")
                    time.sleep(1)  # wait for the Atmel to catch up and detect the missing battery/external power
                    continue

            if (
                self._state.is_stopped()
                and self.__mobdos.battery is not None
                and not self.__mobdos.battery.is_secondary_source_connected
            ):
                seconds_stopped += 1
                if seconds_stopped > self.__MAX_SECONDS_WITHOUT_BATTERY:
                    logger.info("Shutting down because battery has been removed for too long")
                    self.shutdown(True)

            if self.__mobdos.battery is not None:
                logger.debug(
                    f"heartbeat resolved: {is_heartbeat_err_resolved_event(event)}, "
                    f"bat conn: {self.__mobdos.battery.is_connected}, "
                    f"ext conn {self.__mobdos.battery.is_secondary_source_connected}"
                )
            else:
                logger.debug(f"heartbeat resolved: {is_heartbeat_err_resolved_event(event)}")

            if self._state.is_stopped() and is_heartbeat_err_resolved_event(event):
                self._state = ApplicationSystemState.OPERATIONAL
                logger.info("System entered 'Operational' state")
                seconds_stopped = 0
                for device in self._config.devices:
                    logger.debug(f"Setting device {device} operational")
                    device.set_operational()
                    if isinstance(device, CetoniPumpDevice):
                        device: CetoniPumpDevice  # typing
                        drive_pos_counter = ServerConfiguration(
                            device.name.replace("_", " "), self._config.name
                        ).pump_drive_position_counter
                        if drive_pos_counter is not None and not device.device_handle.is_position_sensing_initialized():
                            logger.debug(f"Restoring drive position counter: {drive_pos_counter}")
                            device.device_handle.restore_position_counter_value(drive_pos_counter)


class ApplicationSystem(ApplicationSystemBase):
    """
    The whole application system containing all devices (CETONI + 3rd-party) and all configuration
    """

    _config: ApplicationConfiguration

    __cetoni_application_system: Optional[CetoniApplicationSystem]

    def __init__(self, config: ApplicationConfiguration) -> None:
        super().__init__(config)

        cetoni_device_config_path = self._config.cetoni_device_config_path
        if cetoni_device_config_path is not None:
            from .cetoni_device_configuration import CetoniDeviceConfiguration

            self.__cetoni_application_system = CetoniApplicationSystem(
                CetoniDeviceConfiguration(cetoni_device_config_path.name, cetoni_device_config_path)
            )
        else:
            self.__cetoni_application_system = None

        logger.debug(f"Parsed devices {self._config.devices}")

        self.__create_balances(self._config.scan_devices)
        self.__create_lcms(self._config.scan_devices)
        self.__create_heating_cooling_devices(self._config.scan_devices)
        self.__create_purification_devices(self._config.scan_devices)
        self.__create_stirring_devices(self._config.scan_devices)
        self.__create_io_devices(self._config.scan_devices)

        logger.debug(f"Created devices {self._config.devices}")

    def start(self):
        logger.info("Starting application system...")
        self._state = ApplicationSystemState.OPERATIONAL
        if self.__cetoni_application_system is not None:
            self.__cetoni_application_system.start()
        for device in self._config.devices:
            try:
                if device.device is not None:
                    device.device.start()
            except Exception as err:
                device.device = self.___set_device_driver_simulated_or_raise(device, err)
                device.device.start()
        logger.info("Application system started")

    def stop(self):
        logger.info("Stopping application system...")
        self._state = ApplicationSystemState.SHUTDOWN
        if self.__cetoni_application_system is not None:
            self.__cetoni_application_system.stop()
        for device in self._config.devices:
            try:
                device.device.stop()
            except AttributeError:
                # some devices might not be completely setup yet, i.e. they don't have a `device` that can be `stop`ped
                continue

    def shutdown(self, force: bool = False):
        logger.info("Shutting down application system")
        self._state = ApplicationSystemState.SHUTDOWN
        if self.__cetoni_application_system is not None:
            self.__cetoni_application_system.shutdown(force)
        self.stop()

    @property
    def all_devices(self) -> List[Device]:
        """
        Returns a merged list of all devices (CETONI and third-party devices)
        """
        if self.__cetoni_application_system is not None:
            return self._config.devices + self.__cetoni_application_system.device_config.devices
        return self._config.devices

    def ___set_device_driver_simulated_or_raise(self, device: ThirdPartyDevice, err: Exception) -> DeviceDriverABC:
        """
        Swaps the device driver of the given `device` to a simulated driver or raises `err` if this is not possible
        """
        if self._config.simulate_missing and not device.simulated:
            device.simulated = True
            if device.device_type == "balance":
                from sila_cetoni.balance.device_drivers import sartorius_balance

                if isinstance(err, sartorius_balance.SartoriusBalanceNotFoundException):
                    logger.warning(
                        f"Could not connect to balance on {device.port}, setting device simulated", exc_info=err
                    )
                    return sartorius_balance.SartoriusBalanceSim(device.port)
            elif device.device_type == "heating_cooling":
                if device.manufacturer == "Huber":
                    from sila_cetoni.heating_cooling.device_drivers import huber_chiller

                    if isinstance(err, huber_chiller.HuberChillerNotFoundException):
                        logger.warning(
                            f"Could not connect to Huber Chiller on {device.port}, setting device simulated",
                            exc_info=err,
                        )
                        return huber_chiller.HuberChillerSim(device.port)
                elif device.manufacturer == "Memmert":
                    from sila_cetoni.heating_cooling.device_drivers import memmert_oven

                    if isinstance(err, memmert_oven.MemmertOvenNotFoundException):
                        logger.warning(
                            f"Could not connect to Memmert Oven on {device.server_url}, setting device simulated",
                            exc_info=err,
                        )
                        return memmert_oven.MemmertOvenSim(device.server_url)
            elif device.device_type == "purification":
                from sila_cetoni.purification.device_drivers import sartorius_arium

                if isinstance(err, sartorius_arium.SartoriusAriumNotFoundException):
                    logger.warning(
                        f"Could not connect to purification device on {device.server_url}, setting device simulated",
                        exc_info=err,
                    )
                    return sartorius_arium.SartoriusAriumSim(device.server_url, device.trigger_port)
            elif device.device_type == "stirring":
                from sila_cetoni.stirring.device_drivers import twomag_mixdrive

                if isinstance(err, twomag_mixdrive.MIXdriveNotFoundException):
                    logger.warning(
                        f"Could not connect to stirring device on {device.port}, setting device simulated", exc_info=err
                    )
                    return twomag_mixdrive.MIXdriveSim(device.port)
        raise err

    # -------------------------------------------------------------------------
    # Balance
    def __create_balances(self, scan: bool = False):
        """
        Looks up all balances from the current configuration and tries to auto-detect more devices if `scan` is `True`
        """

        balances = list(filter(lambda d: d.device_type == "balance", self._config.devices))

        try:
            from sila_cetoni.balance.device_drivers import sartorius_balance

            from .device import BalanceDevice
        except (ModuleNotFoundError, ImportError) as err:
            msg = "Could not import sila_cetoni.balance package - no support for balance devices!"
            if len(balances) > 0:
                raise RuntimeError(msg)
            else:
                logger.warning(msg, exc_info=err)
            return

        balances: List[BalanceDevice]  # typing

        for balance in balances:
            if balance.manufacturer == "Sartorius":
                logger.debug(f"Connecting to balance on port {balance.port!r}")
                SartoriusBalance = (
                    sartorius_balance.SartoriusBalanceSim if balance.simulated else sartorius_balance.SartoriusBalance
                )
                try:
                    balance.device = SartoriusBalance(balance.port)
                except sartorius_balance.BalanceNotFoundException as err:
                    balance.device = self.___set_device_driver_simulated_or_raise(balance, err)

        if scan:
            logger.debug("Looking for balances")

            bal = sartorius_balance.SartoriusBalance()
            try:
                bal.open()
                logger.debug(f"Found balance on port {bal.port!r}")
                balance = BalanceDevice(
                    "Sartorius_Balance", {"type": "balance", "manufacturer": "Sartorius", "port": bal.port}
                )
                balance.device = bal
                self._config.devices += [balance]
            except sartorius_balance.BalanceNotFoundException:
                pass

    # -------------------------------------------------------------------------
    # LC/MS
    def __create_lcms(self, scan: bool = False):
        """
        Looks up all possible LC/MS device from the current configuration and tries to auto-detect more devices if
        `scan` is `True`

        :note: We currently only support a single LC/MS device
        """

        devices = list(filter(lambda d: d.device_type == "lcms", self._config.devices))

        try:
            from sila_cetoni.lcms.device_drivers import shimadzu_lcms2020

            from .device import LCMSDevice
        except (ModuleNotFoundError, ImportError) as err:
            msg = "Could not import sila_cetoni.lcms package - no support for LC/MS devices!"
            if len(devices) > 0:
                raise RuntimeError(msg)
            else:
                logger.warning(msg, exc_info=err)
            return

        for lcms in devices:
            if lcms.manufacturer == "Shimadzu":
                logger.debug(f"Connecting to LC/MS {lcms.name!r}")
                lcms.device = shimadzu_lcms2020.ShimadzuLCMS2020()

        if scan:
            logger.debug("Looking for LC/MS")

            lcms = shimadzu_lcms2020.ShimadzuLCMS2020()
            try:
                lcms.open()
                logger.debug(f"Found LC/MS named {lcms.instrument_name!r}")
                lcms_dev = LCMSDevice(lcms.instrument_name, {"type": "lcms", "manufacturer": "Shimadzu"})
                lcms_dev.device = lcms
                self._config.devices += [lcms_dev]
            except shimadzu_lcms2020.LabSolutionsStartException:
                pass

    # -------------------------------------------------------------------------
    # Heating/Cooling
    def __create_heating_cooling_devices(self, scan: bool = False):
        """
        Looks up all heating/cooling devices from the current configuration and tries to auto-detect more devices if
        `scan` is `True`
        """

        devices = list(filter(lambda d: d.device_type == "heating_cooling", self._config.devices))

        try:
            from sila_cetoni.heating_cooling.device_drivers import huber_chiller, memmert_oven

            from .device import HeatingCoolingDevice, HuberChillerDevice, MemmertOvenDevice
        except (ModuleNotFoundError, ImportError) as err:
            msg = "Could not import sila_cetoni.heating_cooling package - no support for heating/cooling devices!"
            if len(devices) > 0:
                raise RuntimeError(msg)
            else:
                logger.warning(msg, exc_info=err)
            return

        devices: List[HeatingCoolingDevice]  # typing

        for device in devices:
            if device.manufacturer == "Huber":
                device: HuberChillerDevice  # typing
                logger.debug(f"Connecting to Huber Chiller on port {device.port!r}")
                HuberChiller = huber_chiller.HuberChillerSim if device.simulated else huber_chiller.HuberChiller
                try:
                    device.device = HuberChiller(device.port)
                except huber_chiller.HuberChillerNotFoundException as err:
                    device.device = self.___set_device_driver_simulated_or_raise(device, err)
            elif device.manufacturer == "Memmert":
                device: MemmertOvenDevice  # typing
                logger.debug(f"Connecting to Memmert Oven at {device.server_url!r}")
                Memmertoven = memmert_oven.MemmertOvenSim if device.simulated else memmert_oven.MemmertOven
                try:
                    device.device = Memmertoven(device.server_url)
                except memmert_oven.MemmertOvenNotFoundException as err:
                    device.device = self.___set_device_driver_simulated_or_raise(device, err)

        if scan:
            logger.debug("Looking for heating/cooling devices")
            logger.info("Automatic searching for heating/cooling devices will only find Huber Chillers!")

            dev = huber_chiller.HuberChiller()
            try:
                dev.open()
                logger.debug(f"Found heating/cooling device named {dev.name!r}")
                device = HeatingCoolingDevice(
                    dev.name, {"type": "heating_cooling", "manufacturer": "Huber", "port": dev.port}
                )
                device.device = dev
                self._config.devices += [device]
            except huber_chiller.HuberChillerNotFoundException:
                pass

    # -------------------------------------------------------------------------
    # Purification
    def __create_purification_devices(self, scan: bool = False):
        """
        Looks up all purification devices from the current configuration and tries to auto-detect more devices if `scan`
        is `True`
        """

        devices: List[PurificationDevice] = list(
            filter(lambda d: d.device_type == "purification", self._config.devices)
        )

        try:
            from sila_cetoni.purification.device_drivers import sartorius_arium
        except (ModuleNotFoundError, ImportError) as err:
            msg = "Could not import sila_cetoni.purification package - no support for purification devices!"
            if devices:
                raise RuntimeError(msg)
            else:
                logger.warning(msg, exc_info=err)
            return

        devices: List[PurificationDevice]  # typing

        for device in devices:
            if device.manufacturer == "Sartorius":
                logger.debug(f"Connecting to purification device via {device.server_url!r}")
                SartoriusArium = (
                    sartorius_arium.SartoriusAriumSim if device.simulated else sartorius_arium.SartoriusArium
                )
                try:
                    device.device = SartoriusArium(device.server_url, device.trigger_port)
                except sartorius_arium.SartoriusAriumNotFoundException as err:
                    device.device = self.___set_device_driver_simulated_or_raise(device, err)

        if scan:
            logger.warning("Automatic searching for purification devices is not supported at the moment!")

    # -------------------------------------------------------------------------
    # Stirring
    def __create_stirring_devices(self, scan: bool = False):
        """
        Looks up all stirring devices from the current configuration and tries to auto-detect more devices if `scan` is
        `True`
        """

        devices = list(filter(lambda d: d.device_type == "stirring", self._config.devices))

        try:
            from sila_cetoni.stirring.device_drivers import twomag_mixdrive

            from .device import StirringDevice
        except (ModuleNotFoundError, ImportError) as err:
            msg = "Could not import sila_cetoni.stirring package - no support for stirring devices!"
            if len(devices) > 0:
                raise RuntimeError(msg)
            else:
                logger.warning(msg, exc_info=err)
            return

        devices: List[StirringDevice]  # typing

        for device in devices:
            if device.manufacturer == "2mag":
                logger.debug(f"Connecting to stirring device on port {device.port!r}")
                MIXdrive = twomag_mixdrive.MIXdriveSim if device.simulated else twomag_mixdrive.MIXdrive
                try:
                    device.device = MIXdrive(device.port)
                except twomag_mixdrive.MIXdriveNotFoundException as err:
                    device.device = self.___set_device_driver_simulated_or_raise(device, err)

        if scan:
            logger.debug("Looking for stirring devices")

            dev = twomag_mixdrive.MIXdrive()
            try:
                dev.open()
                logger.debug(f"Found stirring device on port {dev.port!r}")
                device = StirringDevice(dev.name, {"type": "stirring", "manufacturer": "2mag", "port": dev.port})
                device.device = dev
                self._config.devices += [device]
            except twomag_mixdrive.MIXdriveNotFoundException:
                pass

    # -------------------------------------------------------------------------
    # I/O
    def __create_io_devices(self, scan: bool = False):
        """
        Looks up all I/O devices from the current configuration and tries to auto-detect more devices if `scan` is `True`
        """

        devices: List[IODevice] = list(filter(lambda d: d.device_type == "io", self._config.devices))

        try:
            from sila_cetoni.io.device_drivers import revpi

            from .device import IODevice
        except (ModuleNotFoundError, ImportError) as err:
            msg = "Could not import sila_cetoni.io.device_drivers.revpi package - no support for Revolution PI I/O!"
            if len(devices) > 0:
                raise RuntimeError(msg)
            else:
                logger.warning(msg, exc_info=err)
            return

        for device in devices:
            if device.manufacturer == "Kunbus":
                channels: List[revpi.IOChannelInterface] = []

                for (description, ChannelType) in (
                    ("analog in", revpi.RevPiAnalogInChannel),
                    ("analog out", revpi.RevPiAnalogOutChannel),
                    ("digital in", revpi.RevPiDigitalInChannel),
                    ("digital out", revpi.RevPiDigitalOutChannel),
                ):
                    channel_count = ChannelType.number_of_channels()
                    logger.debug(f"Number of {description} channels: {channel_count}")
                    for i in range(channel_count):
                        channels += [ChannelType.channel_at_index(i)]
                        logger.debug(f"Found {description} channel {i} named {channels[-1].name}")

                device.io_channels = channels


class SystemNotOperationalError(UndefinedExecutionError):
    def __init__(self, command_or_property: Union[Command, Property]):
        super().__init__(
            "Cannot {} {} because the system is not in an operational state.".format(
                "execute" if isinstance(command_or_property, Command) else "read from",
                command_or_property.fully_qualified_identifier,
            )
        )


def requires_operational_system(feature: Feature):
    """
    Function decorator that checks whether the global `ApplicationSystem` is in an operational state before executing
    the decorated function. If the system is not in an operation state then a `SystemNotOperationalError` will be raised
    with the Fully Qualified Identifier of the Command/Property that was tried to be accessed.

    Parameters
    ----------
    feature: Feature
        The Feature that the decorated function belongs to (needed when raising the error)
    """

    def decorator(func):
        """
        The actual decorator

        Parameters
        ----------
        func: Callable
            The decorated function
        """

        def wrapper(*args, **kwargs):
            """
            The function wrapper around `func`

            Parameters
            ----------
            *args: Tuple
                Positional arguments passed to `func`
            **kwargs: Tuple
                Keyword arguments passed to `func`
            """
            if not ApplicationSystem().state.is_operational():
                raise SystemNotOperationalError(feature[func.__name__])
            func(*args, **kwargs)

        return wrapper

    return decorator
