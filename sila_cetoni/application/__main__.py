import logging
import os
import sys
from pathlib import Path
from time import strftime
from typing import Optional

import click
import typer

from . import __version__
from .application import Application
from .application_configuration import ApplicationConfiguration

app = typer.Typer()


def show_version(value: bool):
    if value:
        print(f"sila-cetoni v{__version__}")
        raise typer.Exit()


_LOGGING_FORMAT = (
    "%(asctime)s [%(threadName)-{thread_name_len}.{thread_name_len}s] %(levelname)-8s| "
    "%(name)s %(module)s.%(funcName)s (%(lineno)s): %(message)s"
)


def set_logging_level(log_level: str):
    logging_level = log_level.upper()
    try:
        import coloredlogs

        coloredlogs.install(
            fmt=_LOGGING_FORMAT.format(thread_name_len=12), datefmt="%Y-%m-%d %H:%M:%S,%f", level=logging_level
        )
    except ModuleNotFoundError:
        print("Cannot find coloredlogs! Please install coloredlogs, if you'd like to have nicer logging output:")
        print("`pip install coloredlogs`")

        logging.basicConfig(format=_LOGGING_FORMAT.format(thread_name_len=12), level=logging_level)
    return log_level


# -----------------------------------------------------------------------------
# main program
@app.command(no_args_is_help=False, context_settings={"help_option_names": ["-h", "--help"]})
def main(
    ctx: typer.Context,
    version: Optional[bool] = typer.Option(
        None,
        "--version",
        "-v",
        callback=show_version,
        is_eager=True,
        help="Show the application's version number and exit",
    ),
    log_level: str = typer.Option(
        ApplicationConfiguration.DEFAULT_LOG_LEVEL,  # or use "error" for less output
        "--log-level",
        "-l",
        callback=set_logging_level,
        metavar="LEVEL",
        help="Set the logging level of the application",
        case_sensitive=False,
        formats=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
    ),
    log_file_dir: Optional[Path] = typer.Option(
        None,
        metavar="DIR",
        help="The directory to write log files to (if not given log messages will only be printed to standard out)",
        exists=False,
        file_okay=False,
        dir_okay=True,
        readable=True,
        writable=True,
        resolve_path=True,
    ),
    server_ip: str = typer.Option(
        ApplicationConfiguration.DEFAULT_SERVER_IP,
        "--server-ip",
        "-i",
        metavar="IP",
        help="The IP address on which the servers should run",
    ),
    server_base_port: int = typer.Option(
        ApplicationConfiguration.DEFAULT_SERVER_BASE_PORT,
        "--server-base-port",
        "-p",
        metavar="PORT",
        help="The port number for the first SiLA Server",
    ),
    enable_discovery: bool = typer.Option(
        ApplicationConfiguration.DEFAULT_ENABLE_DISCOVERY,
        "--enable-discovery/--disable-discovery",
        help="Enable or disable discovery for all SiLA Servers (whether they announce themselves in the network)",
    ),
    regenerate_certificates: bool = typer.Option(
        ApplicationConfiguration.DEFAULT_REGENERATE_CERTIFICATES,
        "--regenerate-certificates/",
        help=(
            "Force regeneration of the self-signed certificates (e.g. if the IP address of the machine running the "
            "servers changed)"
        ),
    ),
    exec: bool = typer.Option(
        True,
        hidden=True,
        help=(
            "Used by __init__.py to indicate if the application shall be re-executed after setting the necessary "
            "environment variables. Only use this option if you really know what it does!"
        ),
    ),
    scan_devices: bool = typer.Option(
        False,
        help=(
            "Automatically scan for supported connected devices (e.g. scan for available Sartorius balances if the "
            "sila_cetoni_balance package is installed)"
        ),
    ),
    simulate_missing: bool = typer.Option(
        False,
        help=(
            "Try to simulate devices which are not explicitly set to 'simulated' in the config file if the application "
            "cannot connect to them"
        ),
    ),
    sila: bool = typer.Option(
        True,
        hidden=True,
        help=(
            "Whether to use the SiLA 2 stack (experimental, this flag might be removed without warning; only use if "
            "you know what you are doing!)"
        ),
    ),
    remote_objects: bool = typer.Option(
        False,
        hidden=True,
        help=(
            "Whether to use QtRemoteObjects (experimental, this flag might be removed without warning; only use if you "
            "know what you are doing!) Use in combination with --no-sila to only use QtRemoteObjects"
        ),
    ),
    config_file: Path = typer.Argument(
        "config.json",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        resolve_path=True,
        allow_dash=False,
        metavar="CONFIG_FILE",
        help="Path to a valid device configuration JSON file",
    ),
):
    """
    Launches as many SiLA 2 servers as there are CETONI devices in the configuration
    """

    def log_file_name(dir: Path, log_level: str) -> Path:
        return dir.joinpath(f"sila_cetoni-{log_level.lower()}-{strftime('%Y-%m-%d_%H-%M-%S')}.log")

    def make_log_file_handler(log_file_dir: Path, log_level: str) -> logging.FileHandler:
        os.makedirs(log_file_dir, exist_ok=True)
        log_file_handler = logging.FileHandler(log_file_name(log_file_dir, log_level))
        log_file_handler.setFormatter(logging.Formatter(_LOGGING_FORMAT.format(thread_name_len=60)))
        return log_file_handler

    log_file_handler: Optional[logging.FileHandler] = None
    if log_file_dir is not None:
        log_file_handler = make_log_file_handler(log_file_dir, log_level)
        logging.getLogger().addHandler(log_file_handler)
        logging.info(f"Writing log to file {log_file_handler.baseFilename!r}")
    logging.info(f"Starting log for {sys.executable} with args {sys.argv}")

    application = Application(config_file)
    # overwrite parsed values from config.json with values from CLI options
    application.config.server_ip = server_ip
    application.config.server_base_port = server_base_port
    if ctx.get_parameter_source(f"enable_discovery") != click.core.ParameterSource.DEFAULT:
        application.config.enable_discovery = enable_discovery
    application.config.regenerate_certificates = regenerate_certificates
    application.config.scan_devices = scan_devices
    application.config.simulate_missing = simulate_missing
    application.config.sila = sila
    application.config.remote_objects = remote_objects
    if log_file_dir is not None:
        application.config.log_file_dir = log_file_dir

    # set log file dir from config.json if not given via CLI option
    if log_file_dir is None and application.config.log_file_dir is not None:
        log_file_dir = application.config.log_file_dir
        log_file_handler = make_log_file_handler(log_file_dir, log_level)
        logging.getLogger().addHandler(log_file_handler)
        logging.info(f"Writing log to file {log_file_handler.baseFilename!r}")

    # set logging level from config.json if not given via CLI option
    if (
        ctx.get_parameter_source(f"log_level") == click.core.ParameterSource.DEFAULT
        and log_level != application.config.log_level
    ):
        logging.info(f"Setting log level {application.config.log_level!r} from '{config_file}'")
        set_logging_level(application.config.log_level)
        if log_file_dir is not None and log_file_handler is not None:
            logging.getLogger().removeHandler(log_file_handler)
            log_file_handler = make_log_file_handler(log_file_dir, application.config.log_level)
            logging.getLogger().addHandler(log_file_handler)

    if not application.run():
        raise typer.Abort()


if __name__ == "__main__":
    app()
