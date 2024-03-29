import logging
import os
import platform
import sys

try:
    import coloredlogs
except ModuleNotFoundError:
    print("Cannot find coloredlogs! Please install coloredlogs, if you'd like to have nicer logging output:")
    print("`pip install coloredlogs`")

import sila_cetoni.config as config

resource_dir = os.path.join(os.path.dirname(__file__), "resources")

__all__ = ["resource_dir"]

_NO_EXEC_OPTION = "--no-exec"
_CETONI_SDK_PATH_KEY = "CETONI_SDK_PATH"

logger = logging.getLogger(__name__)
_logging_level = logging.ERROR if _NO_EXEC_OPTION in sys.argv else logging.INFO
LOGGING_FORMAT = "%(asctime)s [%(threadName)-12.12s] %(levelname)-8s| %(name)s %(module)s.%(funcName)s: %(message)s"
try:
    coloredlogs.install(fmt=LOGGING_FORMAT, datefmt="%Y-%m-%d %H:%M:%S,%f", level=_logging_level)
except NameError:
    logging.basicConfig(format=LOGGING_FORMAT, level=_logging_level)


if _CETONI_SDK_PATH_KEY in os.environ:
    config.CETONI_SDK_PATH = os.path.expanduser(os.environ.get(_CETONI_SDK_PATH_KEY))
    logger.info(f"Using SDK path from environment variable - setting SDK path to '{config.CETONI_SDK_PATH}'")
elif config.CETONI_SDK_PATH and os.path.exists(config.CETONI_SDK_PATH):
    logger.info(f"Setting SDK path to '{config.CETONI_SDK_PATH}'")
else:
    logger.warning(
        f"Did not find SDK path in CETONI_SDK_PATH environment variable and the directory '{config.CETONI_SDK_PATH}' "
        f"from {config.__file__} does not exist."
    )
    logger.info("Trying to autodetect SDK path... ")
    if platform.system() == "Windows":
        config.CETONI_SDK_PATH = os.path.join("C:\\", "CETONI_SDK")
        logger.info(f"Running on Windows - setting SDK path to '{config.CETONI_SDK_PATH}'")
    else:
        try:
            import RPi.GPIO as gpio

            config.CETONI_SDK_PATH = os.path.join(os.path.expanduser("~"), "CETONI_SDK_Raspi")
            logger.info(f"Running on RaspberryPi - setting SDK path to '{config.CETONI_SDK_PATH}'")
        except (ModuleNotFoundError, ImportError):
            if "Ubuntu" in os.uname().version:
                config.CETONI_SDK_PATH = os.path.join("/usr", "share", "qmix-sdk")
                logger.info(f"Running on Ubuntu Linux - setting SDK path to '{config.CETONI_SDK_PATH}'")
            else:
                config.CETONI_SDK_PATH = os.path.join(os.path.expanduser("~"), "CETONI_SDK")
                logger.info(f"Running on generic Linux - setting SDK path to '{config.CETONI_SDK_PATH}'")

# adjust PATH variable to point to the SDK
sys.path.append(config.CETONI_SDK_PATH)
sys.path.append(os.path.join(config.CETONI_SDK_PATH, "lib", "python"))

try:
    import qmixsdk

    logger.info(f"Found CETONI SDK in {config.CETONI_SDK_PATH}")
except (ModuleNotFoundError, ImportError) as err:
    if platform.system() == "Windows" or _NO_EXEC_OPTION in sys.argv:
        logger.error(
            f"Could not find CETONI SDK in {config.CETONI_SDK_PATH} - no support for CETONI devices!", exc_info=err
        )
    else:
        # setup the environment for python to find the SDK and for ctypes to load the shared libs properly
        env = os.environ.copy()
        env["PATH"] = os.pathsep.join((config.CETONI_SDK_PATH, env["PATH"]))
        env["PYTHONPATH"] = os.pathsep.join((os.path.join(config.CETONI_SDK_PATH, "python"), env.get("PYTHONPATH", "")))
        env["LD_LIBRARY_PATH"] = os.pathsep.join(
            (os.path.join(config.CETONI_SDK_PATH, "lib"), env.get("LD_LIBRARY_PATH", ""))
        )
        # uncomment the following line if you get an error like 'undefined symbol: __atomic_exchange_8'
        env["LD_PRELOAD"] = os.pathsep.join(
            ("/usr/lib/arm-linux-gnueabihf/libatomic.so.1.2.0", env.get("LD_PRELOAD", ""))
        )
        # logger.info(env)

        if sys.argv[0] == "-m":
            # started via `python -m sila_cetoni.application <args>`
            os.execve(sys.executable, [sys.executable, "-m", __name__] + [_NO_EXEC_OPTION] + sys.argv[1:], env)
        elif sys.argv[0].endswith("__init__.py") or sys.argv[0] == "":
            # imported via `import sila_cetoni.application` or in python console -> prevent calling os.execve in this case
            pass
        else:
            # started via `sila-cetoni <args>`
            os.execve(sys.argv[0], [sys.argv[0], _NO_EXEC_OPTION] + sys.argv[1:], env)
