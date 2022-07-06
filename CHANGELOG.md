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
