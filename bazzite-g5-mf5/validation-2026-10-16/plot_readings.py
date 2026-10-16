#!/usr/bin/env python3
"""Render the captured GFan load-test CSV as a dependency-free SVG chart."""
import csv
from datetime import datetime
from html import escape
from pathlib import Path
import sys


source = Path(sys.argv[1] if len(sys.argv) > 1 else "readings.csv")
target = Path(sys.argv[2] if len(sys.argv) > 2 else "temperatures-and-fan.svg")
rows = list(csv.DictReader(source.open(newline="", encoding="utf-8")))
if len(rows) < 2:
    raise SystemExit("Need at least two telemetry samples.")

for row in rows:
    row["time"] = datetime.fromisoformat(row["timestamp"])
    for key in (
        "ec_cpu_c", "ec_gpu_c", "cpu_core_max_c", "fan1_duty_raw",
        "fan2_duty_raw", "fan1_rpm", "fan2_rpm", "nvidia_temp_c",
        "nvidia_util_pct", "mem_available_mb",
    ):
        row[key] = float(row[key])

start = rows[0]["time"]
for row in rows:
    row["seconds"] = (row["time"] - start).total_seconds()

width, height = 1100, 570
left, right, top, bottom = 88, 1005, 60, 465
plot_w, plot_h = right - left, bottom - top
xmax = max(row["seconds"] for row in rows)
temp_min, temp_max = 30, 95


def x(value):
    return left + value / xmax * plot_w


def yt(value):
    return bottom - (value - temp_min) / (temp_max - temp_min) * plot_h


def yduty(raw):
    return bottom - (raw / 255) * plot_h


def line(key, y_fn):
    points = " ".join(f"{x(r['seconds']):.1f},{y_fn(r[key]):.1f}" for r in rows)
    return points


def text(xpos, ypos, value, size=13, fill="#d8dee9", anchor="start", weight="400"):
    return (f'<text x="{xpos}" y="{ypos}" font-family="Inter,Segoe UI,sans-serif" '
            f'font-size="{size}" fill="{fill}" text-anchor="{anchor}" font-weight="{weight}">'
            f"{escape(str(value))}</text>")


parts = [
    f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
    '<rect width="100%" height="100%" rx="16" fill="#11151b"/>',
    text(34, 31, "G5 MF5 · Auto Curve load test", 20, "#f0f3f8", weight="700"),
    text(34, 51, "stress-ng + vkmark · telemetry from EC readback and hwmon", 12, "#a8b2c2"),
]

stages = {
    "baseline": ("#303844", "Idle baseline"),
    "stress-ng+vkmark": ("#3b2b2c", "Combined load"),
    "cooldown": ("#20343a", "Cooldown"),
}
for phase, (color, label) in stages.items():
    members = [r for r in rows if r["phase"] == phase]
    if members:
        x1, x2 = x(members[0]["seconds"]), x(members[-1]["seconds"])
        parts.append(f'<rect x="{x1:.1f}" y="{top}" width="{max(1, x2-x1):.1f}" height="{plot_h}" fill="{color}" opacity="0.42"/>')
        parts.append(text((x1+x2)/2, top+16, label, 11, "#c5ccd8", anchor="middle"))

for value in range(30, 100, 10):
    ypos = yt(value)
    parts.append(f'<line x1="{left}" y1="{ypos:.1f}" x2="{right}" y2="{ypos:.1f}" stroke="#333b47" stroke-width="1"/>')
    parts.append(text(left-12, ypos+4, value, 11, "#a8b2c2", anchor="end"))

for value in range(0, 101, 20):
    ypos = bottom - value / 100 * plot_h
    parts.append(text(right+12, ypos+4, value, 11, "#a8b2c2"))

tick = 0
while tick <= xmax:
    xpos = x(tick)
    parts.append(f'<line x1="{xpos:.1f}" y1="{top}" x2="{xpos:.1f}" y2="{bottom}" stroke="#29313b" stroke-width="1"/>')
    parts.append(text(xpos, bottom+24, f"{int(tick)} s", 11, "#a8b2c2", anchor="middle"))
    tick += 15 if xmax < 90 else 20

cutoff_y = yt(90)
parts.append(f'<line x1="{left}" y1="{cutoff_y:.1f}" x2="{right}" y2="{cutoff_y:.1f}" stroke="#ff6b6b" stroke-width="1.5" stroke-dasharray="7 5"/>')
parts.append(text(right-6, cutoff_y-6, "90°C safety stop", 11, "#ff8a8a", anchor="end"))

series = [
    ("ec_cpu_c", yt, "#ff785a", "CPU · EC"),
    ("cpu_core_max_c", yt, "#ffb454", "CPU · core max"),
    ("ec_gpu_c", yt, "#55c8ff", "GPU · EC"),
    ("nvidia_temp_c", yt, "#b695ff", "NVIDIA GPU"),
    ("fan1_duty_raw", yduty, "#f5d76e", "Fan duty"),
]
for key, y_fn, color, _label in series:
    parts.append(f'<polyline points="{line(key, y_fn)}" fill="none" stroke="{color}" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>')

parts.append(f'<rect x="{left}" y="{top}" width="{plot_w}" height="{plot_h}" fill="none" stroke="#6b7481" stroke-width="1"/>')
parts.append(text(left, top-7, "Temperature (°C)", 11, "#d8dee9"))
parts.append(text(right, top-7, "Fan duty (%)", 11, "#d8dee9", anchor="end"))

legend_x, legend_y = 120, 525
for index, (_key, _y_fn, color, label) in enumerate(series):
    lx = legend_x + index * 184
    parts.append(f'<line x1="{lx}" y1="{legend_y-4}" x2="{lx+24}" y2="{legend_y-4}" stroke="{color}" stroke-width="3"/>')
    parts.append(text(lx+31, legend_y, label, 11, "#d8dee9"))

parts.append(text(34, 555, "Duty channels matched throughout the captured load; fan RPM is tachometer-derived.", 11, "#a8b2c2"))
parts.append("</svg>")
target.write_text("\n".join(parts), encoding="utf-8")
print(f"Wrote {target} from {len(rows)} samples over {xmax:.0f} seconds.")
