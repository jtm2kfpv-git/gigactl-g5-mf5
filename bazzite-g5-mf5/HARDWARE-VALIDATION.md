# Hardware validation

Manual fan control was exercised on a GIGABYTE G5 MF5 running Bazzite.

- EC temperature, fan duty, and tachometer reads returned plausible values.
- A 60% trial and a persistent 60% manual setting drove both EC duty registers to 153/255; tachometer-derived readings rose to about 4,000 RPM per channel.
- The explicit firmware-auto command returned both channels to the observed idle pattern.
- The kernel-mediated `acpi_ec` path loaded successfully on the tested kernel.

The current Auto Curve profile and hysteresis have software unit tests. The updated curve thresholds, sustained-load behavior, and 250 ms polling cadence have not yet been independently measured on hardware. The two EC channels' physical CPU/GPU fan assignment also remains unverified. Reboot, suspend/resume, other laptop models, and updated kernels need separate testing.

These results are from one G5 MF5. They do not establish compatibility with all G5 variants or guarantee recovery from EC, kernel, or power failures.
