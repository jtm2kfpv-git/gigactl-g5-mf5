"""The Bazzite installer release is a complete, reproducible source archive."""
from pathlib import Path
import importlib.util
import os
import subprocess
import tarfile
import pytest

BUILDER_PATH = Path(__file__).with_name("build-bazzite-installer.py")
SPEC = importlib.util.spec_from_file_location("bazzite_installer_builder", BUILDER_PATH)
assert SPEC is not None and SPEC.loader is not None
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)
FILES, ROOT, build = BUILDER.FILES, BUILDER.ROOT, BUILDER.build
archive_path = BUILDER.archive_path


def test_installer_script_parses_as_bash():
    bash = "bash"
    if os.name == "nt":
        bash = str(Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git/bin/bash.exe")
        if not Path(bash).is_file():
            pytest.skip("Git Bash is needed to parse the Linux installer on Windows")
    result = subprocess.run(
        [bash, "-n", "bazzite-g5-mf5/install-bazzite.sh"],
        capture_output=True,
        text=True,
        check=False,
        cwd=ROOT,
    )
    assert result.returncode == 0, result.stderr


def test_release_archive_contains_every_installed_component(tmp_path: Path):
    first = build("0.1.0", tmp_path / "first.tar.gz")
    second = build("0.1.0", tmp_path / "second.tar.gz")
    assert first.read_bytes() == second.read_bytes()
    with tarfile.open(first, "r:gz") as archive:
        members = {member.name: member for member in archive.getmembers()}
        top = "gfan-bazzite-g5-mf5-0.1.0/"
        for path in FILES:
            member = members[top + archive_path(path).as_posix()]
            assert member.isfile(), path
            assert member.size > 0, path
            if path.suffix.lower() != ".png":
                contents = archive.extractfile(member).read()
                assert b"\r\n" not in contents, path
        installer = members[top + "install-bazzite.sh"]
        assert installer.mode & 0o111
        module_license = archive.extractfile(top + "acpi_ec/LICENSE")
        assert module_license is not None
        assert b"GNU GENERAL PUBLIC LICENSE" in module_license.read(128)
        assert top + "gfan_load.py" in members


def test_installer_does_not_apply_a_fan_setting():
    script = (ROOT / "bazzite-g5-mf5/install-bazzite.sh").read_text()
    assert '"$SYSTEM_BIN" status' in script
    assert '"$SYSTEM_BIN" auto' in script  # only the explicit uninstaller path
    assert '"$SYSTEM_BIN" "$percent"' not in script
    assert "rpm-ostree install kernel-devel-matched gcc make" in script
