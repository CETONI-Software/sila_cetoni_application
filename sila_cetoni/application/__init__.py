import os
import platform
import sys

import sila_cetoni.config as config

_CETONI_SDK_PATH_KEY = "CETONI_SDK_PATH"

if _CETONI_SDK_PATH_KEY in os.environ:
    config.CETONI_SDK_PATH = os.environ.get(_CETONI_SDK_PATH_KEY)
    print(f"Using SDK path from environment variable - setting SDK path to {config.CETONI_SDK_PATH}")
elif config.CETONI_SDK_PATH:
    print(f"Setting SDK path to {config.CETONI_SDK_PATH}")
else:
    if platform.system() == "Windows":
        config.CETONI_SDK_PATH = os.path.join("C:\\", "CETONI_SDK")
        print(f"Running on Windows - setting SDK path to {config.CETONI_SDK_PATH}")
    else:
        try:
            import RPi.GPIO as gpio

            config.CETONI_SDK_PATH = os.path.join(os.path.expanduser("~"), "CETONI_SDK_Raspi")
            print(f"Running on RaspberryPi - setting SDK path to {config.CETONI_SDK_PATH}")
        except (ModuleNotFoundError, ImportError):
            if "Ubuntu" in os.uname().version:
                config.CETONI_SDK_PATH = os.path.join("/usr", "share", "qmix-sdk")
                print(f"Running on Ubuntu Linux - setting SDK path to {config.CETONI_SDK_PATH}")
            else:
                config.CETONI_SDK_PATH = os.path.join(os.path.expanduser("~"), "CETONI_SDK")
                print(f"Running on generic Linux - setting SDK path to {config.CETONI_SDK_PATH}")

        try:
            import qmixsdk
        except (ModuleNotFoundError, ImportError):
            # setup the environment for python to find the SDK and for ctypes to load the shared libs properly
            env = os.environ.copy()
            env["PATH"] = f"{config.CETONI_SDK_PATH}:{env['PATH']}"
            env["PYTHONPATH"] = f"{config.CETONI_SDK_PATH}/python:{env.get('PYTHONPATH', '')}"
            env["LD_LIBRARY_PATH"] = f"{config.CETONI_SDK_PATH}/lib:{env.get('LD_LIBRARY_PATH', '')}"
            # uncomment the following line if you get an error like 'undefined symbol: __atomic_exchange_8'
            # env["LD_PRELOAD"] = "/usr/lib/arm-linux-gnueabihf/libatomic.so.1.2.0"
            # print(env)

            if sys.argv[0] == "-m":
                # started via `python -m sila_cetoni.application <args>`
                os.execve(sys.executable, [sys.executable, "-m", __name__] + sys.argv[1:], env)
            else:
                # started via `sila-cetoni <args>`
                os.execve(sys.argv[0], sys.argv, env)
