from __future__ import annotations

import json
import logging
import os
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import jsonschema
import jsonschema.exceptions
from isodate import parse_duration

from sila_cetoni.device_driver_abc import DeviceDriverABC
from sila_cetoni.package_util import available_packages

from ..application import resource_dir
from .configuration import DeviceConfiguration
from .device import ThirdPartyDevice
from .local_ip import LOCAL_IP

CONFIG_SCHEMA_FILE_NAME = "configuration_schema.json"
SCHEMA: Dict
with open(Path((resource_dir)).joinpath(CONFIG_SCHEMA_FILE_NAME), "rt") as schema_file:
    SCHEMA = json.load(schema_file)

__all__ = ["SCHEMA", "ApplicationConfiguration"]

logger = logging.getLogger(__name__)


def load_available_add_on_schemas():
    """
    Loads the JSON schemas for the application configuration file for all available add-on packages and appends them to
    the core JSON `SCHEMA`
    """

    schema_definitions: Dict = SCHEMA["definitions"]
    schema_definitions_device: List = SCHEMA["definitions"]["Device"]["allOf"]

    SCHEMA_REF_INSERT_POINT = {"$comment": "@addOnsRefInsertPoint"}

    for name, package in available_packages().items():
        schema_file_path = os.path.join(os.path.dirname(package.__file__), "resources", CONFIG_SCHEMA_FILE_NAME)
        if not os.path.exists(schema_file_path):
            continue
        with open(schema_file_path, "rt") as schema_file:
            add_on_schema = json.load(schema_file)
            logger.info(f"Appending JSON schema for package {name!r}")
            schema_definitions.update(add_on_schema["definitions"])
            schema_definitions_device.insert(
                schema_definitions_device.index(SCHEMA_REF_INSERT_POINT), {"$ref": add_on_schema["$ref"]}
            )

    logger.debug(f"Final Schema: {json.dumps(SCHEMA)}")


