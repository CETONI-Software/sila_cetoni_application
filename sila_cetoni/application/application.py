"""
________________________________________________________________________

:PROJECT: sila_cetoni

*Application*

:details: Application:
    The main application class containing all logic of the sila_cetoni.py

:file:    application.py
:authors: Florian Meinicke

:date: (creation)          2021-07-19
:date: (last modification) 2021-07-15

________________________________________________________________________

**Copyright**:
  This file is provided "AS IS" with NO WARRANTY OF ANY KIND,
  INCLUDING THE WARRANTIES OF DESIGN, MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE.

  For further Information see LICENSE file that comes with this distribution.
________________________________________________________________________
"""

from __future__ import annotations

import concurrent.futures
import logging
import os
from pathlib import Path
from queue import Empty, Queue
from typing import TYPE_CHECKING, Callable, Dict, List, cast

import typer
from sila2.server import SilaServer

from sila_cetoni.package_util import available_packages

from .application_configuration import ApplicationConfiguration
from .server_configuration import ServerConfiguration
from .singleton import Singleton
from .system import ApplicationSystem

if TYPE_CHECKING:
    from PySide2.QtCore import QObject

DEFAULT_BASE_PORT = 50051

logger = logging.getLogger(__name__)


class Task:
    """
    A task that can be put into a `Queue` for execution in the main application thread

    Consists of a function and optional arguments and keyword arguments.
    Provides a `__call__` implementation that will call the function with those arguments and keyword arguments

    Inspired by https://stackoverflow.com/a/683755/12780516
    """

    def __init__(self, fn: Callable, *args, **kwargs):
        """
        Create a new `Task`

        Parameters
        ----------
        fn: Callable
            The function that will be called when this `Task` is executed
        *args: Tuple
            Arguments to the function `fn`
        **kwargs: Dict
            Keyword arguments to the function `fn`
        """
        if not callable(fn):
            raise TypeError(f"Cannot create Task from non-callable {fn!r}")

        self.fn = fn
        self.args = args
        self.kwargs = kwargs

    def __call__(self):
        return self.fn(*self.args, **self.kwargs)


