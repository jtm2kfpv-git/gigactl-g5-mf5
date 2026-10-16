#!/usr/bin/python3
"""Small dark GTK fan dashboard for the GIGABYTE G5 MF5."""
import json
import queue
import subprocess
import threading

import gi
from gfan_curve import AutoCurve
from gfan_load import CpuLoadReader, gpu_percent
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk

APP_ID = "local.bazzite.GFanControl"
HELPER = "/usr/local/libexec/gfan-ui-helper"

CSS = """
window { background: #111318; color: #e7e9ee; }
.page { background: #111318; }
.card { background: #1a1d24; border: 1px solid #30343d; border-radius: 18px; padding: 20px; }
.muted { color: #a5aab5; }
.reading { font-size: 34px; font-weight: 700; }
.label { color: #a5aab5; font-size: 13px; }
.section-title { font-size: 18px; font-weight: 650; }
.fan-percent { font-size: 25px; font-weight: 650; }
.status-pill { background: #292d36; border-radius: 999px; padding: 6px 12px; }
.load-meter trough { border: 2px solid #25c66a; border-radius: 8px; background: #111814; }
.load-meter block { min-width: 14px; min-height: 7px; margin: 1px; border-radius: 5px; }
.load-meter block.filled { background: #25c66a; }
.load-meter block.empty { background: #242d27; }
.load-percent { color: #25c66a; font-size: 13px; font-weight: 650; }
button.suggested-action { background: #6c8cff; color: #10131a; }
scale trough { min-height: 8px; }
scale highlight { background: #7894ff; }
"""


class GfanBackend:
    """Serialized access to the root-owned gfan helper."""

    def __init__(self):
        self.process = subprocess.Popen(
            ["/usr/bin/pkexec", HELPER], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1,
        )
        self.requests = queue.Queue()
        self.results = queue.Queue()
        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()

    def request(self, command, percent=None):
        self.requests.put({"command": command, "percent": percent})

    def status(self):
        self.request("status")

    def set_manual(self, percent):
        self.request("set", percent)

    def firmware_auto(self):
        self.request("auto")

    def close(self):
        if self.process.stdin and not self.process.stdin.closed:
            self.process.stdin.close()

    def _worker(self):
        while True:
            request = self.requests.get()
            try:
                self.process.stdin.write(json.dumps(request) + "\n")
                self.process.stdin.flush()
                line = self.process.stdout.readline()
                if not line:
                    error = self.process.stderr.read().strip()
                    raise RuntimeError(error or "Polkit helper disconnected. Close and reopen GFan Control to reconnect.")
                self.results.put(json.loads(line))
            except Exception as exc:
                self.results.put({"ok": False, "error": str(exc)})


class FanTile(Gtk.Box):
    def __init__(self, title):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.add_css_class("card")
        self.append(Gtk.Label(label=title, xalign=0, css_classes=["section-title"]))
        self.percent = Gtk.Label(label="—", xalign=0, css_classes=["fan-percent"])
        self.append(self.percent)
        self.rpm = Gtk.Label(label="— RPM", xalign=0, css_classes=["muted"])
        self.append(self.rpm)
        self.bar = Gtk.LevelBar.new_for_interval(0, 100)
        self.bar.set_value(0)
        self.append(self.bar)

    def update(self, raw, rpm):
        percent = round(raw * 100 / 255)
        self.percent.set_text(f"{percent}% duty")
        self.rpm.set_text(f"{rpm:,} RPM" if rpm else "0 RPM · stopped")
        self.bar.set_value(percent)


class GfanWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="GFan Control", default_width=620, default_height=690)
        self.backend = GfanBackend()
        self.status_backend = GfanBackend()
        self.busy = False
        self.operation_pending = False
        self.last_snapshot = None
        self.last_manual_state = None
        self.curve = AutoCurve()
        self.curve_active = False
        self.curve_start_pending = True
        self.curve_duty = None
        self.pending_write = None
        self.cpu_load_reader = CpuLoadReader()
        self.gpu_load_stop = threading.Event()
        self._make_ui()
        self.curve_button.set_label("Stop Auto Curve")
        self.mode.set_text("Auto Curve · waiting for sensors")
        self.connect("close-request", self._close_request)
        self.timer = GLib.timeout_add(250, self._poll)
        self.gpu_load_thread = threading.Thread(target=self._gpu_load_loop, daemon=True)
        self.gpu_load_thread.start()
        self._poll()

    def _make_ui(self):
        titlebar = Adw.HeaderBar()
        titlebar.set_title_widget(Gtk.Label(label="GFan Control"))
        self.set_titlebar(titlebar)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        root.set_margin_top(22)
        root.set_margin_bottom(22)
        root.set_margin_start(24)
        root.set_margin_end(24)
        self.set_child(root)

        header = Gtk.Box(spacing=12, valign=Gtk.Align.CENTER)
        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3, hexpand=True)
        title_box.append(Gtk.Label(label="G5 MF5 · Fan Control", xalign=0, css_classes=["title-1"]))
        title_box.append(Gtk.Label(label="Live temperatures and fan readback", xalign=0, css_classes=["muted"]))
        header.append(title_box)
        self.mode = Gtk.Label(label="Connecting…", css_classes=["status-pill"])
        header.append(self.mode)
        root.append(header)

        temps = Gtk.Box(spacing=14)
        self.cpu_temp = self._temp_tile("CPU")
        self.gpu_temp = self._temp_tile("GPU")
        temps.append(self.cpu_temp[0])
        temps.append(self.gpu_temp[0])
        root.append(temps)

        root.append(Gtk.Label(label="Fan readback", xalign=0, css_classes=["section-title"]))
        fans = Gtk.Box(spacing=14)
        self.fan1 = FanTile("CPU Fan · EC Fan 1")
        self.fan2 = FanTile("GPU Fan · EC Fan 2")
        fans.append(self.fan1)
        fans.append(self.fan2)
        root.append(fans)

        control = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        control.add_css_class("card")
        control.append(Gtk.Label(label="Fan control", xalign=0, css_classes=["section-title"]))
        slider_row = Gtk.Box(spacing=12, valign=Gtk.Align.CENTER)
        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 30, 100, 1)
        self.scale.set_draw_value(False)
        self.scale.set_hexpand(True)
        self.scale.set_value(60)
        self.scale.connect("value-changed", self._slider_changed)
        slider_row.append(self.scale)
        self.scale_value = Gtk.Label(label="60%", width_chars=5, css_classes=["fan-percent"])
        slider_row.append(self.scale_value)
        control.append(slider_row)
        control.append(Gtk.Label(label="Auto Curve controls both fans from the hottest available CPU/GPU sensor. Firmware Auto returns control to the laptop and does not provide this Linux curve.", xalign=0, wrap=True, css_classes=["muted"]))
        buttons = Gtk.Box(spacing=10)
        self.apply_button = Gtk.Button(label="Apply to both fans", css_classes=["suggested-action"])
        self.apply_button.connect("clicked", self._apply)
        buttons.append(self.apply_button)
        self.curve_button = Gtk.Button(label="Enable Auto Curve", css_classes=["suggested-action"])
        self.curve_button.connect("clicked", self._toggle_curve)
        buttons.append(self.curve_button)
        self.auto_button = Gtk.Button(label="Firmware Auto")
        self.auto_button.connect("clicked", self._auto)
        buttons.append(self.auto_button)
        control.append(buttons)
        root.append(control)

        self.message = Gtk.Label(label="Waiting for sensor readback…", xalign=0, wrap=True, css_classes=["muted"])
        root.append(self.message)
        footer = Gtk.Label(label="Readout every 0.25 seconds · keep this window open while Auto Curve is enabled", xalign=0, wrap=True, css_classes=["label"])
        root.append(footer)

    def _temp_tile(self, title):
        card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12, hexpand=True)
        card.add_css_class("card")
        readings = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, hexpand=True)
        readings.append(Gtk.Label(label=title, xalign=0, css_classes=["section-title"]))
        value = Gtk.Label(label="— °C", xalign=0, css_classes=["reading"])
        readings.append(value)
        detail = Gtk.Label(label="Embedded controller", xalign=0, css_classes=["label"])
        readings.append(detail)
        card.append(readings)

        load_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, valign=Gtk.Align.CENTER)
        meter = Gtk.LevelBar.new_for_interval(0, 100)
        meter.set_orientation(Gtk.Orientation.VERTICAL)
        meter.set_inverted(True)
        meter.set_size_request(22, 64)
        meter.add_css_class("load-meter")
        meter.set_value(0)
        load_box.append(meter)
        load_value = Gtk.Label(label="—%", css_classes=["load-percent"])
        load_box.append(load_value)
        card.append(load_box)
        return card, value, detail, meter, load_value

    def _slider_changed(self, scale):
        value = round(scale.get_value())
        self.scale_value.set_text(f"{value}%")

    def _poll(self):
        self._drain_results()
        cpu_percent = self.cpu_load_reader.sample()
        self._set_load(self.cpu_temp, cpu_percent)
        if not self.busy:
            self.busy = True
            self.status_backend.status()
        return GLib.SOURCE_CONTINUE

    def _gpu_load_loop(self):
        while not self.gpu_load_stop.is_set():
            value = gpu_percent()
            GLib.idle_add(self._set_gpu_load, value)
            if self.gpu_load_stop.wait(1.0):
                return

    def _set_gpu_load(self, value):
        if not self.gpu_load_stop.is_set():
            self._set_load(self.gpu_temp, value)
        return GLib.SOURCE_REMOVE

    @staticmethod
    def _set_load(tile, value):
        tile[3].set_value(value if value is not None else 0)
        tile[4].set_text(f"{value}%" if value is not None else "N/A")

    def _drain_results(self):
        self._drain_status_results()
        self._drain_command_results()
        return GLib.SOURCE_CONTINUE

    def _drain_status_results(self):
        try:
            while True:
                result = self.status_backend.results.get_nowait()
                self.busy = False
                if not result.get("ok"):
                    if self.curve_active:
                        self.message.set_text("Temperature read failed; Auto Curve is holding the last verified duty and will retry.")
                    else:
                        self.message.set_text(result.get("error", "Temperature read failed"))
                    continue
                snapshot = result.get("snapshot")
                if snapshot:
                    self._update(snapshot, result.get("manual_state"))
                    if self.curve_start_pending:
                        self.curve_start_pending = False
                        self._start_curve()
                    elif self.curve_active:
                        self._curve_sample(snapshot)
        except queue.Empty:
            pass

    def _drain_command_results(self):
        try:
            while True:
                result = self.backend.results.get_nowait()
                if not result.get("ok"):
                    pending = self.pending_write
                    self.pending_write = None
                    self.operation_pending = False
                    if pending and pending.get("kind") == "curve":
                        self.curve_active = False
                        self.curve_button.set_label("Enable Auto Curve")
                        self.message.set_text("Auto Curve could not verify the fan command and stopped. Check temperatures and fan readback; a failed gfan write can return control to firmware.")
                    else:
                        self.message.set_text(result.get("error", "Fan backend failed"))
                    self.mode.set_text("Needs attention")
                    continue
                snapshot = result.get("snapshot")
                if snapshot:
                    self._update(snapshot, result.get("manual_state"))
                if result.get("command") == "set":
                    pending = self.pending_write
                    self.pending_write = None
                    self.operation_pending = False
                    if pending and pending["kind"] == "curve":
                        self.curve_duty = pending["percent"]
                        self.mode.set_text(f"Auto Curve · {self.curve_duty}%")
                        self.message.set_text(f"Auto Curve applied {self.curve_duty}% to both fans and verified the EC readback.")
                    else:
                        self.message.set_text(result.get("message") or "Manual duty applied and verified.")
                elif result.get("command") == "emergency":
                    pending = self.pending_write
                    self.pending_write = None
                    self.operation_pending = False
                    requested = (result.get("manual_state") or {}).get("requested_percent", [100, 100])
                    duty = requested[0] if requested and len(set(requested)) == 1 else 100
                    if pending and pending.get("kind") == "curve":
                        self.curve_duty = duty
                        self.curve.current = duty
                        self.curve.candidate = None
                        self.curve.candidate_samples = 0
                        self.mode.set_text(f"Auto Curve · {duty}%")
                        self.message.set_text(f"Temperature safety limit reached. Both fans were raised to {duty}%; Auto Curve remains active.")
                    else:
                        self.curve_active = False
                        self.curve_button.set_label("Enable Auto Curve")
                        self.mode.set_text(f"Safety override · {duty}%")
                        self.message.set_text(f"Temperature safety limit reached. Both fans were raised to {duty}%.")
                elif result.get("command") == "auto":
                    self.pending_write = None
                    self.message.set_text(result.get("message") or "Firmware Auto requested for both fans.")
                    self.operation_pending = False
        except queue.Empty:
            pass

    def _close_request(self, _window):
        GLib.source_remove(self.timer)
        self.gpu_load_stop.set()
        self.backend.close()
        self.status_backend.close()
        return False

    def _update(self, data, manual_state):
        self.last_snapshot = data
        self.last_manual_state = manual_state
        core_temp = data.get("cpu_core_c")
        cpu_display = max(data["cpu_c"], core_temp) if core_temp is not None else data["cpu_c"]
        self.cpu_temp[1].set_text(f"{cpu_display:g} °C")
        self.cpu_temp[2].set_text(f"EC {data['cpu_c']}° · core max {core_temp:g}°" if core_temp is not None else "Embedded controller")
        self.gpu_temp[1].set_text(f"{data['gpu_c']} °C")
        self.fan1.update(data["duty_raw"][0], data["rpm"][0])
        self.fan2.update(data["duty_raw"][1], data["rpm"][1])
        if self.curve_active:
            shown = self.curve_duty if self.curve_duty is not None else self.curve.current
            self.mode.set_text(f"Auto Curve · {shown}%" if shown is not None else "Auto Curve · starting")
        elif self.curve_start_pending:
            self.mode.set_text("Auto Curve · waiting for sensors")
        elif manual_state:
            value = manual_state.get("requested_percent", [])
            shown = value[0] if value and len(set(value)) == 1 else "custom"
            self.mode.set_text(f"Manual · {shown}%" if isinstance(shown, int) else "Manual · separate fans")
        else:
            self.mode.set_text("No manual request")

    def _apply(self, _button):
        if self.operation_pending:
            self.message.set_text("A fan change is already in progress. Wait for its readback.")
            return
        value = round(self.scale.get_value())
        self.curve_start_pending = False
        self.curve_active = False
        self.curve_button.set_label("Enable Auto Curve")
        self.curve_duty = None
        self.operation_pending = True
        self.message.set_text(f"Applying {value}% to both fans and waiting for readback…")
        self.pending_write = {"kind": "manual", "percent": value}
        self.backend.set_manual(value)

    def _toggle_curve(self, _button):
        if self.operation_pending:
            self.message.set_text("A fan change is already in progress. Wait for its readback.")
            return
        if self.curve_start_pending:
            self.curve_start_pending = False
            self.curve_button.set_label("Enable Auto Curve")
            self.mode.set_text("No manual request")
            self.message.set_text("Auto Curve startup cancelled. Enable it here whenever you want it to control the fans.")
            return
        if self.curve_active:
            self.curve_active = False
            self.curve_button.set_label("Enable Auto Curve")
            self.message.set_text("Auto Curve stopped. Fans remain at their last manual duty; Firmware Auto is separate.")
            return
        if not self.last_snapshot:
            self.message.set_text("Waiting for a valid temperature reading before starting Auto Curve.")
            return
        self._start_curve()

    def _start_curve(self):
        if self.operation_pending:
            self.message.set_text("A fan change is already in progress. Wait for its readback.")
            return
        if not self.last_snapshot:
            self.message.set_text("Waiting for a valid temperature reading before starting Auto Curve.")
            return
        try:
            self.curve_duty = self.curve.start(
                self.last_snapshot["cpu_c"], self.last_snapshot["gpu_c"],
                self.last_snapshot.get("cpu_core_c"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            self.curve_active = False
            self.curve_button.set_label("Enable Auto Curve")
            self.mode.set_text("Needs attention")
            self.message.set_text(f"Auto Curve could not start: {exc}")
            return
        self.curve_active = True
        self.curve_button.set_label("Stop Auto Curve")
        self.mode.set_text(f"Auto Curve · starting at {self.curve_duty}%")
        self.message.set_text(f"Auto Curve enabled from the hotter sensor. Setting both fans to {self.curve_duty}%…")
        self._queue_curve_duty(self.curve_duty)

    def _curve_sample(self, snapshot):
        if not self.curve_active or self.operation_pending:
            return
        try:
            target = self.curve.update(snapshot["cpu_c"], snapshot["gpu_c"], snapshot.get("cpu_core_c"))
        except (KeyError, TypeError, ValueError, RuntimeError) as exc:
            self.curve_active = False
            self.curve_button.set_label("Enable Auto Curve")
            self.message.set_text(f"Auto Curve paused because sensor data is invalid: {exc}. Fans stay at the last verified duty.")
            self.mode.set_text("Needs attention")
            return
        if target is not None:
            self._queue_curve_duty(target)

    def _queue_curve_duty(self, percent):
        self.operation_pending = True
        self.pending_write = {"kind": "curve", "percent": percent}
        self.message.set_text(f"Auto Curve setting both fans to {percent}% and verifying EC readback…")
        self.backend.set_manual(percent)

    def _auto(self, _button):
        if self.operation_pending:
            self.message.set_text("A fan change is already in progress. Wait for its readback.")
            return
        self.curve_start_pending = False
        self.curve_active = False
        self.curve_button.set_label("Enable Auto Curve")
        self.curve_duty = None
        self.pending_write = {"kind": "firmware-auto", "percent": None}
        self.operation_pending = True
        self.message.set_text("Returning both fans to firmware control…")
        self.backend.firmware_auto()


class GfanApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=0)
        self.connect("activate", self._activate)

    def _activate(self, app):
        manager = Adw.StyleManager.get_default()
        manager.set_color_scheme(Adw.ColorScheme.FORCE_DARK)
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS.encode())
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.window = GfanWindow(app)
        self.window.present()


if __name__ == "__main__":
    raise SystemExit(GfanApp().run(None))
