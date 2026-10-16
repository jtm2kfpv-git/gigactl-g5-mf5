"""Read CPU and GPU utilization without adding a GUI runtime dependency."""
from __future__ import annotations

import glob
from pathlib import Path
import subprocess
import shutil


def parse_cpu_times(line: str) -> tuple[int, int]:
    """Return aggregate CPU total and idle ticks from a /proc/stat cpu line."""
    fields = line.split()
    if not fields or fields[0] != "cpu" or len(fields) < 5:
        raise ValueError("Expected the aggregate cpu line from /proc/stat.")
    try:
        ticks = [int(value) for value in fields[1:]]
    except ValueError as exc:
        raise ValueError("CPU tick values must be integers.") from exc
    idle = ticks[3] + (ticks[4] if len(ticks) > 4 else 0)
    # guest/guest_nice are already included in user/nice by the kernel.
    return sum(ticks[:8]), idle


def cpu_percent(previous: tuple[int, int] | None,
                current: tuple[int, int]) -> int | None:
    """Compute busy percentage between two aggregate /proc/stat readings."""
    if previous is None:
        return None
    total_delta = current[0] - previous[0]
    idle_delta = current[1] - previous[1]
    if total_delta <= 0 or idle_delta < 0 or idle_delta > total_delta:
        return None
    return round(100 * (total_delta - idle_delta) / total_delta)


class CpuLoadReader:
    def __init__(self, path="/proc/stat"):
        self.path = path
        self.previous = None

    def sample(self) -> int | None:
        try:
            with open(self.path, encoding="ascii") as source:
                current = parse_cpu_times(source.readline())
        except (OSError, ValueError):
            self.previous = None
            return None
        value = cpu_percent(self.previous, current)
        self.previous = current
        return value


def parse_gpu_percent(output: str) -> int | None:
    values = []
    for line in output.splitlines():
        try:
            value = int(line.strip().removesuffix("%"))
        except ValueError:
            continue
        if 0 <= value <= 100:
            values.append(value)
    return max(values, default=None)


def gpu_percent() -> int | None:
    """Query NVIDIA first, then use a DRM busy counter when one is exposed."""
    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi:
        try:
            result = subprocess.run(
                [nvidia_smi, "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=2, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            result = None
        if result is not None and result.returncode == 0:
            value = parse_gpu_percent(result.stdout)
            if value is not None:
                return value

    for path in glob.glob("/sys/class/drm/card*/device/gpu_busy_percent"):
        try:
            value = int(Path(path).read_text(encoding="ascii").strip())
        except (OSError, ValueError):
            continue
        if 0 <= value <= 100:
            return value
    return None
