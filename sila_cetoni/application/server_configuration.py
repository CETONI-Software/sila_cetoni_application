import logging
import os
import platform
import uuid
from configparser import ConfigParser
from typing import Dict, Optional, Set

from sila2.server.encryption import generate_self_signed_certificate

from .configuration import Configuration
from .local_ip import LOCAL_IP

logger = logging.getLogger(__name__)


class ServerConfiguration(Configuration):
    """
    The configuration for a specific SiLA server
    """

    __uuids: Set[uuid.UUID] = set()

    __parser: ConfigParser

    VERSION = 2

    def __init__(self, name: str, subdir: str = "") -> None:
        """
        Construct a `ServerConfiguration` that will read from / write to a config file with the given `name`

            :param name: Name of the config file
            :param subdir: (optional) The subdirectory to store the config file in
        """
        super().__init__(name, os.path.join(self.__config_dir(subdir), name + ".ini"))

    @staticmethod
    def __config_dir(subdir: str = "") -> str:
        """
        Returns the path to the directory where the configuration file is located
        """
        if platform.system() == "Windows":
            return os.path.join(os.environ["APPDATA"], "sila_cetoni", subdir)
        else:
            return os.path.join(os.environ["HOME"], ".config", "sila_cetoni", subdir)

    @staticmethod
    def __unique_server_uuid() -> uuid.UUID:
        """
        Ensures that the randomly generated UUIDs are actually unique
        """
        server_uuid = uuid.uuid4()
        logger.info(
            f"1 new uuid {server_uuid}, already used? {server_uuid in ServerConfiguration.__uuids}, UUIDs: {ServerConfiguration.__uuids}"
        )
        while server_uuid in ServerConfiguration.__uuids:
            server_uuid = uuid.uuid4()
            logger.warning(
                f"2 new uuid {server_uuid}, already used? {server_uuid in ServerConfiguration.__uuids}, UUIDs: {ServerConfiguration.__uuids}"
            )
        logger.info(f"uuid {server_uuid} is unique")
        ServerConfiguration.__uuids.add(server_uuid)
        return server_uuid

    def _parse(self) -> None:
        self.__parser = ConfigParser()
        file_exists = self.__parser.read(self._file_path)

        version = self.__parser.getint("meta", "version", fallback=0)
        # update version
        self.__parser["meta"] = {}
        self.__parser["meta"]["version"] = str(self.VERSION)

        if not file_exists:
            logger.warning(f"Could not read config file! Creating a new one ({self._file_path})")
            self.__add_default_values()

        if version < 1:
            self.__add_default_values_v1()
        if version < 2:
            self.__add_default_values_v2()
        self.write()

    # v0 ---------------------------------------------------------------------

    def __add_default_values(self):
        """
        Sets all necessary entries to default values
        """
        self.__parser["server"] = {}
        self.__parser["server"]["uuid"] = str(self.__unique_server_uuid())
        self.__parser["pump"] = {}
        self.__parser["axis_position_counters"] = {}

    def generate_self_signed_certificate(self, ip: str):
        """
        Generates a self-signed certificate and a private key and stores that into the config file

            :param ip: The IP address to store into the certificate
        """
        uuid = self.__parser["server"]["uuid"]
        logger.info(f"Generating self-signed certificate for server {uuid}")
        private_key, cert_chain = generate_self_signed_certificate(uuid, ip)
        self.__parser["server"]["ssl_private_key"] = private_key.decode("utf-8")
        self.__parser["server"]["ssl_certificate"] = cert_chain.decode("utf-8")

    def write(self):
        """
        Writes the current configuration to the file
        """
        os.makedirs(os.path.dirname(self._file_path), exist_ok=True)
        with open(self._file_path, "w") as config_file:
            self.__parser.write(config_file)

    # v1 ---------------------------------------------------------------------

    def __add_default_values_v1(self):
        """
        Sets all necessary entries to default values for version 1 of the config file
        """
        self.generate_self_signed_certificate(LOCAL_IP)

    @property
    def server_uuid(self) -> Optional[str]:
        """
        The UUID of the SiLA Server as read from the config file
        """
        return self.__parser["server"].get("uuid")

    @property
    def ssl_private_key(self) -> Optional[bytes]:
        """
        The private key for the SSL certificate
        """
        return self.__parser["server"].get("ssl_private_key").encode("utf-8")

    @property
    def ssl_certificate(self) -> Optional[bytes]:
        """
        The SSL certificate
        """
        return self.__parser["server"].get("ssl_certificate").encode("utf-8")

    @property
    def pump_drive_position_counter(self) -> Optional[int]:
        """
        Returns the pump drive position counter if this config is for a pump device
        """
        return self.__parser["pump"].getint("drive_position_counter")

    @pump_drive_position_counter.setter
    def pump_drive_position_counter(self, drive_position_counter: int):
        """
        Set the pump drive position counter if this config is for a pump device
        """
        self.__parser["pump"]["drive_position_counter"] = str(drive_position_counter)

    @property
    def axis_position_counters(self) -> Optional[Dict[str, int]]:
        """
        Returns the axis position counters if this config is for an axis device

        The keys of the returned dictionary are the axis names and the values are the position counter values.
        """
        if self.__parser.has_section("axis_position_counters"):
            return dict(self.__parser["axis_position_counters"])
        else:
            return dict()

    @axis_position_counters.setter
    def axis_position_counters(self, position_counters: Dict[str, int]):
        """
        Set the axis position counters if this config is for an axis device

        The keys of the dictionary need to be the axis names and the values are the position counter values.
        """
        logger.info(position_counters)
        self.__parser["axis_position_counters"] = position_counters

    # v2 ---------------------------------------------------------------------

    def __add_default_values_v2(self):
        """
        Sets all necessary entries to default values for version 2 of the config file
        """
        self.__parser["stirring"] = {}

    @property
    def stirring_rpm(self) -> Optional[float]:
        """
        Returns the stirring RPM if this config is for a stirring device
        """
        return self.__parser["stirring"].getfloat("rpm")

    @stirring_rpm.setter
    def stirring_rpm(self, rpm: float):
        """
        Set the stirring RPM if this config is for a stirring device
        """
        self.__parser["stirring"]["rpm"] = str(rpm)

    @property
    def stirring_power(self) -> Optional[float]:
        """
        Returns the stirring power if this config is for a stirring device
        """
        return self.__parser["stirring"].getfloat("power")

    @stirring_power.setter
    def stirring_power(self, power: float):
        """
        Set the stirring power if this config is for a stirring device
        """
        self.__parser["stirring"]["power"] = str(power)