class JSONWithCommentsDecoder(json.JSONDecoder):
    """
    A JSON decoder that strips line comments (lines starting with '//') from a JSON file while decoding

    https://stackoverflow.com/a/72168909/12780516
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def decode(self, s: str) -> Any:
        s = "\n".join(l if not l.lstrip().startswith("//") else "" for l in s.split("\n"))
        return super().decode(s)


class ApplicationConfiguration(DeviceConfiguration[ThirdPartyDevice[DeviceDriverABC]]):
    """
    The device configuration for sila_cetoni based applications

    It parses (and thus represents the contents of) a config.json file.
    """

    __version: int
    __server_ip: str
    __server_base_port: int
    __server_base_port_cli_overwrite: bool
    __enable_discovery: bool
    __log_level: str
    __log_file_dir: Optional[Path]
    __regenerate_certificates: bool
    __scan_devices: bool
    __simulate_missing: bool
    __sila: bool
    __remote_objects: bool
    __json_devices: Optional[Dict[str, Dict]]
    __cetoni_device_config_path: Optional[Path]
    __cetoni_max_time_without_battery: timedelta
    __cetoni_max_time_without_traffic: timedelta

    __SCHEMA_PROPERTIES = SCHEMA["definitions"]["DeviceConfiguration"]["properties"]
    DEFAULT_SERVER_IP: str = LOCAL_IP
    DEFAULT_SERVER_BASE_PORT: int = int(__SCHEMA_PROPERTIES["server_base_port"]["default"])
    DEFAULT_ENABLE_DISCOVERY: bool = bool(__SCHEMA_PROPERTIES["enable_discovery"]["default"])
    DEFAULT_LOG_LEVEL: str = __SCHEMA_PROPERTIES["log_level"]["default"]
    DEFAULT_REGENERATE_CERTIFICATES: bool = __SCHEMA_PROPERTIES["regenerate_certificates"]["default"]
    DEFAULT_SCAN_DEVICES: bool = __SCHEMA_PROPERTIES["scan_devices"]["default"]
    DEFAULT_SIMULATE_MISSING: bool = __SCHEMA_PROPERTIES["simulate_missing"]["default"]
    DEFAULT_SILA: bool = True  # __SCHEMA_PROPERTIES["sila"]["default"]
    DEFAULT_REMOTE_OBJECTS: bool = False  # __SCHEMA_PROPERTIES["remote_objects"]["default"]

    __CETONI_SCHEMA_PROPERTIES = SCHEMA["definitions"]["CetoniDevices"]["properties"]
    DEFAULT_MAX_TIME_WITHOUT_BATTERY: timedelta = parse_duration(
        __CETONI_SCHEMA_PROPERTIES["max_time_without_battery"]["default"]
    )
    DEFAULT_MAX_TIME_WITHOUT_TRAFFIC: timedelta = parse_duration(
        __CETONI_SCHEMA_PROPERTIES["max_time_without_traffic"]["default"]
    )

    def __init__(self, name: str, config_file_path: Path) -> None:
        load_available_add_on_schemas()

        super().__init__(name, config_file_path)

    def _parse(self) -> None:
        try:
            with open(self._file_path, "r") as config_file:
                config: dict = json.load(config_file, cls=JSONWithCommentsDecoder)

                jsonschema.validate(config, SCHEMA)
                logger.debug(f"JSON config {config}")
                # required properties
                self.__version = config["version"]
                self.__json_devices = config.get("devices", None)
                self.__cetoni_device_config_path = (
                    Path(config["cetoni_devices"]["device_config_path"]) if "cetoni_devices" in config else None
                )
                # optional properties -> default values from schema
                self.__server_ip = config.get("server_ip", self.DEFAULT_SERVER_IP)
                self.__server_base_port = int(config.get("server_base_port", self.DEFAULT_SERVER_BASE_PORT))
                self.__server_base_port_cli_overwrite = False
                self.__enable_discovery = bool(config.get("enable_discovery", self.DEFAULT_ENABLE_DISCOVERY))
                self.__log_level = config.get("log_level", self.DEFAULT_LOG_LEVEL)
                self.__log_file_dir = Path(config["log_file_dir"]) if "log_file_dir" in config else None
                self.__regenerate_certificates = config.get(
                    "regenerate_certificates", self.DEFAULT_REGENERATE_CERTIFICATES
                )
                self.__scan_devices = config.get("scan_devices", self.DEFAULT_SCAN_DEVICES)
                self.__simulate_missing = config.get("simulate_missing", self.DEFAULT_SIMULATE_MISSING)
                # sila not yet supported by the schema, only via CLI flag
                self.__sila = config.get("sila", self.DEFAULT_SILA)
                # remote_objects not yet supported by the schema, only via CLI flag
                self.__remote_objects = config.get("remote_objects", self.DEFAULT_REMOTE_OBJECTS)

                try:
                    self.__cetoni_max_time_without_battery = parse_duration(
                        config["cetoni_devices"]["max_time_without_battery"]
                    )
                except KeyError:
                    self.__cetoni_max_time_without_battery = self.DEFAULT_MAX_TIME_WITHOUT_BATTERY
                try:
                    self.__cetoni_max_time_without_traffic = parse_duration(
                        config["cetoni_devices"]["max_time_without_traffic"]
                    )
                except KeyError:
                    self.__cetoni_max_time_without_traffic = self.DEFAULT_MAX_TIME_WITHOUT_TRAFFIC
        except (OSError, ValueError, jsonschema.exceptions.ValidationError) as err:
            raise RuntimeError(f"Configuration file {self._file_path} is invalid: {err}")

    def sanity_check(self) -> None:
        """
        Performs a sanity check of all configured options and raises `ValueError` if there are any problems
        """
        if self.__sila and self.__remote_objects:
            raise ValueError(
                "Both sila and remote_objects are enabled but currently it is only supported to run either SiLA 2 "
                "server or use Qt remote objects"
            )
        if not self.__sila and not self.__remote_objects:
            raise ValueError("Neither sila nor remote_objects are enabled - this makes no sense")

    def parse_devices(self):
        logger.debug(f"JSON devices {self.__json_devices}")
        self._devices = []
        for package in available_packages().values():
            # fmt: off
            self._devices.extend(package.parse_devices(self.__json_devices))  # type: ignore "Device" is incompatible
                                                                              # with "ThirdPartyDevice[DeviceDriverABC]"
            # fmt: on

    def __str__(self) -> str:
        return (
            super().__str__() + f", version: {self.__version}, server_ip: {self.__server_ip}, "
            f"server_base_port: {self.__server_base_port}, log_level: {self.__log_level}, "
            f"regenerate_certificates: {self.__regenerate_certificates}, scan_devices: {self.__scan_devices}, "
            f"simulate_missing: {self.__simulate_missing}"
        )

    @property
    def version(self) -> int:
        """
        The version of the configuration file
        """
        return self.__version

    @property
    def server_ip(self) -> str:
        """
        The IP address on which to start the SiLA Servers (defaults to the local IP address)
        """
        return self.__server_ip

    @server_ip.setter
    def server_ip(self, server_ip: str):
        """
        Sets the `server_ip` property but only if the given `server_ip` is not the default value of this property
        """
        if server_ip is not self.DEFAULT_SERVER_IP:
            logger.warning(f"Overwriting server_ip with {server_ip!r} (was {self.server_ip!r})")
            self.__server_ip = server_ip

    @property
    def server_base_port(self) -> int:
        """
        The port number for the first SiLA Server
        """
        return self.__server_base_port

    @server_base_port.setter
    def server_base_port(self, server_base_port: int):
        """
        Sets the `server_base_port` property but only if the given `server_base_port` is not the default value of this
        property
        """
        if server_base_port is not self.DEFAULT_SERVER_BASE_PORT:
            logger.warning(f"Overwriting server_base_port with {server_base_port!r} (was {self.server_base_port!r})")
            self.__server_base_port_cli_overwrite = True
            self.__server_base_port = server_base_port

    @property
    def server_base_port_cli_overwrite(self) -> bool:
        """
        Whether the server_base_port was overwritten via the CLI
        """
        return self.__server_base_port_cli_overwrite

    @property
    def enable_discovery(self) -> bool:
        """
        Enable or disable discovery of all SiLA Servers (whether they announce themselves in the network)
        """
        return self.__enable_discovery

    @enable_discovery.setter
    def enable_discovery(self, enable_discovery: bool) -> None:
        """
        Sets the `enable_discovery` property but only if the given `enable_discovery` value is not the default value of
        this property
        """
        if enable_discovery is not self.DEFAULT_ENABLE_DISCOVERY:
            logger.warning(f"Overwriting enable_discovery with {enable_discovery!r} (was {self.enable_discovery!r})")
            self.__enable_discovery = enable_discovery

    @property
    def log_level(self) -> str:
        """
        The logging level of the application
        """
        return self.__log_level

    @log_level.setter
    def log_level(self, log_level: str):
        """
        Sets the `log_level` property but only if the given `log_level` is not the default value of this property
        """
        if log_level is not self.DEFAULT_LOG_LEVEL:
            logger.warning(f"Overwriting log_level with {log_level!r} (was {self.__log_level!r})")
            self.__log_level = log_level

    @property
    def log_file_dir(self) -> Optional[Path]:
        """
        The directory to write log files to (if not given log messages will only be printed to standard out)
        """
        return self.__log_file_dir

    @log_file_dir.setter
    def log_file_dir(self, log_file_dir: Path):
        """
        Sets the `log_file_dir` property
        """
        logger.warning(f"Overwriting log_file_dir with {log_file_dir!r} (was {self.__log_file_dir!r})")
        self.__log_file_dir = log_file_dir

    @property
    def regenerate_certificates(self) -> bool:
        """
        Whether to force regeneration of the self-signed certificates (e.g. if the IP address of the machine running the
        servers changed)
        """
        return self.__regenerate_certificates

    @regenerate_certificates.setter
    def regenerate_certificates(self, regenerate_certificates: bool):
        """
        Sets the `regenerate_certificates` property but only if the given `regenerate_certificates` is not the default
        value of this property
        """
        if regenerate_certificates is not self.DEFAULT_REGENERATE_CERTIFICATES:
            logger.warning(
                f"Overwriting regenerate_certificates with {regenerate_certificates!r} (was "
                f"{self.regenerate_certificates!r})"
            )
            self.__regenerate_certificates = regenerate_certificates

    @property
    def scan_devices(self) -> bool:
        """
        Whether to automatically scan for supported connected devices (e.g. scan for available Sartorius balances if the
        sila_cetoni_balance package is installed)
        """
        return self.__scan_devices

    @scan_devices.setter
    def scan_devices(self, scan_devices: bool):
        """
        Sets the `scan_devices` property but only if the given `scan_devices` is not the default value of this property
        """
        if scan_devices is not self.DEFAULT_SCAN_DEVICES:
            logger.warning(f"Overwriting scan_devices with {scan_devices!r} (was {self.scan_devices!r})")
            self.__scan_devices = scan_devices

    @property
    def simulate_missing(self) -> bool:
        """
        Whether to try and simulate devices which are not explicitly set to 'simulated' in the config file if the
        application cannot connect to them
        """
        return self.__simulate_missing

    @simulate_missing.setter
    def simulate_missing(self, simulate_missing: bool):
        """
        Sets the `simulate_missing` property but only if the given `simulate_missing` is not the default value of this
        property
        """
        if simulate_missing is not self.DEFAULT_SIMULATE_MISSING:
            logger.warning(f"Overwriting simulate_missing with {simulate_missing!r} (was {self.simulate_missing!r})")
            self.__simulate_missing = simulate_missing

    @property
    def sila(self) -> bool:
        """
        Whether to try and simulate devices which are not explicitly set to 'simulated' in the config file if the
        application cannot connect to them
        """
        return self.__sila

    @sila.setter
    def sila(self, sila: bool):
        """
        Sets the `sila` property but only if the given `sila` is not the default value of this
        property
        """
        if sila is not self.DEFAULT_SILA:
            logger.warning(f"Overwriting sila with {sila!r} (was {self.sila!r})")
            self.__sila = sila

    @property
    def remote_objects(self) -> bool:
        """
        Whether to try and simulate devices which are not explicitly set to 'simulated' in the config file if the
        application cannot connect to them
        """
        return self.__remote_objects

    @remote_objects.setter
    def remote_objects(self, remote_objects: bool):
        """
        Sets the `remote_objects` property but only if the given `remote_objects` is not the default value of this
        property
        """
        if remote_objects is not self.DEFAULT_REMOTE_OBJECTS:
            logger.warning(f"Overwriting remote_objects with {remote_objects!r} (was {self.remote_objects!r})")
            self.__remote_objects = remote_objects

    @property
    def cetoni_device_config_path(self) -> Optional[Path]:
        """
        The path to the CETONI device configuration folder if present in the configuration
        """
        return self.__cetoni_device_config_path

    @property
    def cetoni_max_time_without_battery(self) -> timedelta:
        """
        How long the device will stay on at most without a battery (default: 20 seconds)

        Note
        ----
        This is a property only used for the battery powered CETONI mobile dosage units
        """
        return self.__cetoni_max_time_without_battery

    @property
    def cetoni_max_time_without_traffic(self) -> timedelta:
        """
        How long the device will stay on without any SiLA Command calls or Property requests to non-standard features
        (default: 10 minutes)

        Note
        ----
        This is a property only used for the battery powered CETONI mobile dosage units
        """
        return self.__cetoni_max_time_without_traffic
