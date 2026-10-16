#!/usr/bin/env bash
set -euo pipefail

duration="${1:-90}"
cooldown="${2:-45}"
outdir="${3:-./gfan-load-test}"
if [[ ! "$duration" =~ ^[0-9]+$ || "$duration" -lt 10 || "$duration" -gt 300 ]]; then
    echo "Duration must be 10..300 seconds." >&2
    exit 2
fi
if [[ ! "$cooldown" =~ ^[0-9]+$ || "$cooldown" -gt 300 ]]; then
    echo "Cooldown must be 0..300 seconds." >&2
    exit 2
fi

for command in sudo gfan stress-ng vkmark nvidia-smi python3; do
    command -v "$command" >/dev/null || { echo "Required command not found: $command" >&2; exit 2; }
done

uid="$(id -u)"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$uid}"
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}"
[[ -S "$XDG_RUNTIME_DIR/$WAYLAND_DISPLAY" ]] || {
    echo "Wayland socket not found; run this from the active desktop user's session." >&2
    exit 2
}

mkdir -p "$outdir"
csv="$outdir/readings.csv"
stress_log="$outdir/stress-ng.log"
vkmark_log="$outdir/vkmark.log"
summary="$outdir/run-info.txt"
: > "$stress_log"
: > "$vkmark_log"

sudo -v
sudo -n gfan status >/dev/null

nvidia_uuid="$(vkmark --list-devices 2>/dev/null | awk '/Vendor ID: *0x10DE/ { nvidia=1; next } nvidia && /Device UUID:/ && !found { print $3; found=1 }')"
vkmark_device=""
if [[ -n "$nvidia_uuid" ]]; then
    vkmark_device="--use-device $nvidia_uuid"
fi

cat > "$csv" <<'CSV'
timestamp,phase,ec_cpu_c,ec_gpu_c,cpu_core_max_c,fan1_duty_raw,fan2_duty_raw,fan1_rpm,fan2_rpm,nvidia_temp_c,nvidia_util_pct,mem_available_mb
CSV

cat > "$summary" <<EOF
Test duration: ${duration}s
Cooldown sampling: ${cooldown}s
Stress-ng: --cpu 0 --cpu-load 100 --vm 2 --vm-bytes 35% --timeout ${duration}s --metrics-brief
vkmark: Wayland window 800x600, looping for up to ${duration}s
Dedicated NVIDIA device selected: $([[ -n "$nvidia_uuid" ]] && echo yes || echo no;)
Telemetry: one-second sampling target via read-only 'sudo gfan status'; synchronous sensor commands can add interval drift under load
Fan control: Auto Curve was visibly enabled before the run; this script does not alter fan settings
Safety stop: 90 C, a curve response shortfall persisting 8 samples, or less than 1 GiB available memory
EOF

sample() {
    local phase="$1" stamp status fields cpu gpu duty1 duty2 rpm1 rpm2 coremax nvidia gpuutil memavail
    stamp="$(date --iso-8601=seconds)"
    status="$(sudo -n gfan status 2>/dev/null | sed -n '1p')" || return 1
    fields="$(python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["cpu_c"], d["gpu_c"], *d["duty_raw"], *d["rpm"])' <<< "$status")"
    read -r cpu gpu duty1 duty2 rpm1 rpm2 <<< "$fields"

    coremax=""
    for hwmon in /sys/class/hwmon/hwmon*; do
        if [[ -r "$hwmon/name" && "$(<"$hwmon/name")" == coretemp ]]; then
            coremax="$(awk 'BEGIN { m=0 } { if ($1+0 > m) m=$1+0 } END { if (m) printf "%.1f", m/1000 }' "$hwmon"/temp*_input)"
        fi
    done
    coremax="${coremax:-$cpu}"
    IFS=, read -r nvidia gpuutil < <(nvidia-smi --query-gpu=temperature.gpu,utilization.gpu --format=csv,noheader,nounits)
    nvidia="${nvidia// /}"
    gpuutil="${gpuutil//[^0-9]/}"
    memavail="$(awk '/^MemAvailable:/ { printf "%.0f", $2/1024 }' /proc/meminfo)"
    printf '%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n' \
        "$stamp" "$phase" "$cpu" "$gpu" "$coremax" "$duty1" "$duty2" \
        "$rpm1" "$rpm2" "$nvidia" "$gpuutil" "$memavail" >> "$csv"
    printf '%s %s: CPU %s C, GPU %s C, core max %s C, duty %s/%s, RPM %s/%s, GPU %s C @ %s%%, mem avail %s MiB\n' \
        "$stamp" "$phase" "$cpu" "$gpu" "$coremax" "$duty1" "$duty2" "$rpm1" "$rpm2" "$nvidia" "$gpuutil" "$memavail"
}

stress_pid=""
vkmark_pid=""
cleanup() {
    [[ -z "$stress_pid" ]] || kill -INT "$stress_pid" 2>/dev/null || true
    [[ -z "$vkmark_pid" ]] || kill -INT "$vkmark_pid" 2>/dev/null || true
    [[ -z "$stress_pid" ]] || wait "$stress_pid" 2>/dev/null || true
    [[ -z "$vkmark_pid" ]] || wait "$vkmark_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "Starting ${duration}s combined test; output: $outdir"
for _ in $(seq 1 5); do sample baseline; sleep 1; done

stress-ng --cpu 0 --cpu-load 100 --vm 2 --vm-bytes 35% --timeout "${duration}s" --metrics-brief > "$stress_log" 2>&1 &
stress_pid=$!
vkmark_args=(--winsys wayland --size 800x600 --run-forever)
[[ -z "$nvidia_uuid" ]] || vkmark_args+=(--use-device "$nvidia_uuid")
vkmark "${vkmark_args[@]}" > "$vkmark_log" 2>&1 &
vkmark_pid=$!

expected_duty() {
    awk -v t="$1" 'BEGIN { if (t>=80) print 255; else if (t>=70) print 204; else if (t>=60) print 166; else if (t>=50) print 140; else print 102 }'
}
shortfalls=0
test_result="completed"
for _ in $(seq 1 "$duration"); do
    sleep 1
    sample stress-ng+vkmark || { test_result="telemetry-error"; break; }
    line="$(tail -n 1 "$csv")"
    IFS=, read -r _ _ ec_cpu ec_gpu core_max duty1 duty2 _ _ _ _ available <<< "$line"
    hottest="$(awk -v a="$ec_cpu" -v b="$ec_gpu" -v c="$core_max" 'BEGIN { print (a>b ? (a>c?a:c) : (b>c?b:c)) }')"
    if awk -v t="$hottest" 'BEGIN { exit !(t>=90) }'; then
        test_result="thermal-limit-90C"
        break
    fi
    if [[ "$available" -lt 1024 ]]; then
        test_result="memory-limit-1GiB"
        break
    fi
    required="$(expected_duty "$hottest")"
    if [[ "$duty1" -lt "$required" || "$duty2" -lt "$required" ]]; then
        shortfalls=$((shortfalls + 1))
    else
        shortfalls=0
    fi
    if [[ "$shortfalls" -ge 8 ]]; then
        test_result="curve-response-shortfall"
        break
    fi
done

cleanup
stress_pid=""
vkmark_pid=""
echo "Test phase ended: $test_result"
for _ in $(seq 1 "$cooldown"); do sample cooldown; sleep 1; done
printf '\nResult: %s\n' "$test_result" >> "$summary"
printf 'Samples: %s\n' "$(($(wc -l < "$csv") - 1))" >> "$summary"
echo "Result: $test_result; samples: $(($(wc -l < "$csv") - 1)); files: $outdir"
