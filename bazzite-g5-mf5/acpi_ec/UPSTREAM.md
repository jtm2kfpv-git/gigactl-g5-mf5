# Bundled kernel module source

This directory contains the minimum source files needed to build `acpi_ec`,
copied from [saidsay-so/acpi_ec](https://github.com/saidsay-so/acpi_ec) at
commit [`e83e5a6122e15a83cc52883ac24bf9b1880fd53c`](https://github.com/saidsay-so/acpi_ec/commit/e83e5a6122e15a83cc52883ac24bf9b1880fd53c).
The upstream `LICENSE` is included. The module is GPL-3.0; this fan-control
subproject uses its `/dev/ec` interface and does not modify the module source.

The installer builds it against the exact running kernel. It does not install
the upstream project's DKMS scripts, key-generation scripts, or system-wide
module hooks.
