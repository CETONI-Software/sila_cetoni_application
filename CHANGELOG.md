# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

<!--
Types of changes

    `Added` for new features.
    `Changed` for changes in existing functionality.
    `Deprecated` for soon-to-be removed features.
    `Removed` for now removed features.
    `Fixed` for any bug fixes.
    `Security` in case of vulnerabilities.
-->

## Unreleased

### Changed

- Allow to change the port of server(s) which had been run before on a certain port (i.e. where a server config file exists that remembers that port) to a different port by specifying the CLI option `-p`/`--server-base-port` or by changing the JSON config file option `"server_base_port"` when running the server(s) again.
- If you have servers that were run before with an older version, the server config file does not contain the used server base port and the only option to overwrite the server port is to use the CLI option `-p`/`--server-base-port`.

## v1.9.1

Sync with sila_cetoni v1.9.1 release

## v1.9.0

Sync with sila_cetoni v1.9.0 release

### Added

- `CetoniMobDosDevice` to represent a CETONI mobile dosage unit
- `SystemNotOperationalError` and `ApplicationSystem.ensure_operational` decorator to simplify raising an error when the `ApplicationSystem` is not in an operational state
- All `ApplicationSystem` classes gained the `shutdown` method to completely shutdown the application and the OS
- `CetoniApplicationSystem.monitor_traffic` decorator to mark feature implementation classes as "monitored". If no Command/Property has been called on the monitored Features then the application will automatically shut down on CETONI's MobDos (only if it is battery powered).
- New `"max_time_without_battery"` and `"max_time_without_traffic"` configuration options for the JSON config file (only applicable to CETONI MobDos devices)
- Support for simulated Shimadzu 2020 LC/MS
- Add option to enable/disable SiLA discovery (CLI: `--enable-discovery`/`--disable-discovery`, JSON: `"enable_discovery"`)
- If the `SILA_CETONI_SERVER_STARTED_FILE` environment variable is set to a file name, the application will create this file after all servers have been started successfully
- Add py.typed to make this package PEP 561 compatible
- The same server (with the same UUID) can now be run on multiple IP addresses (not at once but when the IP of the host changes, for example, due to a new IP being assigned by the network's DHCP server)
- Self-signed certificates which are close to expiry (< 30 days until *Not After*) or are already expired will now be automatically renewed
- The 64bit CETONI SDK is now also detected on Raspberry Pis
- Add experimental Qt Remote Objects support which can be enabled via CLI flags

### Changed

- Add-on packages are now dynamically discovered and the process of parsing the JSON configuration, creating the devices and servers is now decoupled
- Due to the looser coupling to add-on packages all specific device classes which belong to an add-on package have been moved to their respective add-on package
- For the same reason all specific options for the JSON configuration have been moved to the respective add-on packages, as well
- The JSON schema is now built out of the base schema located in this package and the schemas of all available add-on packages
- Use dynamic version from git in pyproject.toml
- `ServerConfiguration` now behaves like `ConfigParser` which has the advantage that add-on packages can easily add new sections/options (previously this would have required changes in sila_cetoni_application)
- `ServerConfiguration` behaves singleton-like such that there is only one unique instance per physical config file to prevent race conditions during writes

### Fixed

- CETONI SDK's new 'src' subfolder layout is now correctly supported
- A regenerated SSL certificate wasn't stored
- Errors during server creation are now caught and cause the application to exit
- Look for CETONI SDK in `/usr/share/cetoni-sdk` by default on Ubuntu and only use `/usr/share/qmix-sdk` as a fallback
- Fix an issue causing the MobDos to be powered off too early during a battery swap
- Fix an error due to missing `libatomic.so` on Linux systems
- Fix compatibility issues with PySide2 by attempting to import it before importing `qmixsdk`

## v1.8.0

Sync with sila_cetoni v1.8.0 release

### Added

- Support for RevolutionPi digital and analog I/O channels

### Changed

- `CetoniDevice` and `CetoniIODevice` use the agnostic `IOChannelInterface` subclasses now instead of the `qmixanalogio`/`qmixdigio` classes
- `ApplicationSystem` supports third-party I/O devices from the JSON configuration now
- The JSON schema was updated to allow specifying third-party I/O devices (currently only Kunbus' Revolution PI I/O modules are supported)
- Bump required sila2 version to v0.10.1
- Increase required Python version to 3.8 because in 3.7 the implementation of `ThreadPoolExecutor` in the standard library does not reuse idle threads leading to an ever increasing number of threads which eventually causes blocking of the server(s) on Raspberry Pis

### Fixed

- The server configuration files don't use the raw server name any more but a valid file name without any special characters
- A non-existent log file directory will be created automatically from now on
- Possible blocking during shutdown due to `ThirdPartyIODevice`'s I/O channels not being stopped
- Fix `NameError` on shutdown in `ServerConfiguration.__del__` because `open` is not defined any more

## v1.7.1

Sync with sila_cetoni v1.7.1 release

### Fixed

- Typo in pyproject.toml

## v1.7.0

Sync with sila_cetoni v1.7.0

### Changed

- Bump required sila2 version to v0.10.0

### Fixed

- Automatically simulating missing devices did not work if the device was detected as "missing" in `ApplicationSystem.start`

## v1.6.0

Sync with sila_cetoni v1.6.0

### Added

- Add option to automatically simulate missing devices

## v1.5.0

Sync with sila_cetoni v1.5.0

### Changed

- Third-party device classes to only contain the properties they actually need
- The main function now uses `@app.command` instead of `@app.callback`

### Fixed

- Errors during the startup of the application are now caught and result in a graceful exit of the application
- If parsing of the JSON config file fails, `RuntimeError`s will be generated with more descriptive error messages

## v1.4.2

### Fixed

- Non-present `log_file_dir` in the JSON config will not cause a crash any more
- Detection of battery

## v1.4.1

### Fixed

- Fix dependencies in pyproject.toml
- Fix log file handling when `log_file_dir` is only set in the JSON config but not via CLI option

## v1.4.0

Sync with sila_cetoni v1.4.0

## v1.3.1

### Fixed

- `ModuleNotFoundError`s when qmixsdk or another sila_cetoni module could not be found

## v1.3.0

Sync with sila_cetoni v1.3.0

### Added

- `ServerConfiguration` now saves the port that a server was started on

### Changed

- A server will be tried to be started on the same port as last time before falling back to the port calculated from the base port and the index of the server in the list of all servers

### Fixed

- The `-v/--version` CLI option of the main application no works as expected

## v1.2.0

Sync with sila_cetoni v1.2.0

### Added

- Support purification devices with sila_cetoni_purification
- Support stirring devices with sila_cetoni_stirring
- `--scan`/`--no-scan` CLI options to force scanning for devices like serial devices (the default is to not scan for devices)
- JSON configuration file concept (similar to CETONI device configurations but hand-written)
  - `sila-cetoni` now **requires** a configuration file in JSON format that describes the type and number of devices to start SiLA servers for
  - There is a distinction between CETONI devices and devices from other vendors (like Sartorius, Huber, etc.)
  - CETONI devices still require a CETONI device configuration folder, i.e. if you have CETONI devices in your system you need to specify the corresponding device config folder in the JSON config
  - All third-party devices are configured one by one and require at least a type and a manufacturer; depending on the device type you'll also need to specify device specific configuration options like a serial port or a server URL
- Third-party devices can be simulated now
  - There is an optional `simulated` property for devices in the JSON config file
  - Support for simulated Sartorius balances
  - Support for simulated Huber Chillers
  - Support for simulated Sartorius Arium purification devices
  - Support for simulated 2mag MIXdrive stirring devices

### Changed

- `sila-cetoni` can now be run completely without CETONI SDK
- Use the server name as the name for `ServerConfiguration`

## v1.1.0

### Added

- `~` path constructs in the `CETONI_SDK_PATH` environment variable can now be properly expanded
- Add CLI option to specify the IP address the servers should run on
- Add CLI option to force regeneration of the self-signed certificates
- New `HeatingCoolingDevice` device class for devices of sila_cetoni_heating_cooling

### Changed

- Bump sila2 to v0.8.2

### Fixed

- Fix dependencies in pyproject.toml
- Catch possible `TimeoutError` when starting the servers

## v1.0.0

First release of sila_cetoni

This is the main application plugin required to run sila_cetoni

### Added

- Main application logic for running sila_cetoni with a CETONI device configuration and without a device configuration
  for non-CETONI devices
