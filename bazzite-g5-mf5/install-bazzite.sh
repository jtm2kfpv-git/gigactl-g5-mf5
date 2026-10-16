#!/usr/bin/env bash
# Install the independent G5 MF5 GFan CLI and desktop app on Bazzite.
set -Eeuo pipefail

VERSION="0.2.0"
SYSTEM_BIN="/usr/local/bin/gfan"
HELPER="/usr/local/libexec/gfan-ui-helper"
MODULE_ROOT="/usr/local/lib/bazzite-fan-control"
POLKIT_RULE="/etc/polkit-1/rules.d/50-gfan-control.rules"
APP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/gfan-control"
APPLICATIONS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"

usage() {
    cat <<EOF
GFan Control installer $VERSION for the GIGABYTE G5 MF5 on Bazzite

Usage:
  ./install-bazzite.sh             Install the CLI, GUI and desktop launcher
  ./install-bazzite.sh --uninstall Remove this install and return fans to firmware
  ./install-bazzite.sh --help      Show this help

Run as your normal desktop user, without sudo. The installer asks for your
password when it needs administrator access.
EOF
}

die() { printf 'GFan installer: ERROR: %s\n' "$*" >&2; exit 1; }
note() { printf '\nGFan installer: %s\n' "$*"; }

[[ ${EUID} -ne 0 ]] || die "Run this installer as your normal desktop user, not with sudo."
[[ -n ${HOME:-} && -d $HOME ]] || die "Your home directory is unavailable."

if [[ ${1:-} == --help || ${1:-} == -h ]]; then
    usage
    exit 0
fi

if [[ ${1:-} == --uninstall ]]; then
    note "Returning both fans to firmware control before removing GFan Control."
    sudo -v
    if [[ -x $SYSTEM_BIN ]]; then
        sudo "$SYSTEM_BIN" auto || die "Could not return fans to firmware control; nothing was removed."
    fi
    sudo rm -f -- "$SYSTEM_BIN" "$HELPER" "$POLKIT_RULE"
    sudo rm -f -- "/usr/local/share/man/man8/gfan.8" "/usr/local/share/doc/gfan/gfan-manual.txt"
    sudo rm -f -- "$MODULE_ROOT/$(uname -r)/acpi_ec.ko"
    sudo rmdir --ignore-fail-on-non-empty "$MODULE_ROOT/$(uname -r)" "$MODULE_ROOT" 2>/dev/null || true
    rm -f -- "$APPLICATIONS_DIR/gfan-control.desktop" "$APP_DIR/gfan_ui.py" "$APP_DIR/gfan_curve.py" "$APP_DIR/gfan_load.py"
    rmdir --ignore-fail-on-non-empty "$APP_DIR" 2>/dev/null || true
    desktop_dir="$(xdg-user-dir DESKTOP 2>/dev/null || true)"
    [[ -n $desktop_dir ]] || desktop_dir="$HOME/Desktop"
    rm -f -- "$desktop_dir/GFan Control.desktop"
    if sudo rmmod acpi_ec 2>/dev/null; then
        note "Removed the GFan files and unloaded acpi_ec."
    else
        note "Removed the GFan files. acpi_ec stayed loaded because it is in use or was not loaded."
    fi
    exit 0
fi

