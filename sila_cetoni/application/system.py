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

import logging
import os
from pathlib import Path
import sys
import threading
import time
from enum import Enum
from typing import List, Optional

# import qmixsdk
from qmixsdk import qmixanalogio, qmixbus, qmixcontroller, qmixdigio, qmixmotion, qmixpump, qmixvalve

from sila_cetoni.config import CETONI_SDK_PATH
from sila_cetoni.core.device_drivers.abc import BatteryInterface
from sila_cetoni.core.device_drivers.mobdos_battery import MobDosBattery

from .config import Config
from .device import (
    AxisSystemDevice,
    BalanceDevice,
    ControllerDevice,
    Device,
    DeviceConfiguration,
    IODevice,
    LCMSDevice,
    PumpDevice,
    ValveDevice,
)
from .singleton import Singleton

logger = logging.getLogger(__name__)


class SystemState(Enum):
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


class ApplicationSystem(metaclass=Singleton):
    """
    The whole application system containing all devices and all configuration
    """

    device_config: DeviceConfiguration = DeviceConfiguration.EMPTY
    bus: Optional[qmixbus.Bus] = None
    monitoring_thread: threading.Thread

    battery: Optional[BatteryInterface] = None
    pumps: List[PumpDevice] = []
    axis_systems: List[AxisSystemDevice] = []
    valves: List[ValveDevice] = []
    controllers: List[ControllerDevice] = []
    io_devices: List[IODevice] = []
    balances: List[BalanceDevice] = []
    lcms: Optional[LCMSDevice] = None

    state: SystemState

    MAX_SECONDS_WITHOUT_BATTERY = 20

    def __init__(self, device_config_path: Optional[Path] = None):
        logger.info("Looking up devices...")

        if device_config_path is not None:
            self.device_config = DeviceConfiguration(device_config_path)

            self.bus = qmixbus.Bus()
            self.open_bus()

            if self.device_config.has_battery:
                # we don't have any other specific battery drivers yet
                self.battery = MobDosBattery()

            # The order is important here! Many devices have I/O channels but are not
            # pure I/O devices (similarly, pumps might have a valve but they're not a
            # valve device). That's why valves have to be detected after pumps and I/O
            # devices have to be detected last (since then we can guarantee that there
            # is no possibility for an I/O channel to belong to an I/O device).
            self.pumps = self.get_availabe_pumps()
            self.axis_systems = self.get_availabe_axis_systems()
            self.valves = self.get_availabe_valves()
            self.controllers = self.get_availabe_controllers()
            self.io_devices = self.get_availabe_io_channels()

        self.balances = self.get_availabe_balances()
        self.lcms = self.get_availabe_lcms()

        logger.debug(f"Pumps: {self.pumps!r}")
        logger.debug(f"axis: {self.axis_systems!r}")
        logger.debug(f"valve devices: {self.valves!r}")
        logger.debug(f"controller devices: {self.controllers!r}")
        logger.debug(f"io devices: {self.io_devices!r}")
        logger.debug(f"balance devices: {self.balances!r}")
        logger.debug(f"lcms: {self.lcms!r}")

        self.state = SystemState.OPERATIONAL

    def start(self):
        """
        Starts the CAN bus communications and the bus monitoring and enables devices
        """
        if self.bus is not None:
            self.start_bus_and_enable_devices()
            self._start_bus_monitoring()

    def stop(self):
        """
        Stops the CAN bus monitoring and the bus communication
        """
        logger.info("Stopping application system...")
        self.state = SystemState.SHUTDOWN
        if self.battery is not None:
            self.battery.stop()
        if self.bus is not None:
            self.stop_and_close_bus()
        if self.lcms is not None:
            self.lcms.device.stop()

    def shutdown(self):
        """
        Shuts down the operating system if we are battery powered
        """
        if self.device_config.has_battery:
            logger.info("Shutting down...")
            os.system("sudo shutdown now")

    def _start_bus_monitoring(self):
        """
        Starts monitoring the CAN bus for events (esp. emergency and error events)
        """
        self.monitoring_thread = threading.Thread(target=self.monitor_events, name="BusMonitoringThread")
        self.monitoring_thread.start()

    # -------------------------------------------------------------------------
    # Bus
    def open_bus(self, exit: bool = True):
        """
        Opens the given device config and starts the bus communication

            :param exit: Whether to call `sys.exit` if opening fails or just pass on the error that ocurred
        """
        logger.info("Opening bus...")
        try:
            # If we're executed through python.exe the application dir is the
            # directory where python.exe is located. In order for the SDK to find
            # all plugins, nonetheless, we need to give it it's expected plugin
            # path.
            self.bus.open(str(self.device_config.path), os.path.join(CETONI_SDK_PATH, "plugins", "labbcan"))
        except qmixbus.DeviceError as err:
            logger.error("Could not open the bus communication: %s", err)
            if exit:
                sys.exit(1)
            else:
                raise err

    def start_bus_and_enable_devices(self):
        """
        Starts the bus communication and enables all devices
        """
        logger.info("Starting bus and enabling devices...")
        self.bus.start()
        self.enable_pumps()
        self.enable_axis_systems()

    def stop_and_close_bus(self):
        """
        Stops and closes the bus communication
        """
        logger.info("Closing bus...")
        if self.state.is_operational():
            self.bus.stop()
        self.bus.close()

    def monitor_events(self):
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
        while not self.state.shutting_down():
            time.sleep(1)

            event = self.bus.read_event()
            if event.is_valid():
                logger.debug(
                    f"event id: {event.event_id}, device handle: {event.device.handle}, "
                    f"node id: {event.device.get_node_id()}, data: {event.data}, message: {event.string}"
                )

                if self.state.is_operational() and is_dc_link_under_voltage_event(event):
                    self.state = SystemState.STOPPED
                    logger.info("System entered 'Stopped' state")
                    time.sleep(1)  # wait for the Atmel to catch up and detect the missing battery/external power
                    continue

            if self.state.is_stopped() and self.battery is not None and not self.battery.is_secondary_source_connected:
                seconds_stopped += 1
                if seconds_stopped > self.MAX_SECONDS_WITHOUT_BATTERY:
                    logger.info("Shutting down because battery has been removed for too long")
                    self.shutdown()

            if self.battery is not None:
                logger.debug(
                    f"heartbeat resolved: {is_heartbeat_err_resolved_event(event)}, bat conn: {self.battery.is_connected}, ext conn {self.battery.is_secondary_source_connected}"
                )
            else:
                logger.debug(
                    f"heartbeat resolved: {is_heartbeat_err_resolved_event(event)}"
                )

            if self.state.is_stopped() and is_heartbeat_err_resolved_event(event):
                self.state = SystemState.OPERATIONAL
                logger.info("System entered 'Operational' state")
                seconds_stopped = 0
                for device in self.device_config.devices:
                    logger.debug(f"Setting device {device} operational")
                    device.set_operational()
                    if isinstance(device, PumpDevice):
                        drive_pos_counter = Config(device.name, self.device_config.name).pump_drive_position_counter
                        if drive_pos_counter is not None and not device.is_position_sensing_initialized():
                            logger.debug(f"Restoring drive position counter: {drive_pos_counter}")
                            device.restore_position_counter_value(drive_pos_counter)

    # -------------------------------------------------------------------------
    # Pumps
    def get_availabe_pumps(self) -> List[PumpDevice]:
        """
        Looks up all pumps from the current configuration and constructs a list of
        all found pumps

        :return: A list of all found pumps
        """
        pump_count = qmixpump.Pump.get_no_of_pumps()
        logger.debug("Number of pumps: %s", pump_count)

        pumps = []

        for i in range(pump_count):
            pump = qmixpump.Pump()
            pump.lookup_by_device_index(i)
            pump_name = pump.get_device_name()
            logger.debug("Found pump %d named %s", i, pump_name)
            try:
                pump.get_device_property(qmixpump.ContiFlowProperty.SWITCHING_MODE)
                pump = qmixpump.ContiFlowPump(pump.handle)
                logger.debug("Pump %s is contiflow pump", pump_name)
            except qmixbus.DeviceError:
                pass
            pump_device = self.device_config.device_by_name(pump_name)
            PumpDevice.convert_to_class(pump_device, handle=pump.handle)
            pumps += [pump_device]

        return pumps

    def enable_pumps(self):
        """
        Enables all pumps
        """
        for pump in self.pumps:
            if pump.is_in_fault_state():
                pump.clear_fault()
            if not pump.is_enabled():
                pump.enable(True)

    # -------------------------------------------------------------------------
    # Motion Control
    def get_availabe_axis_systems(self) -> List[AxisSystemDevice]:
        """
        Looks up all axis systems connected to the bus

        :return: A list of all axis systems
        """

        system_count = qmixmotion.AxisSystem.get_axis_system_count()
        logger.debug("Number of axis systems: %s", system_count)

        axis_systems = []

        for i in range(system_count):
            axis_system = qmixmotion.AxisSystem()
            axis_system.lookup_by_device_index(i)
            axis_system_name = axis_system.get_device_name()
            logger.debug("Found axis system %d named %s", i, axis_system.get_device_name())
            axis_system_device = self.device_config.device_by_name(axis_system_name)
            AxisSystemDevice.convert_to_class(axis_system_device, handle=axis_system.handle)
            axis_systems += [axis_system_device]

        return axis_systems

    def enable_axis_systems(self):
        """
        Enables all axis systems
        """
        for axis_system in self.axis_systems:
            axis_system.enable(True)

    # -------------------------------------------------------------------------
    # Valves
    def get_availabe_valves(self) -> List[ValveDevice]:
        """
        Looks up all valves from the current configuration and maps them to their
        corresponding device

        :return: A list of all valves
        """

        valve_count = qmixvalve.Valve.get_no_of_valves()
        logger.debug("Number of valves: %s", valve_count)

        valves = []

        for i in range(valve_count):
            valve = qmixvalve.Valve()
            valve.lookup_by_device_index(i)
            try:
                valve_name = valve.get_device_name()
            except OSError:
                # When there are contiflow pumps in the config the corresponding
                # valves from the original syringe pumps are duplicated internally.
                # I.e. with one contiflow pump made up of two low pressure pumps
                # with their corresponding valves the total number of valves is
                # 4 despite of the actual 2 physical valves available. This leads
                # to an access violation error inside QmixSDK in case the device
                # name of one of the non-existent contiflow valves is requested.
                # We can fortunately mitigate this with this try-except here.
                continue
            logger.debug("Found valve %d named %s", i, valve_name)

            for device in self.device_config.devices:
                if device.name.rsplit("_Pump", 1)[0] in valve_name:
                    logger.debug(f"Valve {valve_name} belongs to device {device}")
                    if "QmixIO" in device.name:
                        # These valve devices are actually just convenience devices
                        # that operate on digital I/O channels. Hence, they can be
                        # just used via their corresponding I/O channel.
                        continue
                    device.valves += [valve]
                    if type(device) == Device:
                        ValveDevice.convert_to_class(device)
                        valves += [device]
        return valves

    # -------------------------------------------------------------------------
    # Controllers
    def get_availabe_controllers(self) -> List[ControllerDevice]:
        """
        Looks up all controller channels from the current configuration and maps
        them to their corresponding device

        :return: A list of all controller devices
        """
        channel_count = qmixcontroller.ControllerChannel.get_no_of_channels()
        logger.debug("Number of controller channels: %s", channel_count)

        channels = []

        for i in range(channel_count):
            channel = qmixcontroller.ControllerChannel()
            channel.lookup_channel_by_index(i)
            logger.debug("Found controller channel %d named %s", i, channel.get_name())
            channels.append(channel)

        return self.device_config.add_channels_to_device(channels)

    # -------------------------------------------------------------------------
    # I/O
    def get_availabe_io_channels(self) -> List[IODevice]:
        """
        Looks up all analog and digital I/O channels from the current configuration
        and maps them to their corresponding device

        :return: A list of all I/O channels
        """

        channels = []

        for (description, ChannelType) in {
            "analog in": qmixanalogio.AnalogInChannel,
            "analog out": qmixanalogio.AnalogOutChannel,
            "digital in": qmixdigio.DigitalInChannel,
            "digital out": qmixdigio.DigitalOutChannel,
        }.items():

            channel_count = ChannelType.get_no_of_channels()
            logger.debug("Number of %s channels: %s", description, channel_count)

            for i in range(channel_count):
                channel = ChannelType()
                channel.lookup_channel_by_index(i)
                channel_name = channel.get_name()
                logger.debug("Found %s channel %d named %s", description, i, channel_name)
                channels.append(channel)

        return self.device_config.add_channels_to_device(channels)

    # -------------------------------------------------------------------------
    # Balance
    def get_availabe_balances(self) -> List[BalanceDevice]:
        """
        Looks up all balances from the current configuration

        :return: A list of all balance devices
        """

        try:
            from sila_cetoni.balance.device_drivers import sartorius_balance
        except (ModuleNotFoundError, ImportError):
            logger.info("Could not find sila_cetoni.balance package - no support for balance devices!")
            return []

        # for now we assume that at most one balance is connected until we get
        # proper balance support in the SDK
        balance_count = 1
        logger.debug("Number of balances: %s", balance_count)

        balances = []

        for i in range(balance_count):
            bal = sartorius_balance.SartoriusBalance()
            try:
                bal.open()
            except sartorius_balance.BalanceNotFoundException:
                continue
            # 'guess' the balance name for now
            balance_name = f"Sartorius_Balance_{i+1}"
            logger.debug("Found balance %d named %s", i, balance_name)
            if self.device_config:
                balance_device = self.device_config.device_by_name(balance_name)
                BalanceDevice.convert_to_class(balance_device, device=bal)
            else:
                balance_device = BalanceDevice(balance_name, bal)
            balances += [balance_device]

        return balances

    # -------------------------------------------------------------------------
    # LC/MS
    def get_availabe_lcms(self) -> Optional[LCMSDevice]:
        """
        Checks for a possible LC/MS device and returns it if found

        :return: The connected LC/MS device if there is one

        :note: We currently only support a single LC/MS device
        """

        try:
            from sila_cetoni.lcms.device_drivers import shimadzu_lcms2020
        except (ModuleNotFoundError, ImportError):
            logger.info("Could not find sila_cetoni.lcms package - no support for LC/MS devices!")
            return None

        logger.debug("Looking for LC/MS")

        lcms = shimadzu_lcms2020.ShimadzuLCMS2020()
        try:
            lcms.open()
            logger.debug("Found LC/MS named %s", lcms.instrument_name)
            return LCMSDevice(lcms.instrument_name, lcms)
        except shimadzu_lcms2020.LabSolutionsStartException:
            pass
