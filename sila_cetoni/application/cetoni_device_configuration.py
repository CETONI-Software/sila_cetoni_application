from __future__ import annotations

import logging
import os
import re
import sys
from pathlib import Path
from typing import List, Union

from lxml import etree, objectify

# import qmixsdk
from qmixsdk import qmixanalogio, qmixbus, qmixcontroller, qmixdigio, qmixmotion, qmixpump, qmixvalve
from sila_cetoni.config import CETONI_SDK_PATH

from .configuration import DeviceConfiguration
from .device import (
    AxisSystemDevice,
    CetoniAxisSystemDevice,
    CetoniControllerDevice,
    CetoniDevice,
    CetoniIODevice,
    CetoniPumpDevice,
    CetoniValveDevice,
    ControllerDevice,
    IODevice,
    PumpDevice,
    ValveDevice,
)

logger = logging.getLogger(__name__)


class CetoniDeviceConfiguration(DeviceConfiguration[CetoniDevice]):
    """
    A special device configuration for CETONI devices

    It parses (and thus represents the contents of) a CETONI device configuration folder.
    """

    __bus: qmixbus.Bus
    _has_battery: bool

    def __init__(self, name: str, config_file_path: Path) -> None:
        super().__init__(name, config_file_path)

    def _parse(self) -> None:
        """
        Parses the device configuration
        """

        self.__bus = qmixbus.Bus()
        self.__open_bus()

        # The order is important here! Many devices have I/O channels but are not pure I/O devices (similarly, pumps
        # might have a valve but they're not a valve device). That's why valves have to be detected after pumps and I/O
        # devices have to be detected last (since then we can guarantee that there is no possibility for an I/O channel
        # to belong to an I/O device).
        self.__create_pump_devices()
        self.__create_axis_systems_devices()
        self.__create_valve_devices()
        self.__create_controller_devices()
        self.__create_io_devices()

        logger.debug(f"Parsing device configuration {self._file_path}")

        tree: objectify.ObjectifiedElement
        with open(os.path.join(self._file_path, "device_properties.xml")) as f:
            tree = objectify.parse(f)
        root = tree.getroot()
        for plugin in root.Core.PluginList.iterchildren():
            if plugin.text in (
                "qmixelements",
                "scriptingsystem",
                "labbcanservice",
                "canopentools",
                "qmixdevices",
                "datalogger",
            ):
                # these files are the only ones with UTF-8 w/ BOM which leads to an error while parsing the file; since
                # we don't need them anyway we can skip them
                continue

            self._parse_plugin(plugin.text)

        logger.debug(f"Found the following devices: {self._devices}")

        self._has_battery = bool(getattr(root, "SiLA.BatteryPowered", False))

    def _parse_plugin(self, plugin_name: str):
        """
        Parses the configuration for the plugin named `plugin_name`

        :param plugin_name: The name of the plugin to parse
        """
        logger.debug(f"Parsing configuration for {plugin_name} plugin")
        # we need to create a new parser that parses our 'broken' XML files
        # (they are regarded as 'broken' because they contain multiple root tags)
        parser: etree.XMLParser = objectify.makeparser(recover=True, remove_comments=True)
        with open(os.path.join(self._file_path, plugin_name + ".xml")) as f:
            # wrap the 'broken' XML in a new <root> so that we can parse the
            # whole document instead of just the first root
            lines = f.readlines()
            fixed_xml = bytes(lines[0] + "<root>" + "".join(lines[1:]) + "</root>", "utf-8")

            plugin_tree: objectify.ObjectifiedElement = objectify.fromstring(fixed_xml, parser)
            plugin_root: objectify.ObjectifiedElement = plugin_tree.Plugin

            # only parse the things we don't get from the SDK's API

            if "rotaxys" in plugin_name:
                device: objectify.ObjectifiedElement  # only for typing
                for device in plugin_root.DeviceList.iterchildren():
                    try:
                        # no possibility to find the jib length elsewhere
                        self.device_by_name(device.get("Name")).set_device_property(
                            "jib_length", abs(int(device.JibLength.text))
                        )
                    except ValueError:
                        pass
            if "tubingpump" in plugin_name:
                device: objectify.ObjectifiedElement  # only for typing
                for device in plugin_root.labbCAN.DeviceList.iterchildren():
                    try:
                        # no other way to identify a peristaltic pump
                        setattr(self.device_by_name(device.get("Name")), "is_peristaltic_pump", True)
                    except ValueError:
                        pass

    def device_by_name(self, name: str):
        """
        Retrieves a Device by its name

        Raises ValueError if there is no Device with the `name` present.

        :param name: The name of the device to get
        :return: The Device with the given `name`
        """
        for device in self._devices:
            if name == device.name:
                return device
        raise ValueError(f"No device with name {name}")

    # -------------------------------------------------------------------------
    # Bus
    def __open_bus(self, exit: bool = True):
        """
        Opens the given device config and starts the bus communication

            :param exit: Whether to call `sys.exit` if opening fails or just pass on the error that occurred
        """
        logger.info("Opening bus...")
        try:
            # If we're executed through python.exe the application dir is the
            # directory where python.exe is located. In order for the SDK to find
            # all plugins, nonetheless, we need to give it it's expected plugin
            # path.
            self.__bus.open(str(self.file_path), os.path.join(CETONI_SDK_PATH, "plugins", "labbcan"))
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
        self.__bus.start()
        self.enable_pumps()
        self.enable_axis_systems()

    def read_bus_event(self) -> qmixbus.Event:
        return self.__bus.read_event()

    def stop_bus(self):
        """
        Stops the bus communication
        """
        self.__bus.stop()

    def close_bus(self):
        """
        Closes the bus communication
        """
        self.__bus.close()

    # -------------------------------------------------------------------------
    # Pumps
    def __create_pump_devices(self):
        """
        Looks up all pumps from the current configuration and adds them as `CetoniPumpDevice` to the device list
        """
        pump_count = qmixpump.Pump.get_no_of_pumps()
        logger.debug("Number of pumps: %s", pump_count)

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
            self._devices += [CetoniPumpDevice(pump_name, pump)]

    def enable_pumps(self):
        """
        Enables all pumps
        """
        pump: CetoniPumpDevice
        for pump in filter(lambda d: isinstance(d, CetoniPumpDevice), self._devices):
            if pump.device_handle.is_in_fault_state():
                pump.device_handle.clear_fault()
            if not pump.device_handle.is_enabled():
                pump.device_handle.enable(True)

    # -------------------------------------------------------------------------
    # Motion Control
    def __create_axis_systems_devices(self):
        """
        Looks up all axis systems from the current configuration and adds them as `CetoniAxisSystemDevice` to the device
        list
        """

        system_count = qmixmotion.AxisSystem.get_axis_system_count()
        logger.debug("Number of axis systems: %s", system_count)

        for i in range(system_count):
            axis_system = qmixmotion.AxisSystem()
            axis_system.lookup_by_device_index(i)
            axis_system_name = axis_system.get_device_name()
            logger.debug("Found axis system %d named %s", i, axis_system.get_device_name())
            self._devices += [CetoniAxisSystemDevice(axis_system_name, axis_system)]

    def enable_axis_systems(self):
        """
        Enables all axis systems
        """
        axis_system: CetoniAxisSystemDevice
        for axis_system in filter(lambda d: isinstance(d, CetoniAxisSystemDevice), self._devices):
            axis_system.device_handle.enable(True)

    # -------------------------------------------------------------------------
    # Valves
    def __create_valve_devices(self):
        """
        Looks up all valves from the current configuration and adds them as `CetoniValveDevice` to the device list
        """

        valve_count = qmixvalve.Valve.get_no_of_valves()
        logger.debug("Number of valves: %s", valve_count)

        for i in range(valve_count):
            valve = qmixvalve.Valve()
            valve.lookup_by_device_index(i)
            try:
                valve_name = valve.get_device_name()
            except OSError:
                # When there are contiflow pumps in the config the corresponding  valves from the original syringe pumps
                # are duplicated internally.  I.e. with one contiflow pump made up of two low pressure pumps  with their
                # corresponding valves the total number of valves is  4 despite of the actual 2 physical valves
                # available. This leads  to an access violation error inside QmixSDK in case the device  name of one of
                # the non-existent contiflow valves is requested.  We can fortunately mitigate this with this try-except
                # here.
                continue
            logger.debug("Found valve %d named %s", i, valve_name)

            for device in self._devices:
                if device.name.rsplit("_Pump", 1)[0] in valve_name:
                    logger.debug(f"Valve {valve_name} belongs to device {device}")
                    if "QmixIO" in device.name:
                        # These valve devices are actually just convenience devices that operate on digital I/O
                        # channels. Hence, they can be just used via their corresponding I/O channel.
                        continue
                    device.valves += [valve]
                    break
            else:
                device_name = re.match(r".*(?=_Valve\d?$)", valve_name).group()
                if "QmixIO" in device_name:
                    # These valve devices are actually just convenience devices that operate on digital I/O
                    # channels. Hence, they can be just used via their corresponding I/O channel.
                    continue
                logger.debug(f"Standalone valve device {device_name}")
                device = CetoniValveDevice(device_name)
                logger.debug(f"Valve {valve_name} belongs to device {device}")
                device.valves += [valve]
                self._devices += [device]

    # -------------------------------------------------------------------------
    # Controllers
    def __create_controller_devices(self) -> List[ControllerDevice]:
        """
        Looks up all controllers from the current configuration and adds them as `CetoniControllerDevice` to the device
        list
        """
        channel_count = qmixcontroller.ControllerChannel.get_no_of_channels()
        logger.debug("Number of controller channels: %s", channel_count)

        channels = []

        for i in range(channel_count):
            channel = qmixcontroller.ControllerChannel()
            channel.lookup_channel_by_index(i)
            logger.debug("Found controller channel %d named %s", i, channel.get_name())
            channels.append(channel)

        self.add_channels_to_device(channels)

    # -------------------------------------------------------------------------
    # I/O
    def __create_io_devices(self) -> List[IODevice]:
        """
        Looks up all I/Os from the current configuration and adds them as `CetoniIODevice` to the device list
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

        self.add_channels_to_device(channels)

    def add_channels_to_device(
        self,
        channels: List[Union[qmixcontroller.ControllerChannel, qmixanalogio.AnalogChannel, qmixdigio.DigitalChannel]],
    ):
        """
        A device might have controller or I/O channels. This relationship between a device and its channels is
        constructed here.

        If a device is not of a specific type yet (i.e. it's not a `CetoniPumpDevice`, `CetoniAxisSystemDevice` or
        `CetoniValveDevice`) it is converted to either a `CetoniControllerDevice` or a `CetoniIODevice` depending on the
        type of the channel.

        :param channels: A list of channels that should be mapped to their corresponding devices
        """

        for channel in channels:
            channel_name = channel.get_name()
            for device in self._devices:
                if device.name.rsplit("_Pump", 1)[0] in channel_name:
                    logger.debug(f"Channel {channel_name} belongs to device {device}")
                    if isinstance(channel, qmixcontroller.ControllerChannel):
                        device.controller_channels += [channel]
                    else:
                        device.io_channels += [channel]
                    break
            else:
                if isinstance(channel, qmixcontroller.ControllerChannel):
                    device_name = re.match(
                        r".*(?=(_Temperature)|(_ReactionLoop)|(_ReactorZone)|(_Ctrl)\d?$)", channel_name
                    ).group()
                    logger.debug(f"Standalone controller device {device_name}")
                    device = CetoniControllerDevice(device_name)
                    logger.debug(f"Channel {channel_name} belongs to device {device}")
                    device.controller_channels += [channel]
                    self._devices += [device]
                else:
                    # https://regexr.com/6pv74
                    device_name = re.match(
                        r".*(?=((_TC)|(_AI)|(_AnIN)|(_AO)|(_DI)|(_DigIN)|(_DO)|(_DigOUT))\w{1}"
                        r"((((_IN)|(_DIAG))\w{1,2})|((_PWM)|(_PT100)))?$)",
                        channel_name,
                    ).group()
                    logger.debug(f"Standalone I/O device {device_name}")
                    device = CetoniIODevice(device_name)
                    logger.debug(f"Channel {channel_name} belongs to device {device}")
                    device.io_channels += [channel]
                    self._devices += [device]

    @property
    def has_battery(self) -> bool:
        return self._has_battery

    def __str__(self) -> str:
        return super().__str__() + f"\b, has_battery: {self._has_battery})"