[[ $# -eq 0 ]] || { usage >&2; exit 2; }

[[ -r /etc/os-release ]] || die "Cannot identify this Linux installation."
# shellcheck disable=SC1091
source /etc/os-release
[[ ${ID:-} == bazzite || ${ID_LIKE:-} == *bazzite* ]] || die "This installer supports Bazzite only (detected ${PRETTY_NAME:-unknown})."

dmi=/sys/class/dmi/id
[[ -r $dmi/sys_vendor && -r $dmi/product_name ]] || die "Laptop model information is unavailable."
vendor="$(<"$dmi/sys_vendor")"
model="$(<"$dmi/product_name")"
[[ $vendor == GIGABYTE && $model == 'G5 MF5' ]] || die "This build supports GIGABYTE G5 MF5 only (detected '$vendor $model')."

for file in gfan.py gfan_ui.py gfan_curve.py gfan_load.py gfan_ui_helper.py gfan-control.desktop 50-gfan-control.rules.in gfan.8 gfan-manual.txt acpi_ec/UPSTREAM.md acpi_ec/Makefile acpi_ec/src/Makefile acpi_ec/src/acpi_ec.c acpi_ec/LICENSE; do
    [[ -f $SOURCE_DIR/$file ]] || die "Installer package is incomplete; missing $file. Extract the complete release archive and try again."
done

PYTHON=/usr/bin/python3
[[ -x $PYTHON ]] || die "Bazzite's /usr/bin/python3 was not found."
"$PYTHON" - <<'PY' || die "GTK4/libadwaita Python bindings are missing. On Bazzite install them with: rpm-ostree install python3-gobject gtk4 libadwaita; reboot, then run this installer again."
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk
PY

for command in sudo make; do
    command -v "$command" >/dev/null 2>&1 || die "Required command '$command' is missing."
done
[[ -x /usr/bin/pkexec ]] || die "pkexec is missing; install/enable Bazzite's Polkit support before continuing."
[[ -x /usr/bin/busctl && -x /usr/bin/systemctl && -x /usr/sbin/insmod ]] || die "Required Bazzite system tools (busctl, systemctl, insmod) are missing."

user_name="$(id -un)"
[[ $user_name =~ ^[a-z_][a-z0-9_-]*\$?$ ]] || die "The current account name cannot safely be written into the Polkit rule."

kernel="$(uname -r)"
kernel_build="/usr/lib/modules/$kernel/build"
[[ -e $kernel_build/Makefile ]] || die "Matching build files for kernel '$kernel' are not installed. Install them with 'rpm-ostree install kernel-devel-matched gcc make', reboot into the new deployment, then rerun this installer. No application files have been installed."

if command -v mokutil >/dev/null 2>&1 && mokutil --sb-state 2>/dev/null | grep -qi enabled; then
    die "Secure Boot is enabled. This installer does not sign kernel modules; disable Secure Boot or arrange module signing before installation. No application files have been installed."
fi

# Do not silently replace another project's gfan executable or Polkit policy.
if [[ -e $SYSTEM_BIN ]] && ! grep -qF 'Manual G5 MF5 fan control' "$SYSTEM_BIN"; then
    die "$SYSTEM_BIN already exists and is not this G5 MF5 build. Remove/rename the conflicting installation first."
fi
if [[ -e $POLKIT_RULE ]] && ! grep -qF 'gfan-ui-helper' "$POLKIT_RULE"; then
    die "$POLKIT_RULE already exists and is not a GFan Control rule. Review it before installing."
fi

note "Building acpi_ec for the running kernel $kernel."
build_dir="$(mktemp -d "${TMPDIR:-/tmp}/gfan-install.XXXXXXXX")"
trap 'rm -rf -- "$build_dir"' EXIT
cp -a -- "$SOURCE_DIR/acpi_ec/." "$build_dir/"
make -s -C "$kernel_build" M="$build_dir" modules
module="$build_dir/src/acpi_ec.ko"
[[ -s $module ]] || die "Kernel build completed without producing acpi_ec.ko."

note "Installing GFan Control for $user_name."
sudo -v
sudo install -d -m 0755 /usr/local/bin /usr/local/libexec "$MODULE_ROOT/$kernel" \
    /usr/local/share/man/man8 /usr/local/share/doc/gfan /etc/polkit-1/rules.d
sudo install -o root -g root -m 0755 "$SOURCE_DIR/gfan.py" "$SYSTEM_BIN"
sudo install -o root -g root -m 0755 "$SOURCE_DIR/gfan_ui_helper.py" "$HELPER"
sudo install -o root -g root -m 0644 "$module" "$MODULE_ROOT/$kernel/acpi_ec.ko"
sudo install -o root -g root -m 0644 "$SOURCE_DIR/gfan.8" /usr/local/share/man/man8/gfan.8
sudo install -o root -g root -m 0644 "$SOURCE_DIR/gfan-manual.txt" /usr/local/share/doc/gfan/gfan-manual.txt

sed "s/@GFAN_USER@/$user_name/g" "$SOURCE_DIR/50-gfan-control.rules.in" \
    | sudo tee "$POLKIT_RULE" >/dev/null
sudo chown root:root "$POLKIT_RULE"
sudo chmod 0644 "$POLKIT_RULE"

install -d -m 0755 "$APP_DIR" "$APPLICATIONS_DIR"
install -m 0644 "$SOURCE_DIR/gfan_ui.py" "$APP_DIR/gfan_ui.py"
install -m 0644 "$SOURCE_DIR/gfan_curve.py" "$APP_DIR/gfan_curve.py"
install -m 0644 "$SOURCE_DIR/gfan_load.py" "$APP_DIR/gfan_load.py"
install -m 0644 "$SOURCE_DIR/gfan-control.desktop" "$APPLICATIONS_DIR/gfan-control.desktop"

desktop_dir="$(xdg-user-dir DESKTOP 2>/dev/null || true)"
[[ -n $desktop_dir ]] || desktop_dir="$HOME/Desktop"
if [[ -d $desktop_dir ]]; then
    install -m 0755 "$SOURCE_DIR/gfan-control.desktop" "$desktop_dir/GFan Control.desktop"
    note "Created a desktop shortcut at $desktop_dir/GFan Control.desktop."
else
    note "No desktop folder exists; GFan Control is available in the application menu."
fi

if [[ ! -e /dev/ec ]]; then
    note "Loading the kernel module. This only enables EC access; it does not change fan speed."
    sudo /usr/sbin/insmod "$MODULE_ROOT/$kernel/acpi_ec.ko" || die "The kernel rejected acpi_ec. Check Secure Boot, kernel headers and the error above. The files are installed; run './install-bazzite.sh' again after resolving the issue."
fi
for _ in {1..50}; do
    [[ -c /dev/ec ]] && break
    sleep 0.1
done
[[ -c /dev/ec ]] || die "acpi_ec loaded but did not create /dev/ec. See 'sudo dmesg' for the module error."

note "Checking read-only EC telemetry. No fan command will be sent."
if ! sudo "$SYSTEM_BIN" status; then
    die "The files are installed, but the read-only hardware check failed. Review the error above before opening GFan Control."
fi

note "Installation complete. Open GFan Control from the desktop shortcut or the application menu. Manual changes require clicking Apply; Auto Curve runs only while enabled and the window stays open."
note "The software curve is not enabled at boot. Keep the app open while Auto Curve is active."
