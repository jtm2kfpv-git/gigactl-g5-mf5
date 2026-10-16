# Hardware validation

Manual fan control was exercised on a GIGABYTE G5 MF5 running Bazzite.

- EC temperature, fan duty, and tachometer reads returned plausible values.
- A 60% trial and a persistent 60% manual setting drove both EC duty registers to 153/255; tachometer-derived readings rose to about 4,000 RPM per channel.
- The explicit firmware-auto command returned both channels to the observed idle pattern.
- The kernel-mediated `acpi_ec` path loaded successfully on the tested kernel.

On 2026-10-16, a supervised combined `stress-ng` and NVIDIA `vkmark` run captured 91 timestamped readings with Auto Curve enabled. Both fans advanced from 40% to 65%, 80%, and 100% as CPU temperature crossed the configured steps. The capture guard stopped the load at 90°C after about 54 seconds, with both fans already at 100%; during cooldown, CPU temperature fell to 49°C and duty returned to 55%. The detailed report includes raw readings, benchmark results, screenshots, and the capture script: [2026-10-16 Auto Curve load test](validation-2026-10-16/README.md).

This single transient test does not establish thermal equilibrium. The two EC channels' physical CPU/GPU fan assignment remains unverified. Reboot, suspend/resume, other laptop models, and updated kernels need separate testing.

These results are from one G5 MF5. They do not establish compatibility with all G5 variants or guarantee recovery from EC, kernel, or power failures.
