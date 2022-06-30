__version__ = "0.1.0"

import logging
from pathlib import Path
from typing import Optional

import typer

try:
    import coloredlogs
except ModuleNotFoundError:
    print("Cannot find coloredlogs! Please install coloredlogs, if you'd like to have nicer logging output:")
    print("`pip install coloredlogs`")

from .application import DEFAULT_BASE_PORT, Application

app = typer.Typer()


def set_logging_level(log_level: str):

    logging_level = log_level.upper()
    LOGGING_FORMAT = "%(asctime)s [%(threadName)-12.12s] %(levelname)-8s| %(name)s %(module)s.%(funcName)s: %(message)s"
    try:
        coloredlogs.install(fmt=LOGGING_FORMAT, datefmt="%Y-%m-%d %H:%M:%S,%f", level=logging_level)
    except NameError:
        logging.basicConfig(format=LOGGING_FORMAT, level=logging_level)


# -----------------------------------------------------------------------------
# main program
@app.callback(
    invoke_without_command=True, no_args_is_help=False, context_settings={"help_option_names": ["-h", "--help"]}
)
def main(
    version: Optional[bool] = typer.Option(
        None, "--version", "-v", help="Show the application's version number and exit"
    ),
    log_level: str = typer.Option(
        "INFO",  # or use "error" for less output
        "--log-level",
        "-l",
        callback=set_logging_level,
        metavar="LEVEL",
        help="Set the logging level of the application",
        case_sensitive=False,
        formats=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
    ),
    config_path: Optional[Path] = typer.Option(
        None,
        "--config_path",
        "-c",
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
        resolve_path=True,
        allow_dash=False,
        metavar="CONFIG_PATH",
        help=(
            "Path to a valid CETONI device configuration folder (This is only necessary if you want to control CETONI "
            "devices. Controlling other devices that have their own drivers in the 'device_drivers' subdirectory don't "
            "need a configuration. If you don't have a configuration yet, create one with the CETONI Elements software "
            "first.)"
        ),
    ),
    server_base_port: int = typer.Option(
        DEFAULT_BASE_PORT, "--server-base-port", "-p", metavar="PORT", help="The port number for the first SiLA Server"
    ),
):
    """
    Launches as many SiLA 2 servers as there are CETONI devices in the configuration
    """
    Application(config_path, server_base_port).run()


if __name__ == "__main__":
    app()
