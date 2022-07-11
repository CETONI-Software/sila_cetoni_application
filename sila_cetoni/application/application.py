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

import argparse
import concurrent.futures
import logging
import os
import sys
import time
from pathlib import Path
from typing import List, Optional

from sila2.server import SilaServer

from sila_cetoni.config import CETONI_SDK_PATH

# adjust PATH variable to point to the SDK
sys.path.append(CETONI_SDK_PATH)
sys.path.append(os.path.join(CETONI_SDK_PATH, "lib", "python"))

try:
    from qmixsdk import qmixpump
except (ModuleNotFoundError, ImportError):
    pass

from .config import Config
from .local_ip import LOCAL_IP
from .singleton import Singleton
from .system import ApplicationSystem

DEFAULT_BASE_PORT = 50051

logger = logging.getLogger(__name__)


class Application(metaclass=Singleton):
    """
    Encompasses the main application logic
    """

    system: ApplicationSystem

    ip: str
    base_port: int
    servers: List[SilaServer]
    regenerate_certificates: bool

    def __init__(
        self,
        device_config_path: Optional[Path] = None,
        ip: str = LOCAL_IP,
        base_port: int = DEFAULT_BASE_PORT,
        regenerate_certificates: bool = False,
    ):

        self.system = ApplicationSystem(device_config_path)

        self.ip = ip
        self.base_port = base_port
        self.regenerate_certificates = regenerate_certificates

    def run(self):
        """
        Run the main application loop

        Starts the whole system (i.e. all devices) and all SiLA 2 servers
        Runs until Ctrl-C is pressed on the command line or `stop()` has been called
        """
        self.system.start()

        logger.debug("Creating SiLA 2 servers...")
        self.servers = self.create_servers()

        if not self.servers:
            logger.info("No SiLA Servers to run")
            self.system.stop()
            return

        try:
            self.start_servers()
            print("Press Ctrl-C to stop...", flush=True)
            while not self.system.state.shutting_down():
                time.sleep(1)
        except KeyboardInterrupt:
            print()
            self.stop()

    def stop(self):
        """
        Stops the application

        Shuts down all SiLA 2 servers and stops the whole system
        """
        self.stop_servers()
        self.system.stop()

    def start_servers(self):
        """
        Starts all SiLA 2 servers
        """
        logger.debug("Starting SiLA 2 servers...")
        port = self.base_port
        for server in self.servers:
            try:
                config = Config(server.server_name.replace(" ", "_"), self.system.device_config.name)
                if self.regenerate_certificates:
                    config.generate_self_signed_certificate(self.ip)
                server.start(
                    self.ip,
                    port,
                    private_key=config.ssl_private_key,
                    cert_chain=config.ssl_certificate,
                    ca_for_discovery=config.ssl_certificate,
                )
                logger.info(f"Starting SiLA 2 server {server.server_name!r} on {LOCAL_IP}:{port}")
            except (RuntimeError, concurrent.futures.TimeoutError) as err:
                logger.error(str(err))
                self.stop()
            port += 1
        logger.info("All servers started!")

    def stop_servers(self):
        """
        Stops all SiLA 2 servers
        """
        logger.debug("Shutting down servers...")
        for server in self.servers:
            server.stop()
        logger.info("Done!")

    def create_servers(self):
        """
        Creates a corresponding SiLA 2 server for every device connected to the bus
        """

        servers = []
        # common args for all servers
        server_type = "TestServer"

        # ---------------------------------------------------------------------
        # pumps
        for pump in self.system.pumps:
            server_name = pump.name.replace("_", " ")

            if pump.is_peristaltic_pump:
                logger.warning(
                    f"Cannot create SiLA 2 server for pump {pump.name} because peristaltic pumps are not yet supported!"
                )
                continue

            if isinstance(pump, qmixpump.ContiFlowPump):
                from sila_cetoni.pumps.contiflowpumps.sila.contiflowpump_service.server import Server

                server = Server(
                    pump=pump,
                    server_name=server_name,
                    server_type=server_type,
                    server_uuid=Config(pump.name, self.system.device_config.name).server_uuid,
                )
            else:
                from sila_cetoni.pumps.syringepumps.sila.syringepump_service import Server

                server = Server(
                    pump=pump,
                    valve=pump.valves[0] if len(pump.valves) > 0 else None,
                    io_channels=pump.io_channels,
                    battery=self.system.battery,
                    server_name=server_name,
                    server_type=server_type,
                    server_uuid=Config(pump.name, self.system.device_config.name).server_uuid,
                )
            servers += [server]

        # ---------------------------------------------------------------------
        # axis systems
        for axis_system in self.system.axis_systems:
            server_name = axis_system.name.replace("_", " ")

            from sila_cetoni.motioncontrol.axis.sila.axis_service.server import Server

            server = Server(
                axis_system=axis_system,
                io_channels=axis_system.io_channels,
                device_properties=axis_system.properties,
                server_name=server_name,
                server_type=server_type,
                server_uuid=Config(axis_system.name, self.system.device_config.name).server_uuid,
            )
            servers += [server]

        # ---------------------------------------------------------------------
        # valves
        for valve_device in self.system.valves:
            server_name = valve_device.name.replace("_", " ")

            from sila_cetoni.valves.sila.valve_service.server import Server

            server = Server(
                valves=valve_device.valves,
                server_name=server_name,
                server_type=server_type,
                server_uuid=Config(valve_device.name, self.system.device_config.name).server_uuid,
            )
            servers += [server]

        # ---------------------------------------------------------------------
        # controller
        for controller_device in self.system.controllers:
            server_name = controller_device.name.replace("_", " ")

            from sila_cetoni.controllers.sila.controllers_service.server import Server

            server = Server(
                controller_channels=controller_device.controller_channels,
                server_name=server_name,
                server_type=server_type,
                server_uuid=Config(controller_device.name, self.system.device_config.name).server_uuid,
            )
            servers += [server]

        # ---------------------------------------------------------------------
        # I/O
        for io_device in self.system.io_devices:
            server_name = io_device.name.replace("_", " ")

            from sila_cetoni.io.sila.io_service.server import Server

            server = Server(
                io_channels=io_device.io_channels,
                server_name=server_name,
                server_type=server_type,
                server_uuid=Config(io_device.name, self.system.device_config.name).server_uuid,
            )
            servers += [server]

        # ---------------------------------------------------------------------
        # balance
        for balance in self.system.balances:
            server_name = balance.name.replace("_", " ")

            from sila_cetoni.balance.sila.balance_service.server import Server

            server = Server(
                balance=balance.device,
                server_name=server_name,
                server_type=server_type,
                server_uuid=Config(balance.name, self.system.device_config.name).server_uuid,
            )
            servers += [server]

        # ---------------------------------------------------------------------
        # lcms
        lcms = self.system.lcms
        if lcms is not None:
            server_name = lcms.name.replace("_", " ")

            from sila_cetoni.lcms.sila.spectrometry_service.server import Server

            server = Server(
                lcms=lcms.device,
                server_name=server_name,
                server_type=server_type,
                server_uuid=Config(lcms.name, self.system.device_config.name).server_uuid,
            )
            servers += [server]

        # ---------------------------------------------------------------------
        # heating_cooling
        for heating_cooling_device in self.system.heating_cooling_devices:
            server_name = heating_cooling_device.name.replace("_", " ")

            from sila_cetoni.heating_cooling.sila.heating_cooling_service.server import Server

            server = Server(
                temp_controller=heating_cooling_device.device,
                server_name=server_name,
                server_type=server_type,
                server_uuid=Config(heating_cooling_device.name, self.system.device_config.name).server_uuid,
            )
            servers += [server]

        # ---------------------------------------------------------------------
        # purification
        for purification_device in self.system.purification_devices:
            server_name = purification_device.name.replace("_", " ")

            from sila_cetoni.purification.sila.purification_service.server import Server

            server = Server(
                device=purification_device.device,
                server_name=server_name,
                server_type=server_type,
                server_uuid=Config(purification_device.name, self.system.device_config.name).server_uuid,
            )
            servers += [server]

        return servers
