import os
import platform
import sys

# Change this to point to your CETONI SDK installation path
if platform.system() == "Windows":
    CETONI_SDK_PATH = os.path.join("C:\\", "CETONI_SDK")
    print(f"Running on Windows - setting SDK path to {CETONI_SDK_PATH}")
else:
    try:
        import RPi.GPIO as gpio

        CETONI_SDK_PATH = os.path.join(os.path.expanduser("~"), "CETONI_SDK_Raspi")
        print(f"Running on RaspberryPi - setting SDK path to {CETONI_SDK_PATH}")
    except (ModuleNotFoundError, ImportError):
        pass

    if "Ubuntu" in os.uname().version:
        CETONI_SDK_PATH = os.path.join("/usr", "share", "qmix-sdk")
        print(f"Running on Ubuntu Linux - setting SDK path to {CETONI_SDK_PATH}")
    else:
        CETONI_SDK_PATH = os.path.join(os.path.expanduser("~"), "CETONI_SDK")
        print(f"Running on generic Linux - setting SDK path to {CETONI_SDK_PATH}")

    try:
        import qmixsdk

        # If we were called via `sila-cetoni <args>` we get an ImportError in the sila-cetoni script saying that 'main'
        # cannot be imported from 'sila_cetoni.application'. I don't exactly know why, but importing it here seems to
        # fix this error.
        from .__main__ import main
    except (ModuleNotFoundError, ImportError):
        # setup the environment for python to find the SDK and for ctypes to load the shared libs properly
        env = os.environ.copy()
        env["PATH"] = f"{CETONI_SDK_PATH}:{env['PATH']}"
        env["PYTHONPATH"] = f"{CETONI_SDK_PATH}/python:{env.get('PYTHONPATH', '')}"
        env["LD_LIBRARY_PATH"] = f"{CETONI_SDK_PATH}/lib:{env.get('LD_LIBRARY_PATH', '')}"
        # print(env)

        if sys.argv[0] == "-m":
            # started via `python -m sila_cetoni.application <args>`
            os.execve(sys.executable, [sys.executable, "-m", __name__] + sys.argv[1:], env)
        else:
            # started via `sila-cetoni <args>`
            os.execve(sys.argv[0], sys.argv, env)
