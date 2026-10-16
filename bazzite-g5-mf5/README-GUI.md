# GFan Control desktop app

GFan Control is a small GTK4/libadwaita dashboard for the GIGABYTE G5 MF5. It displays the embedded controller's CPU/GPU temperature readings and each fan's duty readback and tachometer RPM. Fan tiles are labeled CPU Fan / EC Fan 1 and GPU Fan / EC Fan 2 as requested; the EC channel-to-physical-fan mapping has not been independently verified. The dark theme is forced for this app.

The window refreshes readings every 0.25 seconds when the status helper can keep up. The slider sets a shared manual value from 30% to 100%; no fan change occurs until **Apply to both fans** is clicked. **Enable Auto Curve** starts a software curve using the hottest available CPU/GPU reading: the CPU core maximum when `coretemp` is available, otherwise the CPU EC reading, plus the GPU EC reading. It writes the same duty to both fans. The curve holds 40% below 50°C, then uses 55% at 50°C, 65% at 60°C, 80% at 70°C, and 100% at 80°C. Increases require two consecutive readings; decreases step down one level after cooling at least 5°C below that level's threshold. Commands are sent only when the target changes.

The curve is active only while the GUI is running. Stopping it leaves the last manual duty in place. **Firmware Auto** explicitly returns control to firmware; on this laptop, firmware automatic mode does not provide the Linux fan ramp this curve is intended to supply. The curve does not start at login or boot, so keep the window open while it is enabled.

The GUI stays unprivileged. A narrowly scoped Polkit rule starts a root-owned helper, which accepts only status, shared percentage, and firmware-auto requests and invokes `/usr/local/bin/gfan`. It does not add a sudoers rule or background service. A running Polkit agent is required. The app expects the already installed CLI. Python GTK4 and libadwaita were present on the validated Bazzite host.

## Install on Bazzite

Download and extract the `gfan-bazzite-g5-mf5-<version>.tar.gz` asset from [the fork's Releases page](https://github.com/jtm2kfpv-git/gigactl-g5-mf5/releases). Open a terminal in the extracted folder and run:

```bash
./install-bazzite.sh
```

Run it as your normal desktop account, without `sudo`; it requests administrator authentication itself. The installer builds the bundled `acpi_ec` source for the running kernel, installs the root-owned `gfan` command and Polkit helper, creates a narrowly scoped rule for the current account, installs the app and menu entry, and creates `GFan Control.desktop` in the Desktop folder when one exists. It then loads the module if needed and runs `gfan status`. That final check only reads telemetry; installation never sets fan speed.

The installer refuses systems other than Bazzite on the GIGABYTE G5 MF5. It requires matching kernel build files at `/usr/lib/modules/$(uname -r)/build`, `make`, `/usr/bin/python3` with GTK4/libadwaita, `pkexec`, and Secure Boot disabled. If matching build files are absent, run `rpm-ostree install kernel-devel-matched gcc make`, reboot into the new deployment, then rerun the installer. Secure Boot module signing is not implemented. If GTK bindings are absent, the installer prints the corresponding `rpm-ostree` command and asks you to reboot and rerun.

To remove the installation, use the extracted folder and run `./install-bazzite.sh --uninstall`. It first asks `gfan` to return control to firmware, then removes the installed CLI, helper, Polkit rule, app files and the module for the currently running kernel. It unloads `acpi_ec` only if the kernel permits it. After a kernel update, rerun the installer with build files matching that kernel; automatic rebuild and boot-time loading are intentionally not configured.

## Curve behavior and limits

`gfan_curve.py` contains the pure curve controller. Invalid or implausible sensor values pause the curve and leave the fans at their last verified manual duty; the GUI reports the fault and retries status reads. The CLI permits only 100% at 95°C or hotter, and refuses duties below 70% from 85°C upward. If a temperature guard trips during an in-progress write, it attempts a verified safety duty of 80% from 85°C or 100% from 95°C, keeping firmware control disabled. Other write failures retain the CLI's firmware-recovery behavior. Temperature and RPM status reads use a separate helper session and can continue every 0.25 seconds during fan duty verification, subject to EC read time and system load.

The curve writes the same setting to both EC channels. The CPU/GPU fan labels are still an assumed mapping and must be verified on the hardware.
