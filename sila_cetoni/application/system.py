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
from datetime import datetime
from enum import Enum
from functools import wraps
from threading import Thread
from typing import TYPE_CHECKING, List, Optional, Union

from sila2.framework import UndefinedExecutionError

from sila_cetoni.pkgutil import available_packages

from .application_configuration import ApplicationConfiguration
from .configuration import DeviceConfiguration
from .device import Device
from .server_configuration import ServerConfiguration
from .singleton import ABCSingleton

if TYPE_CHECKING:
    from sila2.framework import Command, Feature, Property

    from sila_cetoni.mobdos import CetoniMobDosDevice

    from .cetoni_device_configuration import CetoniDeviceConfiguration

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
    __application_config: ApplicationConfiguration = None  # class variable

    __bus_monitoring_thread: threading.Thread

    __mobdos: Optional[CetoniMobDosDevice]
    __shutdown_time: datetime = None  # class variable
    __traffic_monitoring_thread: Thread

    def __init__(self, application_config: ApplicationConfiguration, config: CetoniDeviceConfiguration) -> None:
        super().__init__(config)
        self.__class__.__application_config = application_config

        self.__class__.__shutdown_time = datetime.now() + self.__application_config.cetoni_max_time_without_traffic

        try:
            self.__mobdos = list(filter(lambda d: d.device_type == "mobdos", self._config.devices))[0]

            def monitor_traffic():
                while not self._state.shutting_down():
                    if (
                        self.__mobdos is not None
                        and not self.__mobdos.battery.is_secondary_source_connected
                        and datetime.now() >= self.__shutdown_time
                    ):
                        logger.info(
                            f"Did not receive any requests for the last "
                            f"{self.__application_config.cetoni_max_time_without_traffic.total_seconds() / 60} minutes "
                            f"- shutting down"
                        )
                        ApplicationSystem().shutdown()
                    time.sleep(5)

            self.__traffic_monitoring_thread = Thread(target=monitor_traffic, name="TrafficMonitoringThread")
            self.__traffic_monitoring_thread.start()
        except IndexError:
            self.__mobdos = None
            self.__traffic_monitoring_thread = None

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
            logger.info(f"Shutting down {'forced' if force else 'gracefully'}...")
            os.system(f"({'' if force else 'sleep 15'}; sudo shutdown now) &")

    @classmethod
    def monitor_traffic(cls, klass):
        """
        Class decorator that monitors the decorated class's methods and detects whether the methods are called or not

        This information is used to shut down the device in case there were no Commands or Property requests received for a
        certain amount of time to save battery when the device is battery powered. If the device is not battery powered then
        the device is not automatically shut down.

        Inspired by: https://stackoverflow.com/a/2704528/12780516

        Parameters
        ----------
        klass: Type
            The decorated class
        """

        def __getattribute__(self, name):
            attr = object.__getattribute__(self, name)

            if cls.__application_config is None or not cls()._config.has_battery:
                # there is no `CetoniApplicationSystem` instance or we're not battery powered, so we don't need/want
                # to monitor for traffic
                return attr

            # the "update_" functions are called by the implementations, not by a client
            # the "get_calls_affected_by_" functions are called by the feature_implementation_servicer, not by a client
            # "stop" is called during server shutdown, not by a client
            if callable(attr) and not attr.__name__.startswith(("update_", "get_calls_affected_by_", "stop")):

                @wraps(attr)
                def wrapper(*args, **kwargs):
                    cls.__shutdown_time = datetime.now() + cls.__application_config.cetoni_max_time_without_traffic
                    logger.debug(
                        f"Received call to {self.__class__.__name__}.{attr.__name__} - bumping shutdown time to "
                        f"{cls.__shutdown_time!s}"
                    )
                    return attr(*args, **kwargs)

                return wrapper
            return attr

        klass.__getattribute__ = __getattribute__
        return klass

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

        from qmixsdk import qmixbus

        from sila_cetoni.pumps import CetoniPumpDevice

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
                if seconds_stopped > self.__application_config.cetoni_max_time_without_battery.total_seconds():
                    logger.info("Shutting down because battery has been removed for too long")
                    ApplicationSystem().shutdown(True)

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
                config, CetoniDeviceConfiguration(cetoni_device_config_path.name, cetoni_device_config_path)
            )
        else:
            self.__cetoni_application_system = None

        for name, package in available_packages().items():
            try:
                package.create_devices(self._config, self._config.scan_devices)
            except Exception as err:
                logger.warning(f"'{name}.create_devices' failed with error {err!r}", exc_info=err)

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
                device.set_device_simulated_or_raise(self._config, err)
                device.device.start()
        logger.info("Application system started")

    def stop(self):

        if threading.current_thread() is not threading.main_thread():
            # stop has to be executed in main thread because stopping the CetoniApplicationSystem has to run in the main
            # thread (because it was started from the main thread as well)

            from .application import Application, Task  # delayed import to break dependency cycle

            Application().tasks_queue.put(Task(self.stop))
            return

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

        if threading.current_thread() is not threading.main_thread():
            # shutdown has to be executed in main thread because it calls `stop()` which has to run in the main thread

            from .application import Application, Task  # delayed import to break dependency cycle

            Application().tasks_queue.put(Task(self.shutdown, force))
            return

        logger.info("Shutting down application system")
        self._state = ApplicationSystemState.SHUTDOWN
        if self.__cetoni_application_system is not None:
            self.__cetoni_application_system.shutdown(force)

        from .application import Application  # delayed import to break dependency cycle

        Application().stop()

    @property
    def all_devices(self) -> List[Device]:
        """
        Returns a merged list of all devices (CETONI and third-party devices)
        """
        if self.__cetoni_application_system is not None:
            return self._config.devices + self.__cetoni_application_system.device_config.devices
        return self._config.devices

    @staticmethod
    def ensure_operational(feature: Feature):
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

            @wraps(func)
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


class SystemNotOperationalError(UndefinedExecutionError):
    def __init__(self, command_or_property: Union[Command, Property]):
        super().__init__(
            "Cannot {} {} because the system is not in an operational state.".format(
                "execute" if isinstance(command_or_property, Command) else "read from",
                command_or_property.fully_qualified_identifier,
            )
        )
