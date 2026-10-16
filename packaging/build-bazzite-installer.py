#!/usr/bin/env python3
"""Build a deterministic, self-contained Bazzite G5 MF5 installer archive."""
from __future__ import annotations

import argparse
import gzip
import io
from pathlib import Path
import re
import tarfile

ROOT = Path(__file__).resolve().parents[1]
FILES = [
    Path("LICENSE"),
    Path("bazzite-g5-mf5/install-bazzite.sh"),
    Path("bazzite-g5-mf5/README.md"),
    Path("bazzite-g5-mf5/README-GUI.md"),
    Path("bazzite-g5-mf5/HARDWARE-VALIDATION.md"),
    Path("bazzite-g5-mf5/gfan.py"),
    Path("bazzite-g5-mf5/gfan_ui.py"),
    Path("bazzite-g5-mf5/gfan_curve.py"),
    Path("bazzite-g5-mf5/gfan_load.py"),
    Path("bazzite-g5-mf5/gfan_ui_helper.py"),
    Path("bazzite-g5-mf5/gfan-control.desktop"),
    Path("bazzite-g5-mf5/50-gfan-control.rules.in"),
    Path("bazzite-g5-mf5/gfan.8"),
    Path("bazzite-g5-mf5/gfan-manual.txt"),
    Path("bazzite-g5-mf5/acpi_ec/UPSTREAM.md"),
    Path("bazzite-g5-mf5/acpi_ec/LICENSE"),
    Path("bazzite-g5-mf5/acpi_ec/Makefile"),
    Path("bazzite-g5-mf5/acpi_ec/src/Makefile"),
    Path("bazzite-g5-mf5/acpi_ec/src/acpi_ec.c"),
    Path("bazzite-g5-mf5/validation-2026-10-16/README.md"),
    Path("bazzite-g5-mf5/validation-2026-10-16/auto-curve-before-test.png"),
    Path("bazzite-g5-mf5/validation-2026-10-16/auto-curve-after-test.png"),
    Path("bazzite-g5-mf5/validation-2026-10-16/temperatures-and-fan.svg"),
    Path("bazzite-g5-mf5/validation-2026-10-16/readings.csv"),
    Path("bazzite-g5-mf5/validation-2026-10-16/benchmark-results.txt"),
    Path("bazzite-g5-mf5/validation-2026-10-16/run-info.txt"),
    Path("bazzite-g5-mf5/validation-2026-10-16/capture-load-test.sh"),
    Path("bazzite-g5-mf5/validation-2026-10-16/plot_readings.py"),
]


def archive_path(path: Path) -> Path:
    """Put the Bazzite subproject at the archive root for a one-folder install."""
    if path == Path("LICENSE"):
        return path
    return path.relative_to("bazzite-g5-mf5")


def build(version: str, output: Path) -> Path:
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise ValueError("version must use MAJOR.MINOR.PATCH")
    missing = [str(path) for path in FILES if not (ROOT / path).is_file()]
    if missing:
        raise FileNotFoundError("missing package files: " + ", ".join(missing))

    output.parent.mkdir(parents=True, exist_ok=True)
    top = f"gfan-bazzite-g5-mf5-{version}"
    with output.open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
            packaged = [(path, archive_path(path)) for path in FILES]
            dirs = {Path(".")}
            for _source_path, packaged_path in packaged:
                dirs.update(packaged_path.parents)
            for directory in sorted(dirs, key=lambda p: (len(p.parts), str(p))):
                if str(directory) == ".":
                    continue
                entry = tarfile.TarInfo(f"{top}/{directory.as_posix()}/")
                entry.type = tarfile.DIRTYPE
                entry.mode = 0o755
                entry.uid = entry.gid = entry.mtime = 0
                entry.uname = entry.gname = ""
                archive.addfile(entry)
            for path, packaged_path in packaged:
                source = ROOT / path
                contents = source.read_bytes()
                if source.suffix.lower() != ".png":
                    contents = contents.replace(b"\r\n", b"\n")
                entry = tarfile.TarInfo(f"{top}/{packaged_path.as_posix()}")
                entry.size = len(contents)
                entry.mode = 0o755 if packaged_path.name == "install-bazzite.sh" else 0o644
                entry.uid = entry.gid = entry.mtime = 0
                entry.uname = entry.gname = ""
                archive.addfile(entry, io.BytesIO(contents))
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default="0.2.0")
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    destination = args.output
    if destination.is_dir() or not destination.suffix:
        destination = destination / f"gfan-bazzite-g5-mf5-{args.version}.tar.gz"
    print(build(args.version, destination))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
