# Hardware validation

Manual fan control was exercised on a GIGABYTE G5 MF5 running Bazzite.

- EC temperature, fan duty, and tachometer reads returned plausible values.
- A 60% trial and a persistent 60% manual setting drove both EC duty registers to 153/255; tachometer-derived readings rose to about 4,000 RPM per channel.
- The explicit firmware-auto command returned both channels to the observed idle pattern.
- The kernel-mediated `acpi_ec` path loaded successfully on the tested kernel.

The user subsequently reported exercising the current Auto Curve and 250 ms readout while running `vkmark` and `stress-ng` on the laptop. No temperature/duty log, polling timing, or detailed outcome was captured, so this records user-reported load testing rather than a quantified or independently observed thermal validation. The two EC channels' physical CPU/GPU fan assignment remains unverified. Reboot, suspend/resume, other laptop models, and updated kernels need separate testing.

These results are from one G5 MF5. They do not establish compatibility with all G5 variants or guarantee recovery from EC, kernel, or power failures.
