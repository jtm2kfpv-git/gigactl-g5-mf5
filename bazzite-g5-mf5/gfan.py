#!/usr/bin/python3
"""Manual G5 MF5 fan control using kernel-mediated /dev/ec only.

Protocol: smairio/gigactl commit 7c1a34b (MIT), docs/PROTOCOL.md.
This independent CLI deliberately does not run an automatic curve engine.
"""
import argparse
import contextlib
import glob
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import time

VERSION = "0.1.0"
LOCK = "/run/lock/gigactl-ec.lock"
STATE = Path("/run/gfan-manual.json")
FANS = (1, 2)


def check_model():
    dmi = Path("/sys/class/dmi/id")
    if (dmi / "sys_vendor").read_text().strip() != "GIGABYTE" or (dmi / "product_name").read_text().strip() != "G5 MF5":
        raise RuntimeError("This build is restricted to GIGABYTE G5 MF5.")


def check_writers():
    result = subprocess.run(["/usr/bin/busctl", "--system", "call", "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "NameHasOwner", "s", "io.github.smairio.gigactl"], capture_output=True, text=True, timeout=5)
    if result.returncode or result.stdout.strip() != "b false":
        raise RuntimeError("gigactld is running, or its absence cannot be established.")
    for unit in ("nbfc_service", "nbfc", "fancontrol"):
        result = subprocess.run(["/usr/bin/systemctl", "is-active", unit], capture_output=True, text=True, timeout=5)
        if result.stdout.strip() in ("active", "activating", "reloading"):
            raise RuntimeError(f"Competing fan controller: {unit}. Stop it before using gfan.")


def ensure_device():
    if not Path("/dev/ec").exists():
        module = Path("/usr/local/lib/bazzite-fan-control") / os.uname().release / "acpi_ec.ko"
        if not module.is_file():
            raise RuntimeError("No /dev/ec or module built for this kernel. Rebuild acpi_ec; raw-port fallback is disabled.")
        subprocess.run(["/usr/sbin/insmod", str(module)], check=True, timeout=10)
    info = os.lstat("/dev/ec")
    if not stat.S_ISCHR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o077:
        raise RuntimeError("/dev/ec must be a root-owned character device with mode 0600.")


@contextlib.contextmanager
def lock_ec():
    import fcntl
    fd = os.open(LOCK, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        deadline = time.monotonic() + 5
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("Another EC operation holds the lock.")
                time.sleep(0.05)
        yield
    finally:
        os.close(fd)


class EC:
    def __init__(self, writable=False):
        self.fd = os.open("/dev/ec", (os.O_RDWR if writable else os.O_RDONLY) | os.O_NOFOLLOW | os.O_CLOEXEC)

    def close(self):
        os.close(self.fd)

    def read(self, offset):
        value = os.pread(self.fd, 1, offset)
        if len(value) != 1:
            raise OSError(f"Short EC read at {offset:#x}")
        return value[0]

    def write(self, offset, value):
        if os.pwrite(self.fd, bytes([value]), offset) != 1:
            raise OSError(f"Short EC write at {offset:#x}")

    def wait_mailbox(self):
        deadline = time.monotonic() + 2
        while self.read(0xF8):
            if time.monotonic() >= deadline:
                raise RuntimeError("EC mailbox did not acknowledge the command.")
            time.sleep(0.02)

    def command(self, sub, value):
        self.wait_mailbox()
        self.write(0xF9, sub)
        self.write(0xFA, value)
        self.write(0xF8, 0xC1)
        self.wait_mailbox()


def snapshot(ec):
    periods = [(ec.read(hi) << 8) | ec.read(hi + 1) for hi in (0xD0, 0xD2)]
    return {"cpu_c": ec.read(7), "gpu_c": ec.read(10),
            "cpu_core_c": cpu_core_temperature(),
            "duty_raw": [ec.read(0xCE), ec.read(0xCF)],
            "rpm": [0 if p == 0 or p >= 0xFF00 else 2156220 // p for p in periods]}


def show(ec):
    data = snapshot(ec)
    print(json.dumps(data), flush=True)
    return data


def cpu_core_temperature():
    readings = []
    for hwmon in glob.glob("/sys/class/hwmon/hwmon*"):
        try:
            if Path(hwmon, "name").read_text().strip() != "coretemp":
                continue
        except OSError:
            continue
        for path in glob.glob(hwmon + "/temp*_input"):
            try:
                value = int(Path(path).read_text()) / 1000
            except (OSError, ValueError):
                continue
            if 1 <= value <= 110:
                readings.append(value)
    return max(readings, default=None)


def hottest_temperature(data):
    if not all(1 <= data[k] <= 110 for k in ("cpu_c", "gpu_c")):
        raise RuntimeError("EC temperatures are implausible; refusing manual control.")
    temps = [data["cpu_c"], data["gpu_c"]]
    if data.get("cpu_core_c") is not None:
        temps.append(data["cpu_core_c"])
    return max(temps)


def guard(data, targets):
    hottest = hottest_temperature(data)
    if (hottest >= 95 and min(targets) < 100) or (hottest >= 85 and min(targets) < 70):
        raise RuntimeError(f"Temperature guard: {hottest:g} C; at >=95 C only 100% duty is allowed, and at >=85 C duty below 70% is refused.")


def hot_guard_recovery_duty(hottest):
    if hottest >= 95:
        return 100
    if hottest >= 85:
        return 80
    return None


def restore(ec):
    errors = []
    for fan in FANS:
        try:
            ec.command(0xFF, fan)
        except Exception as exc:
            errors.append(f"fan {fan}: {exc}")
    if errors:
        raise RuntimeError("Firmware restore failed: " + "; ".join(errors))
    STATE.unlink(missing_ok=True)
    print("Firmware-auto commands acknowledged for both fans.", flush=True)


def set_duties(ec, targets, timeout=30):
    guard(snapshot(ec), targets)
    raw = [round(p * 255 / 100) for p in targets]
    for fan, duty in zip(FANS, raw):
        ec.command(fan, duty)
    deadline = time.monotonic() + timeout
    while True:
        data = show(ec)
        guard(data, targets)
        matched = all(abs(a-b) <= 10 for a, b in zip(data["duty_raw"], raw))
        if matched:
            return data
        if time.monotonic() >= deadline:
            raise RuntimeError("Fan duty readback did not reach the requested values.")
        time.sleep(0.5)


def percent(value):
    number = int(value)
    if not 30 <= number <= 100:
        raise argparse.ArgumentTypeError("Manual duty must be 30..100%; use auto for firmware control.")
    return number


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?", default="status", help="status, auto, max, test, or 30..100")
    parser.add_argument("values", nargs="*", type=percent)
    parser.add_argument("--seconds", type=int, default=10, help="test hold duration (1..30 seconds)")
    parser.add_argument("--version", action="version", version=VERSION)
    args = parser.parse_args()
    if args.command in ("status", "auto", "max") and args.values:
        parser.error("This command takes no percentages.")
    targets = None
    if args.command == "test":
        if len(args.values) != 1 or not 1 <= args.seconds <= 30:
            parser.error("Use: gfan test PERCENT --seconds 1..30")
        targets = args.values * 2
    elif args.command == "max":
        targets = [100, 100]
    elif args.command not in ("status", "auto"):
        try:
            first = percent(args.command)
        except (ValueError, argparse.ArgumentTypeError) as exc:
            parser.error(str(exc))
        if len(args.values) > 1:
            parser.error("Use one percentage for both fans or two percentages for fan1/fan2.")
        targets = [first, args.values[0] if args.values else first]
    if os.geteuid() != 0:
        raise RuntimeError("Run with sudo: sudo gfan " + " ".join(sys.argv[1:]))
    check_model()
    # Recovery must remain available if another service has started since a set.
    if args.command != "auto":
        check_writers()
    ensure_device()
    # Status only reads telemetry registers, so it may refresh during a long
    # manual write. All mailbox writers still share the exclusive EC lock.
    operation_lock = contextlib.nullcontext() if args.command == "status" else lock_ec()
    with operation_lock:
        ec = EC(writable=args.command != "status")
        touched = False
        emergency_handled = False
        try:
            if args.command == "status":
                show(ec)
                print("Duty/RPM are readback; firmware/manual mode is not directly observable.")
            elif args.command == "auto":
                restore(ec)
                show(ec)
            else:
                # A trial never decreases either fan from its starting duty.
                before = snapshot(ec)
                guard(before, targets)
                if args.command == "test" and any(round(p*255/100) < raw for p, raw in zip(targets, before["duty_raw"])):
                    raise RuntimeError("test must increase or preserve both current fan duties.")
                touched = True  # covers partial first/second fan failure too
                set_duties(ec, targets)
                if args.command == "test":
                    deadline = time.monotonic() + args.seconds
                    while time.monotonic() < deadline:
                        time.sleep(1)
                        guard(show(ec), targets)
                    restore(ec)
                    touched = False
                else:
                    STATE.write_text(json.dumps({"requested_percent": targets, "time": time.time()}))
                    print("Verified manual duty. It stays fixed until 'sudo gfan auto'; no background temperature supervision.")
                    touched = False
        except BaseException as exc:
            if touched:
                try:
                    if "Temperature guard" in str(exc):
                        emergency_snapshot = snapshot(ec)
                        hottest = hottest_temperature(emergency_snapshot)
                        emergency_duty = hot_guard_recovery_duty(hottest)
                        if emergency_duty is not None:
                            emergency = set_duties(ec, [emergency_duty, emergency_duty])
                            STATE.write_text(json.dumps({"requested_percent": [emergency_duty, emergency_duty], "time": time.time()}))
                            print(json.dumps(emergency), flush=True)
                            print(f"Emergency cooling: both fans forced to {emergency_duty}%; firmware control was kept disabled.", flush=True)
                            emergency_handled = True
                        else:
                            restore(ec)
                    elif "temperatures are implausible" in str(exc):
                        print("Temperature sensor failure: keeping the last accepted manual duty; firmware control was not requested.", file=sys.stderr, flush=True)
                    else:
                        restore(ec)
                except Exception as restore_error:
                    print(f"RECOVERY FAILED: {restore_error}; fans may remain at their last accepted duty.", file=sys.stderr, flush=True)
            if emergency_handled:
                return
            raise
        finally:
            ec.close()


def interrupted(signum, frame):
    raise KeyboardInterrupt(f"signal {signum}")


if __name__ == "__main__":
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, interrupted)
    try:
        main()
    except (Exception, KeyboardInterrupt) as exc:
        print(f"gfan: {exc}", file=sys.stderr, flush=True)
        sys.exit(1)
