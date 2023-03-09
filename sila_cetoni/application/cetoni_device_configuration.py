from __future__ import annotations

import logging
import os
import re
import sys
from pathlib import Path
from typing import Dict

from lxml import etree, objectify
from qmixsdk import qmixbus

from sila_cetoni.config import CETONI_SDK_PATH
from sila_cetoni.pkgutil import SiLACetoniFirstPartyPackage, available_packages

from .configuration import DeviceConfiguration
from .device import CetoniDevice

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

        logger.debug(f"Parsing device configuration {self._file_path}")

        tree: objectify.ObjectifiedElement
        with open(os.path.join(self._file_path, "device_properties.xml")) as f:
            tree = objectify.parse(f)
        root = tree.getroot()

        try:
            self._has_battery = bool(root.SiLA.BatteryPowered)
        except AttributeError:
            self._has_battery = False

        # The order is important here! Many devices have I/O channels but are not pure I/O devices (similarly, pumps
        # might have a valve but they're not a valve device). That's why valves have to be detected after pumps and I/O
        # devices have to be detected last (since then we can guarantee that there is no possibility for an I/O channel
        # to not belong to an I/O device).
        self._devices = []
        available_pkgs: Dict[str, SiLACetoniFirstPartyPackage] = available_packages()
        try:
            self._devices.extend(available_pkgs["sila_cetoni.pumps"].create_devices(self))
            self._devices.extend(available_pkgs["sila_cetoni.motioncontrol"].create_devices(self))
            self._devices.extend(available_pkgs["sila_cetoni.mobdos"].create_devices(self))
            self._devices.extend(available_pkgs["sila_cetoni.valves"].create_devices(self))
            self._devices.extend(available_pkgs["sila_cetoni.controllers"].create_devices(self))
            self._devices.extend(available_pkgs["sila_cetoni.io"].create_devices(self))
        except KeyError as err:
            logger.error(f"Failed to create devices because the {err.args[0]!r} package is not installed")
        except Exception as err:
            logger.error(f"Unexpected exception during device creation: {err}", exc_info=err)

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
            # add SDK path and plugin path to PATH env variable to enable proper loading of shared libraries
            os.environ["PATH"] = os.pathsep.join(
                [CETONI_SDK_PATH, os.path.join(CETONI_SDK_PATH, "plugins", "labbcan"), os.environ["PATH"]]
            )
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

    def enable_pumps(self):
        """
        Enables all pumps
        """
        from sila_cetoni.pumps import CetoniPumpDevice

        pump: CetoniPumpDevice  # typing
        for pump in filter(lambda d: isinstance(d, CetoniPumpDevice), self._devices):
            if pump.device_handle.is_in_fault_state():
                pump.device_handle.clear_fault()
            if not pump.device_handle.is_enabled():
                pump.device_handle.enable(True)

    def enable_axis_systems(self):
        """
        Enables all axis systems
        """
        from sila_cetoni.motioncontrol import CetoniAxisSystemDevice

        axis_system: CetoniAxisSystemDevice  # typing
        for axis_system in filter(lambda d: isinstance(d, CetoniAxisSystemDevice), self._devices):
            axis_system.device_handle.enable(True)

    @property
    def has_battery(self) -> bool:
        return self._has_battery

    def __str__(self) -> str:
        return super().__str__() + f"\b, has_battery: {self._has_battery})"