class Application(Singleton):
    """
    Encompasses the main application logic
    """

    __system: ApplicationSystem

    __config: ApplicationConfiguration  # parsed from `config_file`
    __servers: List[SilaServer]

    __remote_objects: List[QObject]

    __tasks_queue: Queue[Task]

    def __init__(self, config_file_path: Path):
        self.__config = ApplicationConfiguration(config_file_path.stem, config_file_path)
        self.__servers = []

        self.__remote_objects = []

        self.__tasks_queue = Queue()

    @property
    def config(self) -> ApplicationConfiguration:
        return self.__config

    @property
    def servers(self) -> List[SilaServer]:
        return self.__servers

    @property
    def tasks_queue(self) -> Queue[Task]:
        """
        Returns the tasks queue that can be used to run tasks in the main thread
        """
        return self.__tasks_queue

    def run(self) -> bool:
        """
        Run the main application loop

        Starts the whole system (i.e. all devices) and all SiLA 2 servers
        Runs until Ctrl-C is pressed on the command line or `stop()` has been called

        Returns
        -------
        bool
            Whether the application could run normally or not (i.e. when there was an error during startup)
            `True` means the application ran normally, `False` means the application did not run normally, e.g. because
            the servers could not be started.
        """

        self.__config.sanity_check()
        self.__config.parse_devices()
        self.__system = ApplicationSystem(self.__config)
        try:
            self.__system.start()
        except Exception as err:
            logger.error(f"Failed to start application system", exc_info=err)
            self.stop()
            raise typer.Exit(1)

        if self.__config.sila:
            try:
                self.__create_servers()
            except Exception as err:
                logger.error(f"Failed to create SiLA servers", exc_info=err)
                self.stop()
                raise typer.Exit(2)

            if not self.__servers:
                logger.info("No SiLA Servers to run")
                self.__system.stop()
                return True

            self.__system.on_servers_created(self.__servers)

        try:
            if self.__config.sila:
                self.__start_servers()
                if self.__system.state.shutting_down():
                    return False
                print("Press Ctrl-C to stop...", flush=True)
                while not self.__system.state.shutting_down():
                    try:
                        task = self.__tasks_queue.get(block=True, timeout=1)
                        task()
                    except Empty:
                        pass
                return True
        except KeyboardInterrupt:
            print()
            self.stop()
            return True

        if self.__config.remote_objects:
            import signal

            from PySide2.QtCore import QCoreApplication

            from sila_cetoni.waa.remoteobjects.remote_object import RemoteObject

            sigint_handler = None

            def handle_sigint(*args):
                global qapp
                if qapp is None:
                    logger.warning("received SIGINT before qapp was initialized")
                    return
                logger.debug("received SIGINT -> quitting QCoreApplication")
                signal.signal(signal.SIGINT, sigint_handler)
                qapp.quit()

            # this has to be done *before* creating the `QCoreApplication` instance, otherwise destroying the `qapp` at
            # the end of the program will cause a segmentation fault
            sigint_handler = signal.signal(signal.SIGINT, handle_sigint)

            # `qapp` must be global otherwise it will cause a segmentation fault when the program exits
            global qapp
            qapp = QCoreApplication([])

            self.__create_remote_objects()

            logger.info("Application started")
            print("Press Ctrl-C to stop...", flush=True)

            exit_code = qapp.exec_()
            logger.debug(f"Application exited with exit code {exit_code}")

            for remote_object in self.__remote_objects:
                cast(RemoteObject, remote_object).stop()

            logger.debug("All remote objects stopped")

            return exit_code == 0

    def stop(self):
        """
        Stops the application

        Shuts down all SiLA 2 servers and stops the whole system
        """
        self.__stop_servers()
        self.__system.stop()

    def __start_servers(self):
        """
        Starts all SiLA 2 servers
        """
        logger.debug("Starting SiLA 2 servers...")
        used_ports: Dict[int, SilaServer] = dict()
        i = 0
        for server in self.__servers:
            try:
                server_config = ServerConfiguration(server.server_name, self.__system.device_config.name)
                if self.__config.regenerate_certificates:
                    server_config.generate_self_signed_certificate(self.__config.server_ip)
                else:
                    server_config.renew_certificate()

                port = self.__config.server_base_port + i
                if server_config.server_port is not None:
                    if server_config.server_port in used_ports:
                        logger.warning(
                            f"Cannot start server {server.server_name!r} on port {server_config.server_port} because "
                            f"this port is already used by {used_ports[server_config.server_port].server_name!r}! "
                            f"Using port {port} instead."
                        )
                    elif self.__config.server_base_port_cli_overwrite or (
                        server_config.server_base_port is not None
                        and server_config.server_base_port != self.__config.server_base_port
                    ):
                        logger.warning(
                            f"Server base port changed from {server_config.server_base_port} to "
                            f"{self.__config.server_base_port}! Using new base port and starting server on port {port}."
                        )
                    else:
                        port = server_config.server_port

                server.start(
                    self.__config.server_ip,
                    port,
                    private_key=server_config.ssl_private_key,
                    cert_chain=server_config.ssl_certificate_for_ip(self.__config.server_ip),
                    ca_for_discovery=server_config.ssl_certificate,
                    enable_discovery=self.__config.enable_discovery,
                )
                server_config.server_base_port = self.__config.server_base_port
                server_config.server_port = port
                server_config.write()
                used_ports[port] = server
                logger.info(
                    f"Starting SiLA 2 server {server.server_name!r} on {self.__config.server_ip}:{port} (UUID: {server_config.server_uuid})"
                )
            except (RuntimeError, concurrent.futures.TimeoutError) as err:
                logger.critical(err, exc_info=err)
                self.stop()
                break
            i += 1
        else:
            logger.info("All servers started!")
            self.__after_start()

    def __after_start(self) -> None:
        """
        Creates an empty file on the device to indicate that the SiLA Servers have been started. The presence of this file
        can be used by systemd services, for example, to turn on an LED.
        """
        SILA_CETONI_SERVER_STARTED_FILE_VAR_NAME = "SILA_CETONI_SERVER_STARTED_FILE"

        server_started_file = os.environ.get(SILA_CETONI_SERVER_STARTED_FILE_VAR_NAME)
        if server_started_file is not None:
            os.system(f'touch "{server_started_file}"')

    def __stop_servers(self):
        """
        Stops all SiLA 2 servers
        """
        logger.debug("Shutting down servers...")
        for server in self.__servers:
            try:
                server.stop()
            except RuntimeError as err:
                logger.warning(f"Could not stop server {server.server_name} ({server.server_uuid})", exc_info=err)
        logger.info("Done!")

    def __create_servers(self):
        """
        Creates a corresponding SiLA 2 server for every device connected to the bus
        """
        logger.debug("Creating SiLA 2 servers...")

        available_pkgs = available_packages()

        for device in self.__system.all_devices:
            logger.info(f"Creating server for {device}")

            # common args for all servers
            server_name = device.name.replace("_", " ")
            common_args = {
                "server_name": server_name,
                "server_uuid": ServerConfiguration(server_name, self.__system.device_config.name).server_uuid,
            }

            if f"sila_cetoni.{device.device_type}" in available_pkgs:
                server = available_pkgs[f"sila_cetoni.{device.device_type}"].create_server(device, **common_args)
                if server is not None:
                    self.__servers.append(server)
                else:
                    logger.warning(
                        f"'sila_cetoni.{device.device_type}.create_server' returned 'None' for device {device}"
                    )
            else:
                logger.warning(f"Unhandled device type {device.device_type!r} of device {device}")
                continue

        logger.debug(f"Done creating servers: {[(server.server_name, server) for server in self.__servers]}")

    def __create_remote_objects(self) -> None:
        """
        Creates remote objects for all supported devices
        """
        logger.debug("Creating remote objects...")

        available_pkgs = available_packages()

        for device in self.__system.all_devices:
            logger.info(f"Creating remote object for {device}")

            pkg_name = f"sila_cetoni.{device.device_type}"
            if pkg_name in available_pkgs:
                pkg = available_pkgs[pkg_name]
                if not hasattr(pkg, "create_remote_object"):
                    logger.info(
                        f"Skipping creation of remote objects for {device} because package {pkg_name} does not "
                        f"implement 'create_remote_object'"
                    )
                    continue

                remote_object = pkg.create_remote_object(device)
                if remote_object is not None:
                    self.__remote_objects.append(remote_object)
                else:
                    logger.warning(
                        f"'sila_cetoni.{device.device_type}.create_remote_object' returned 'None' for device {device}"
                    )
            else:
                logger.warning(f"Unhandled device type {device.device_type!r} of device {device}")
                continue

        logger.debug(f"Done creating remote objects: {[(obj.objectName(), obj) for obj in self.__remote_objects]}")
