"""Focused tests for hardware-control failure and recovery boundaries."""
import importlib.util
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location("gfan", Path(__file__).with_name("gfan.py"))
gfan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gfan)


class FakeEC:
    def __init__(self, echo=True, fail_fan=None, rise_on_fan=None, rise_to=85):
        self.regs = {7: 45, 10: 38, 0xCE: 71, 0xCF: 71}
        self.calls = []
        self.echo = echo
        self.fail_fan = fail_fan
        self.rise_on_fan = rise_on_fan
        self.rise_to = rise_to
    def read(self, offset): return self.regs.get(offset, 0)
    def command(self, fan, value):
        self.calls.append((fan, value))
        if fan == self.fail_fan:
            raise OSError("write failed")
        if self.echo and fan in (1,2): self.regs[0xCD+fan] = value
        if fan == self.rise_on_fan:
            self.regs[7] = self.rise_to


def test_verify_success(monkeypatch):
    monkeypatch.setattr(gfan.glob, "glob", lambda _: [])
    ec = FakeEC()
    assert gfan.set_duties(ec, [60, 70])["duty_raw"] == [153,178]


def test_silent_refusal_is_failure(monkeypatch):
    monkeypatch.setattr(gfan.glob, "glob", lambda _: [])
    with pytest.raises(RuntimeError, match="readback"):
        gfan.set_duties(FakeEC(echo=False), [60,60], timeout=0)


@pytest.mark.parametrize("cpu,gpu,targets", [(95,40,[99,100]),(40,95,[100,99]),(85,40,[30,100]),(40,85,[100,30]),(0,40,[60,60]),(40,255,[60,60])])
def test_temperature_guard(monkeypatch, cpu, gpu, targets):
    monkeypatch.setattr(gfan.glob, "glob", lambda _: [])
    with pytest.raises(RuntimeError):
        gfan.guard({"cpu_c":cpu,"gpu_c":gpu},targets)


@pytest.mark.parametrize("cpu,gpu", [(95,40),(40,95),(105,105)])
def test_full_duty_is_allowed_as_emergency_cooling(monkeypatch, cpu, gpu):
    monkeypatch.setattr(gfan.glob, "glob", lambda _: [])
    gfan.guard({"cpu_c":cpu,"gpu_c":gpu},[100,100])


def test_guard_uses_hot_core_temperature_when_available(monkeypatch):
    monkeypatch.setattr(gfan.glob, "glob", lambda _: [])
    with pytest.raises(RuntimeError, match="90 C"):
        gfan.guard({"cpu_c":70,"gpu_c":40,"cpu_core_c":90},[60,60])


@pytest.mark.parametrize("temperature,duty", [(84, None),(85,80),(94,80),(95,100),(110,100)])
def test_hot_guard_recovery_duty(temperature, duty):
    assert gfan.hot_guard_recovery_duty(temperature) == duty


def test_status_read_does_not_wait_for_exclusive_writer_lock(monkeypatch, capsys):
    ec = FakeEC()
    monkeypatch.setattr(gfan.os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setattr(gfan, "check_model", lambda: None)
    monkeypatch.setattr(gfan, "check_writers", lambda: None)
    monkeypatch.setattr(gfan, "ensure_device", lambda: None)
    monkeypatch.setattr(gfan, "lock_ec", lambda: (_ for _ in ()).throw(AssertionError("status waited for writer lock")))
    monkeypatch.setattr(gfan, "EC", lambda **kw: ec)
    monkeypatch.setattr(ec, "close", lambda: None, raising=False)
    monkeypatch.setattr(gfan.sys, "argv", ["gfan", "status"])
    gfan.main()
    assert '"cpu_c": 45' in capsys.readouterr().out


def test_auto_attempts_both_fans_even_if_first_fails(monkeypatch):
    ec = FakeEC(fail_fan=0xFF)
    with pytest.raises(RuntimeError, match="fan 1.*fan 2"):
        gfan.restore(ec)
    assert ec.calls == [(0xFF,1),(0xFF,2)]


def test_invalid_percentage():
    for p in ("0","29","101"):
        with pytest.raises(gfan.argparse.ArgumentTypeError): gfan.percent(p)


def test_partial_set_failure_restores_both(monkeypatch, tmp_path):
    ec = FakeEC(fail_fan=2)
    monkeypatch.setattr(gfan.os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setattr(gfan, "check_model", lambda: None)
    monkeypatch.setattr(gfan, "check_writers", lambda: None)
    monkeypatch.setattr(gfan, "ensure_device", lambda: None)
    monkeypatch.setattr(gfan, "lock_ec", gfan.contextlib.nullcontext)
    monkeypatch.setattr(gfan, "EC", lambda **kw: ec)
    monkeypatch.setattr(ec, "close", lambda: None, raising=False)
    monkeypatch.setattr(gfan.glob, "glob", lambda _: [])
    monkeypatch.setattr(gfan, "STATE", tmp_path/"state.json")
    monkeypatch.setattr(gfan.sys, "argv", ["gfan","60"])
    with pytest.raises(OSError): gfan.main()
    assert ec.calls[-2:] == [(0xFF,1),(0xFF,2)]


def test_hot_temperature_during_write_forces_safety_duty_without_firmware_auto(monkeypatch, tmp_path, capsys):
    ec = FakeEC(rise_on_fan=1, rise_to=85)
    monkeypatch.setattr(gfan.os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setattr(gfan, "check_model", lambda: None)
    monkeypatch.setattr(gfan, "check_writers", lambda: None)
    monkeypatch.setattr(gfan, "ensure_device", lambda: None)
    monkeypatch.setattr(gfan, "lock_ec", gfan.contextlib.nullcontext)
    monkeypatch.setattr(gfan, "EC", lambda **kw: ec)
    monkeypatch.setattr(ec, "close", lambda: None, raising=False)
    monkeypatch.setattr(gfan.glob, "glob", lambda _: [])
    monkeypatch.setattr(gfan, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(gfan.sys, "argv", ["gfan", "60"])

    gfan.main()

    assert ec.calls == [(1, 153), (2, 153), (1, 204), (2, 204)]
    assert gfan.json.loads((tmp_path / "state.json").read_text())["requested_percent"] == [80, 80]
    assert "Emergency cooling" in capsys.readouterr().out
