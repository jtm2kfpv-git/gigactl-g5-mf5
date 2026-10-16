"""Temperature curve for the G5 MF5 manual fan controller."""

CURVE = ((50, 55), (60, 65), (70, 80), (80, 100))
HYSTERESIS_C = 5
CONFIRM_SAMPLES = 2


def temperature_target(temperature):
    """Return the curve duty for one valid temperature in degrees Celsius."""
    if isinstance(temperature, bool) or not isinstance(temperature, (int, float)):
        raise ValueError("Temperature is not numeric.")
    if not 1 <= temperature <= 110:
        raise ValueError(f"Temperature reading is implausible: {temperature!r} °C.")
    target = 40
    for threshold, duty in CURVE:
        if temperature >= threshold:
            target = duty
    return target


def hottest_temperature(cpu_c, gpu_c, cpu_core_c=None):
    """Validate EC temperatures and optional maximum CPU core reading."""
    temperature_target(cpu_c)
    temperature_target(gpu_c)
    temperatures = [cpu_c, gpu_c]
    if cpu_core_c is not None:
        temperature_target(cpu_core_c)
        temperatures.append(cpu_core_c)
    return max(temperatures)


class AutoCurve:
    """Step curve with two-sample confirmation and 5 °C down hysteresis."""

    def __init__(self):
        self.current = None
        self.candidate = None
        self.candidate_samples = 0

    def start(self, cpu_c, gpu_c, cpu_core_c=None):
        hottest = hottest_temperature(cpu_c, gpu_c, cpu_core_c)
        self.current = temperature_target(hottest)
        self.candidate = None
        self.candidate_samples = 0
        return self.current

    def update(self, cpu_c, gpu_c, cpu_core_c=None):
        if self.current is None:
            raise RuntimeError("Auto Curve has not been started.")
        hottest = hottest_temperature(cpu_c, gpu_c, cpu_core_c)
        desired = temperature_target(hottest)
        duties = [40, 55, 65, 80, 100]
        current_index = duties.index(self.current)
        desired_index = duties.index(desired)

        if desired_index > current_index:
            next_target = desired
        elif desired_index < current_index:
            threshold = next(t for t, duty in CURVE if duty == self.current)
            next_target = duties[current_index - 1] if hottest < threshold - HYSTERESIS_C else self.current
        else:
            next_target = self.current

        if next_target == self.current:
            self.candidate = None
            self.candidate_samples = 0
            return None

        if self.candidate != next_target:
            self.candidate = next_target
            self.candidate_samples = 1
            return None

        self.candidate_samples += 1
        if self.candidate_samples < CONFIRM_SAMPLES:
            return None

        self.current = next_target
        self.candidate = None
        self.candidate_samples = 0
        return self.current
