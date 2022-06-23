import logging
import os
import platform
import uuid
from configparser import ConfigParser
from typing import Dict, Optional

from sila2.server.encryption import generate_self_signed_certificate

from .local_ip import LOCAL_IP

logger = logging.getLogger(__name__)


VERSION = 1

class Config:
    """
    Helper class to read and write a persistent configuration file
    """

    __config_path: str
    __parser: ConfigParser

    def __init__(self, name: str, subdir: str = "") -> None:
        """
        Construct a `Config` that will read from / write to a config file with the given `name`

            :param name: Name of the config file
            :param subdir: (optional) The sub directory to store the config file in
        """
        self.__config_path = os.path.join(self.__config_dir(subdir), name + ".ini")
        self.__parser = ConfigParser()
        file_exists = self.__parser.read(self.__config_path)

        version = self.__parser.getint("meta", "version", fallback=0)
        # update version
        self.__parser["meta"] = {}
        self.__parser["meta"]["version"] = str(VERSION)

        if not file_exists:
            logger.warning(f"Could not read config file! Creating a new one ({self.__config_path})")
            self.__add_default_values()

        if version < 1:
            self.__add_default_values_v1()
        # if version < 2:
        #     self.__add_default_values_v2()
        self.write()


    @staticmethod
    def __config_dir(subdir: str = "") -> str:
        """
        Returns the path to the directory where the configuration file is located
        """
        if platform.system() == "Windows":
            return os.path.join(os.environ["APPDATA"], "sila_cetoni", subdir)
        else:
            return os.path.join(os.environ["HOME"], ".config", "sila_cetoni", subdir)

    def __add_default_values(self):
        """
        Sets all necessary entries to default values
        """
        self.__parser["server"] = {}
        self.__parser["server"]["uuid"] = str(uuid.uuid4())
        self.__parser["pump"] = {}
        self.__parser["axis_position_counters"] = {}

    def __add_default_values_v1(self):
        """
        Sets all necessary entries to default values for version 1 of the config file
        """
        logger.info("Generating self-signed certificate")
        private_key, cert_chain = generate_self_signed_certificate(self.__parser["server"]["uuid"], LOCAL_IP)
        self.__parser["server"]["ssl_private_key"] = private_key.decode("utf-8")
        self.__parser["server"]["ssl_certificate"] = cert_chain.decode("utf-8")

    def write(self):
        """
        Writes the current configuration to the file
        """
        os.makedirs(os.path.dirname(self.__config_path), exist_ok=True)
        with open(self.__config_path, "w") as config_file:
            self.__parser.write(config_file)

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
        self.__parser["pump"]["drive_position_counter"] = str(drive_position_counter)

    @property
    def axis_position_counters(self) -> Optional[Dict[str, int]]:
        """
        Returns the axis position counters if this config is for an axis device
        The keys of the returned dictionary are the axis names and the values are
        the position counter values.
        """
        if self.__parser.has_section("axis_position_counters"):
            return dict(self.__parser["axis_position_counters"])
        else:
            return dict()

    @axis_position_counters.setter
    def axis_position_counters(self, position_counters: Dict[str, int]):
        logger.info(position_counters)
        self.__parser["axis_position_counters"] = position_counters
