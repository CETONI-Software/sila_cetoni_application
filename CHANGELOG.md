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

- Third-party device classes to only contain the properties they actually need

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
