#!/usr/bin/python3
"""Narrow privileged bridge for the unprivileged GTK front end."""
import json
import os
from pathlib import Path
import subprocess
import sys

GFAN = "/usr/local/bin/gfan"
STATE = Path("/run/gfan-manual.json")


def read_request(line):
    request = json.loads(line)
    command = request.get("command")
    if command == "status":
        argv = [GFAN, "status"]
    elif command == "auto":
        argv = [GFAN, "auto"]
    elif command == "set":
        value = request.get("percent")
        if isinstance(value, bool) or not isinstance(value, int) or not 30 <= value <= 100:
            raise ValueError("Fan setting must be a whole number from 30 to 100.")
        argv = [GFAN, str(value)]
    else:
        raise ValueError("Unknown fan command.")

    result = subprocess.run(argv, text=True, capture_output=True, check=False)
    if result.returncode:
        message = result.stderr.strip() or result.stdout.strip() or f"gfan exited {result.returncode}"
        raise RuntimeError(message)

    snapshots = []
    messages = []
    for line in result.stdout.splitlines():
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            if line.strip():
                messages.append(line.strip())
        else:
            if isinstance(parsed, dict) and {"cpu_c", "gpu_c", "duty_raw", "rpm"} <= parsed.keys():
                snapshots.append(parsed)

    message = " ".join(messages)
    response = {
        "ok": True,
        "command": "emergency" if "Emergency cooling:" in message else command,
        "message": message,
    }
    if snapshots:
        response["snapshot"] = snapshots[-1]
    if STATE.is_file():
        try:
            response["manual_state"] = json.loads(STATE.read_text())
        except (OSError, json.JSONDecodeError):
            response["manual_state"] = None
    else:
        response["manual_state"] = None
    return response


def main():
    if os.geteuid() != 0:
        print("This helper must be started by polkit.", file=sys.stderr)
        return 1
    for line in sys.stdin:
        try:
            response = read_request(line)
        except Exception as exc:
            response = {"ok": False, "error": str(exc)}
        print(json.dumps(response), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
