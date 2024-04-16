from __future__ import annotations

import logging
import os
import platform
import re
import uuid
from configparser import ConfigParser
from datetime import datetime, timedelta
from ipaddress import IPv4Address
from pathlib import Path
from typing import TYPE_CHECKING, Dict, Iterator, List, Optional, Set, Tuple, cast

import safer
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from typing_extensions import Self

from sila_cetoni.utils import pretty_timedelta_str

if TYPE_CHECKING:
    from configparser import SectionProxy, _Section

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

    __instances: Dict[Tuple, Self] = {}

    def __new__(cls, *args, **kwargs):
        """
        Ensures that there is only one instance per actual config file
        """
        key = args + tuple(kwargs.items())
        if key not in cls.__instances:
            cls.__instances[key] = super().__new__(cls)
        return cls.__instances[key]

    def __init__(self, name: str, subdir: str = "") -> None:
        """
        Construct a `ServerConfiguration` that will read from / write to a config file with the given `name`

            :param name: Name of the config file (should be the same as the server's name that this config is for)
            :param subdir: (optional) The subdirectory to store the config file in
        """
        super().__init__(name, Path(os.path.join(self.__config_dir(subdir), self.__slugify(name) + ".ini")))

    def __del__(self):
        try:
            self.write()
        except NameError:
            pass

    @staticmethod
    def __slugify(name: str) -> str:
        """
        Returns the slugified version of `name` (i.e. `name` stripped from all whitespaces and special characters that
        are not allowed in filenames)

        from https://stackoverflow.com/a/46801075/12780516 and
        https://github.com/django/django/blob/004f985b918d5ea36fbed9b050459dd22edaf396/django/utils/text.py#L235-L248
        """
        name = str(name).strip().replace(" ", "_")
        name = re.sub(r"(?u)[^-\w.]", "", name)
        return name

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
        file_exists = len(self.__parser.read(self._file_path)) != 0

        version = self.__parser.getint("meta", "version", fallback=-1)
        # update version
        self.__parser["meta"] = {}
        self.__parser["meta"]["version"] = str(self.VERSION)

        if not file_exists or version < 0:
            logger.warning(f"Could not read config file! Creating a new one ({self._file_path})")
            self.__add_default_values()

            if version < 1:
                self.__add_default_values_v1()
            if version < 2:
                self.__add_default_values_v2()
            self.write()

    # `ConfigParser`-like access ---------------------------------------------

    def __len__(self) -> int:
        """
        Returns the number of sections in the config file
        """
        return len(self.__parser)

    def __getitem__(self, key: str) -> SectionProxy:
        """
        Proxy for accessing the internal `ConfigParser` instance using its `__getitem__` method

        Parameters
        ----------
        key : str
            A section in the config file

        Returns
        -------
        section : SectionProxy
            The corresponding section in the config file

        Raises
        ------
        KeyError
            if there is no section with the given name
        """
        return self.__parser[key]

    def __setitem__(self, key: str, value: _Section) -> None:
        """
        Sets the given section `key` to the `value`

        Parameters
        ----------
        key : str
            A section in the config file
        value : _Section
            The value to set for this section
        """
        self.__parser[key] = value

    def __delitem__(self, key: str) -> None:
        """
        Removes the given section `key` from the config file

        Parameters
        ----------
        key : str
            A section in the config file
        """
        del self.__parser[key]

    def __iter__(self) -> Iterator[str]:
        """
        Returns an iterator over all available sections
        """
        return iter(self.__parser)

    def __contains__(self, key: object) -> bool:
        """
        Returns whether the config file contains a section with the given `key`

        Parameters
        ----------
        key : object
            A section in the config file

        Returns
        -------
        bool
            `True` if the `key` is a section in the config file, else `False`
        """
        return key in self.__parser

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
        server_uuid = uuid.UUID(self.__parser["server"]["uuid"])
        logger.info(f"Generating self-signed certificate for server {server_uuid}")
        private_key, cert_chain = generate_self_signed_certificate(server_uuid, ip)
        self.__parser["server"]["ssl_private_key"] = private_key.decode("utf-8")
        self.__parser["server"]["ssl_certificate"] = cert_chain.decode("utf-8")
        self.write()

    def write(self):
        """
        Writes the current configuration to the file
        """
        os.makedirs(os.path.dirname(self._file_path), exist_ok=True)
        with safer.open(self._file_path, "w", delete_failures=False) as config_file:
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
    def server_base_port(self) -> Optional[int]:
        """
        The base port of all SiLA Servers as read from the config file
        """
        return self.__parser["server"].getint("base_port")

    @server_base_port.setter
    def server_base_port(self, server_base_port: int):
        """
        Set the base port of all SiLA Servers
        """
        self.__parser["server"]["base_port"] = str(server_base_port)

    @property
    def server_port(self) -> Optional[int]:
        """
        The port of the SiLA Server as read from the config file
        """
        return self.__parser["server"].getint("port")

    @server_port.setter
    def server_port(self, server_port: int):
        """
        Set the port of the SiLA Server
        """
        self.__parser["server"]["port"] = str(server_port)

    @property
    def ssl_private_key(self) -> bytes:
        """
        The private key for the SSL certificate
        """
        return self.__parser["server"]["ssl_private_key"].encode("utf-8")

    @property
    def ssl_certificate(self) -> bytes:
        """
        The SSL certificate
        """
        return self.__parser["server"]["ssl_certificate"].encode("utf-8")

    def ssl_certificate_for_ip(self, ip: str) -> bytes:
        """
        The SSL certificate with the given `ip` added as a *Subject Alternative Name*

        This will return the already existing certificate if it already contains the `ip` as SAN, otherwise `ip` will be
        added to the SANs first, and the modified certificate will be stored in the configuration file and returned.
        """

        cert = x509.load_pem_x509_certificate(self.ssl_certificate)

        subject_alt_name_ext = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        subject_alt_name_ips = subject_alt_name_ext.value.get_values_for_type(x509.IPAddress)
        ip_address = IPv4Address(ip)
        if ip_address not in subject_alt_name_ips:
            logger.warning(
                f"IP address {ip} not present in SANs of certificate for server {self.server_uuid} - adding it..."
            )

            private_key = serialization.load_pem_private_key(self.ssl_private_key, password=None)
            cert = (
                x509.CertificateBuilder(
                    cert.issuer,
                    cert.subject,
                    cert.public_key(),
                    cert.serial_number,
                    cert.not_valid_before,
                    cert.not_valid_after,
                    list(set(cert.extensions) - set([subject_alt_name_ext])),
                )
                .add_extension(
                    x509.SubjectAlternativeName([x509.IPAddress(ip) for ip in (*subject_alt_name_ips, ip_address)]),
                    critical=False,
                )
                .sign(private_key, hashes.SHA256())
            )

            cert_bytes = cert.public_bytes(serialization.Encoding.PEM)
            self.__parser["server"]["ssl_certificate"] = cert_bytes.decode("utf-8")
            self.write()

        return self.ssl_certificate

    def renew_certificate(self, renewal_period: timedelta = timedelta(days=365), force: bool = False) -> None:
        """
        Renews the server certificate if necessary (i.e. if the *not after* field is close (< 30 days) to expiration)

        The renewed certificate is written to the config file and can be obtained by calling `ssl_certificate` again

        Parameters
        ----------
        renewal_period : timedelta (default: 1 year)
            How long to extend the certificate's validity
            For a certificate that is still valid this means that the new *not after* field is extended by the
            `renewal_period`.
            For an already expired certificate this means that the new *not after* field is set to
            `datetime.today() + renewal_period`.
            This is done to have the longest possible valid certificate in both cases.
        force : bool (default: False)
            Whether to force renewal of the certificate even if it is not close to expiration
        """

        EXPIRY_THRESHOLD = timedelta(days=30)

        cert = x509.load_pem_x509_certificate(self.ssl_certificate)

        expiry_in = cert.not_valid_after - datetime.now()
        if not force and expiry_in >= EXPIRY_THRESHOLD:
            logger.info(f"Certificate for server {self.server_uuid} still valid for {pretty_timedelta_str(expiry_in)}")
            return

        is_expired = expiry_in.total_seconds() < 0
        not_valid_after = (datetime.today() if is_expired else cert.not_valid_after) + renewal_period
        logger.warning(
            f"Renewing certificate for server {self.server_uuid} ({'expired' if is_expired else 'will expire in'} "
            f"{pretty_timedelta_str(abs(expiry_in))}{' ago' if is_expired else ''}) because "
            f"""{'it was forced'
                    if force
                    else f'this is less than the allowed threshold of {pretty_timedelta_str(EXPIRY_THRESHOLD)}'}. """
            f"New expiration date is {not_valid_after.date()}"
        )

        private_key = serialization.load_pem_private_key(self.ssl_private_key, password=None)
        cert = x509.CertificateBuilder(
            cert.issuer,
            cert.subject,
            cert.public_key(),
            cert.serial_number,
            cert.not_valid_before,
            not_valid_after,
            cast(List[x509.Extension], cert.extensions),
        ).sign(private_key, hashes.SHA256())

        cert_bytes = cert.public_bytes(serialization.Encoding.PEM)
        self.__parser["server"]["ssl_certificate"] = cert_bytes.decode("utf-8")
        self.write()

    @property
    def axis_position_counters(self) -> Optional[Dict[str, int]]:
        """
        Returns the axis position counters if this config is for an axis device

        The keys of the returned dictionary are the axis names and the values are the position counter values.
        """
        if self.__parser.has_section("axis_position_counters"):
            return dict(self.__parser["axis_position_counters"])  # type: ignore
        else:
            return dict()

    @axis_position_counters.setter
    def axis_position_counters(self, position_counters: Dict[str, int]):
        """
        Set the axis position counters if this config is for an axis device

        The keys of the dictionary need to be the axis names and the values are the position counter values.
        """
        logger.info(position_counters)
        self.__parser["axis_position_counters"] = position_counters  # type: ignore

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
