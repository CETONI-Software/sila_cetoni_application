import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

import jsonschema
import jsonschema.exceptions

from ..application import resource_dir

SCHEMA: Dict
with open(Path((resource_dir)).joinpath("configuration_schema.json"), "rt") as schema_file:
    SCHEMA = json.load(schema_file)

from .configuration import DeviceConfiguration
from .device import ThirdPartyDevice
from .local_ip import LOCAL_IP

logger = logging.getLogger(__name__)


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


class ApplicationConfiguration(DeviceConfiguration[ThirdPartyDevice]):
    """
    The device configuration for sila_cetoni based applications

    It parses (and thus represents the contents of) a config.json file.
    """

    __version: int
    __server_ip: str
    __server_base_port: int
    __log_level: str
    __log_file_dir: Optional[Path]
    __regenerate_certificates: bool
    __scan_devices: bool
    __cetoni_device_config_path: Optional[Path]

    __SCHEMA_PROPERTIES = SCHEMA["definitions"]["DeviceConfiguration"]["properties"]
    DEFAULT_SERVER_IP: str = LOCAL_IP
    DEFAULT_SERVER_BASE_PORT: int = int(__SCHEMA_PROPERTIES["server_base_port"]["default"])
    DEFAULT_LOG_LEVEL: str = __SCHEMA_PROPERTIES["log_level"]["default"]
    DEFAULT_REGENERATE_CERTIFICATES: bool = __SCHEMA_PROPERTIES["regenerate_certificates"]["default"]
    DEFAULT_SCAN_DEVICES: bool = __SCHEMA_PROPERTIES["scan_devices"]["default"]

    def __init__(self, name: str, config_file_path: Path) -> None:
        super().__init__(name, config_file_path)

    def _parse(self) -> None:
        try:
            with open(self._file_path, "r") as config_file:
                config: dict = json.load(config_file, cls=JSONWithCommentsDecoder)

                jsonschema.validate(config, SCHEMA)
                logger.debug(f"JSON config {config}")
                # required properties
                self.__version = config["version"]
                self.__parse_devices(config.get("devices", None))
                self.__cetoni_device_config_path = (
                    Path(config["cetoni_devices"]["device_config_path"]) if "cetoni_devices" in config else None
                )
                # optional properties -> default values from schema
                self.__server_ip = config.get("server_ip", self.DEFAULT_SERVER_IP)
                self.__server_base_port = int(config.get("server_base_port", self.DEFAULT_SERVER_BASE_PORT))
                self.__log_level = config.get("log_level", self.DEFAULT_LOG_LEVEL)
                self.__log_file_dir = Path(config["log_file_dir"]) if "log_file_dir" in config else None
                self.__regenerate_certificates = config.get(
                    "regenerate_certificates", self.DEFAULT_REGENERATE_CERTIFICATES
                )
                self.__scan_devices = config.get("scan_devices", self.DEFAULT_SCAN_DEVICES)
        except (OSError, ValueError, jsonschema.exceptions.ValidationError) as err:
            raise RuntimeError(f"Configuration file {self._file_path} is invalid: {err}", exc_info=err)

    def __parse_devices(self, devices: Optional[Dict[str, Dict]]):
        logger.debug(f"JSON devices {devices}")
        self._devices = []
        if devices is not None:
            for device in devices:
                try:
                    self._devices.append(ThirdPartyDevice(device, devices[device]))
                except KeyError as err:
                    raise RuntimeError(f"Failed to parse device {device!r}: Expected property {err} could not be found")

    def __str__(self) -> str:
        return (
            super().__str__() + f", version: {self.__version}, server_ip: {self.__server_ip}, "
            f"server_base_port: {self.__server_base_port}, log_level: {self.__log_level}, "
            f"regenerate_certificates: {self.__regenerate_certificates}, scan_devices: {self.__scan_devices}"
        )

    @property
    def version(self) -> int:
        return self.__version

    @property
    def server_ip(self) -> str:
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
        return self.__server_base_port

    @server_base_port.setter
    def server_base_port(self, server_base_port: int):
        """
        Sets the `server_base_port` property but only if the given `server_base_port` is not the default value of this
        property
        """
        if server_base_port is not self.DEFAULT_SERVER_BASE_PORT:
            logger.warning(f"Overwriting server_base_port with {server_base_port!r} (was {self.server_base_port!r})")
            self.__server_base_port = server_base_port

    @property
    def log_level(self) -> str:
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
        return self.__log_file_dir

    @log_file_dir.setter
    def log_file_dir(self, log_file_dir: Path):
        logger.warning(f"Overwriting log_file_dir with {log_file_dir!r} (was {self.__log_file_dir!r})")
        self.__log_file_dir = log_file_dir

    @property
    def regenerate_certificates(self) -> bool:
        return self.__regenerate_certificates

    @regenerate_certificates.setter
    def regenerate_certificates(self, regenerate_certificates: bool):
        """
        Sets the `regenerate_certificates` property but only if the given `regenerate_certificates` is not the default
        value of this property
        """
        if regenerate_certificates is not self.DEFAULT_REGENERATE_CERTIFICATES:
            logger.warning(
                f"Overwriting regenerate_certificates with {regenerate_certificates!r} (was {self.regenerate_certificates!r})"
            )
            self.__regenerate_certificates = regenerate_certificates

    @property
    def scan_devices(self) -> bool:
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
    def cetoni_device_config_path(self) -> Optional[Path]:
        return self.__cetoni_device_config_path
