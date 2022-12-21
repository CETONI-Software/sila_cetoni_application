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
import time
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List

import typer
from sila2.server import SilaServer

if TYPE_CHECKING:
    from sila_cetoni.application.device import (
        CetoniAxisSystemDevice,
        CetoniPumpDevice,
        CetoniMobDosDevice,
        ControllerDevice,
        IODevice,
        ValveDevice,
        BalanceDevice,
        HeatingCoolingDevice,
        LCMSDevice,
        PurificationDevice,
        StirringDevice,
    )

from .application_configuration import ApplicationConfiguration
from .server_configuration import ServerConfiguration
from .singleton import Singleton
from .system import ApplicationSystem

DEFAULT_BASE_PORT = 50051

logger = logging.getLogger(__name__)


class Application(Singleton):
    """
    Encompasses the main application logic
    """

    __system: ApplicationSystem

    __config: ApplicationConfiguration  # parsed from `config_file`
    __servers: List[SilaServer]

    def __init__(self, config_file_path: Path):

        self.__config = ApplicationConfiguration(config_file_path.stem, config_file_path)
        self.__servers = []

    @property
    def config(self) -> ApplicationConfiguration:
        return self.__config

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
        self.__system = ApplicationSystem(self.__config)
        try:
            self.__system.start()
        except Exception as err:
            logger.error(f"Failed to start application system", exc_info=err)
            self.stop()
            raise typer.Exit(1)

        self.__create_servers()

        if not self.__servers:
            logger.info("No SiLA Servers to run")
            self.__system.stop()
            return

        try:
            self.__start_servers()
            print("Press Ctrl-C to stop...", flush=True)
            while not self.__system.state.shutting_down():
                time.sleep(1)
        except KeyboardInterrupt:
            print()
            self.stop()
            return True
        return False

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

                port = self.__config.server_base_port + i
                if server_config.server_port is not None:
                    if server_config.server_port in used_ports:
                        logger.warning(
                            f"Cannot start server {server.server_name!r} on port {server_config.server_port} because "
                            f"this port is already used by {used_ports[server_config.server_port].server_name!r}! "
                            f"Using port {port} instead."
                        )
                    else:
                        port = server_config.server_port

                server.start(
                    self.__config.server_ip,
                    port,
                    private_key=server_config.ssl_private_key,
                    cert_chain=server_config.ssl_certificate,
                    ca_for_discovery=server_config.ssl_certificate,
                )
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

        for device in self.__system.all_devices:

            logger.info(f"Creating server for {device}")

            # common args for all servers
            server_name = device.name.replace("_", " ")
            common_args = {
                "server_name": server_name,
                "server_type": "TestServer",
                "server_uuid": ServerConfiguration(server_name, self.__system.device_config.name).server_uuid,
            }

            server: SilaServer
            if device.device_type == "pump":
                pump: CetoniPumpDevice = device
                from sila_cetoni.pumps.syringepumps.sila.syringepump_service import Server

                server = Server(
                    pump=pump.device_handle,
                    valve=pump.valves[0] if len(pump.valves) > 0 else None,
                    io_channels=pump.io_channels,
                    **common_args,
                )
            elif device.device_type == "contiflow_pump":
                pump: CetoniPumpDevice = device
                from sila_cetoni.pumps.contiflowpumps.sila.contiflowpump_service.server import Server

                server = Server(pump=pump.device_handle, **common_args)
            elif device.device_type == "peristaltic_pump":
                pump: CetoniPumpDevice = device
                # from sila_cetoni.pumps.peristalticpumps.sila.peristalticpump_service.server import Server

                # server = Server(pump=pump.device_handle, **common_args)
                logger.info(f"No support for peristaltic pumps yet! Skipping creation of SiLA Server for {pump.name}.")
                continue
            elif device.device_type == "mobdos":
                mobdos: CetoniMobDosDevice = device
                from sila_cetoni.mobdos.sila.mobdos_service.server import Server

                server = Server(
                    pump=mobdos.device_handle,
                    valve=mobdos.valves[0] if len(mobdos.valves) > 0 else None,
                    io_channels=mobdos.io_channels,
                    battery=mobdos.battery,
                    **common_args,
                )
            elif device.device_type == "axis_system":
                axis_system: CetoniAxisSystemDevice = device

                from sila_cetoni.motioncontrol.axis.sila.axis_service.server import Server

                server = Server(
                    axis_system=axis_system.device_handle,
                    io_channels=axis_system.io_channels,
                    device_properties=axis_system.device_properties,
                    **common_args,
                )
            elif device.device_type == "valve":
                valve_device: ValveDevice = device

                from sila_cetoni.valves.sila.valve_service.server import Server

                server = Server(valves=valve_device.valves, **common_args)
            elif device.device_type == "controller":
                controller_device: ControllerDevice = device

                from sila_cetoni.controllers.sila.controllers_service.server import Server

                server = Server(controller_channels=controller_device.controller_channels, **common_args)
            elif device.device_type == "io":
                io_device: IODevice = device

                from sila_cetoni.io.sila.io_service.server import Server

                server = Server(io_channels=io_device.io_channels, **common_args)
            elif device.device_type == "balance":
                balance: BalanceDevice = device

                from sila_cetoni.balance.sila.balance_service.server import Server

                server = Server(balance=balance.device, **common_args)
            elif device.device_type == "lcms":
                lcms: LCMSDevice = device

                from sila_cetoni.lcms.sila.spectrometry_service.server import Server

                server = Server(lcms=lcms.device, **common_args)
            elif device.device_type == "heating_cooling":
                heating_cooling_device: HeatingCoolingDevice = device

                from sila_cetoni.heating_cooling.sila.heating_cooling_service.server import Server

                server = Server(temp_controller=heating_cooling_device.device, **common_args)
            elif device.device_type == "purification":
                purification_device: PurificationDevice = device

                from sila_cetoni.purification.sila.purification_service.server import Server

                server = Server(device=purification_device.device, **common_args)
            elif device.device_type == "stirring":
                stirring_device: StirringDevice = device

                from sila_cetoni.stirring.sila.stirring_service.server import Server

                server = Server(device=stirring_device.device, **common_args)
            else:
                logger.warning(f"Unhandled device type {device.device_type} of device {device}")
                continue

            self.__servers += [server]

        logger.debug(f"Done creating servers: {[(server.server_name, server) for server in self.__servers]}")
