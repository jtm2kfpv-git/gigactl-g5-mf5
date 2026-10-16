# Manual fan control — GIGABYTE G5 MF5 on Bazzite

This project provides a small Python command and desktop GUI for manual fan control plus an opt-in software cooling curve. It does not use the upstream daemon. The kernel-mediated EC transport is the upstream `acpi_ec` module at commit `e83e5a6122e15a83cc52883ac24bf9b1880fd53c` from [saidsay-so/acpi_ec](https://github.com/saidsay-so/acpi_ec). **Protocol research attribution:** this subproject uses the reverse-engineered fan mailbox sequence, EC register map, and RPM calculation documented by [smairio/gigactl](https://github.com/smairio/gigactl), specifically [`docs/PROTOCOL.md` at commit `7c1a34b23ca0899876c98742ffe52019bb077fec`](https://github.com/smairio/gigactl/blob/7c1a34b23ca0899876c98742ffe52019bb077fec/docs/PROTOCOL.md). The G5 MF5 CLI, desktop GUI, helper, and cooling curve here are a separate implementation; the upstream `gigactld` daemon and GUI are not installed by this subproject. See [the GUI guide](README-GUI.md) and [gfan manual page](gfan.8).

## Installation status

The Bazzite release archive includes a guided installer for the CLI, dark GTK app, Polkit helper/rule, desktop-menu entry, desktop shortcut, manual page, and matching `acpi_ec` kernel module. Download and extract `gfan-bazzite-g5-mf5-<version>.tar.gz` from [GitHub Releases](https://github.com/jtm2kfpv-git/gigactl-g5-mf5/releases), open a terminal in the extracted folder, and run `./install-bazzite.sh`. It asks for administrator authentication, builds the module for the running kernel, installs the files, loads the module, and performs a read-only telemetry check. It does not set fan speed during installation. See the [installer guide](README-GUI.md) for prerequisites, kernel updates, and removal.

The installer supports Bazzite on the GIGABYTE G5 MF5 only. It requires matching kernel build files, `make`, Python GTK4/libadwaita bindings, Polkit, and Secure Boot disabled; it stops with a specific instruction if a prerequisite is missing. External-module signing and automatic rebuild after kernel updates are not included. After a kernel update, run the installer again with build files matching the new running kernel. See the [hardware-validation notes](HARDWARE-VALIDATION.md) and the [2026-10-16 Auto Curve load-test capture](validation-2026-10-16/README.md) for measured behavior and remaining checks.

## Commands on the laptop

```bash
sudo gfan status           # temperatures, raw duty bytes and approximate tach RPM
sudo gfan 60               # both fans at 60%; remains fixed after exit
sudo gfan 60 70            # fan 1 at 60%, fan 2 at 70%
sudo gfan max              # both fans at 100%
sudo gfan auto             # give both fans back to firmware
sudo gfan test 60 --seconds 10  # increase-only trial; restore firmware afterward
```

Use the single-percentage form initially. The two register/command channels are observed, but physical CPU/GPU cooling responsibility has not been independently identified. Duty percentage is a command value, not a percentage of maximum measured RPM. Raw duty 153 corresponds to 60%.

Manual values are restricted to 30–100%. Implausible EC temperatures are rejected; requests below 70% are rejected when either EC component or a coretemp sensor is at least 85°C. All manual requests are rejected at 95°C. These checks occur during the command, not continuously after it exits. `auto` remains available even at high temperatures. Opening the GUI automatically starts its software curve after the first valid temperature reading; you can stop it in the window. It only runs while the GUI stays open and is not started at boot.

The CLI serializes its own operations using `/run/lock/gigactl-ec.lock`, refuses when gigactld or known competing controllers are active, waits for mailbox acknowledgement, and checks duty readback. Errors after a set begins trigger independent restoration attempts for both fans. A short `test` also restores on Ctrl+C, SIGHUP or SIGTERM. SIGKILL, a kernel/device hang, machine failure, or another controller can prevent software cleanup; no claim of unconditional recovery is made. A successful ordinary `gfan 60` intentionally leaves the requested duty in place.

## Installed paths

- `/usr/local/bin/gfan`: root-owned CLI, mode 0755.
- `/usr/local/lib/bazzite-fan-control/<kernel-release>/acpi_ec.ko`: module built for the current kernel, root-owned mode 0644.
- `/dev/ec`: root-only EC character device, created by the loaded module.
- `/run/gfan-manual.json`: transient record of the last successfully requested manual duty, removed by `auto`. It is not used as proof of hardware mode or restored at boot.
- `~/.local/share/bazzite-fan-control/`: laptop staging/source/build directory.

The `/usr/local` location is writable persistent storage on this Atomic installation. No `rpm-ostree` layering, `/usr` unlock, initramfs change, modules-load configuration, sudoers rule, background fan service, or package installation was needed. Existing CoolerControl and TuneD were left running.

## Kernel updates and reboots

The module was loaded temporarily. On a later invocation, gfan loads the root-owned module matching the **running** kernel if `/dev/ec` is absent. This is command-triggered, not boot-time loading. That reload path is tested separately from a reboot; reboot behavior itself has not been tested.

After a kernel update, the old binary cannot be used for the new kernel. Until a matching module is built and copied, gfan fails with an actionable error and does not fall back to raw ports. Build against the exact running kernel headers:

```bash
build="$HOME/.local/share/bazzite-fan-control/build/acpi_ec"
make -C "/usr/lib/modules/$(uname -r)/build" M="$build" modules
sudo install -d -m 755 "/usr/local/lib/bazzite-fan-control/$(uname -r)"
sudo install -m 644 "$build/src/acpi_ec.ko" "/usr/local/lib/bazzite-fan-control/$(uname -r)/acpi_ec.ko"
sudo gfan status
```

If headers or compilation fail, retain firmware control until resolved. Secure Boot was disabled during validation; Secure Boot signing/enrollment has not been implemented. The upstream module's general installation scripts were not run.

## Local validation

```powershell
python -m pytest -q
```

The focused suite covers successful and silently rejected duty writes, hot/invalid temperatures, restoration attempts for both fans when the first fails, invalid percentages, and rollback after a partial two-fan failure. Hardware validation and remaining limits are recorded in `HARDWARE-VALIDATION.md`.

## Removal

First run `sudo gfan auto` and verify the fans have returned to normal firmware behavior. Then remove the specific installed `/usr/local/bin/gfan` and `/usr/local/lib/bazzite-fan-control/<kernel>/acpi_ec.ko` files if desired, and unload `acpi_ec` with `sudo rmmod acpi_ec` once no process has `/dev/ec` open. Do not unload the interface as a substitute for returning the fans to firmware control: removing a driver does not itself send firmware-auto commands.

## Next stage

The GUI software curve uses the hottest available CPU/GPU temperature, hysteresis, separate telemetry polling, and the shared EC command path. It starts when the GUI opens and requires the window to stay open.
