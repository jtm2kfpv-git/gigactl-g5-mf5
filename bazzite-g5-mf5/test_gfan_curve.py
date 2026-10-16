import unittest

from gfan_curve import AutoCurve, temperature_target


class TemperatureTargetTests(unittest.TestCase):
    def test_curve_thresholds(self):
        cases = {
            1: 40, 49: 40, 50: 55, 59: 55, 60: 65,
            69: 65, 70: 80, 79: 80, 80: 100, 110: 100,
        }
        for temperature, expected in cases.items():
            with self.subTest(temperature=temperature):
                self.assertEqual(temperature_target(temperature), expected)

    def test_rejects_invalid_readings(self):
        for temperature in (0, 111, -1, None, "60", True):
            with self.subTest(temperature=temperature):
                with self.assertRaises(ValueError):
                    temperature_target(temperature)


class AutoCurveTests(unittest.TestCase):
    def test_uses_the_hotter_component_and_starts_at_baseline(self):
        curve = AutoCurve()
        self.assertEqual(curve.start(35, 42), 40)
        self.assertIsNone(curve.update(55, 62))
        self.assertEqual(curve.update(55, 62), 65)

    def test_upward_change_requires_two_samples(self):
        curve = AutoCurve()
        curve.start(50, 50)
        self.assertIsNone(curve.update(72, 40))
        self.assertEqual(curve.update(73, 40), 80)

    def test_downward_change_uses_five_degree_hysteresis_and_two_samples(self):
        curve = AutoCurve()
        curve.start(82, 40)
        self.assertIsNone(curve.update(75, 40))
        self.assertIsNone(curve.update(74, 40))
        self.assertEqual(curve.update(74, 40), 80)

    def test_cools_down_one_step_at_a_time(self):
        curve = AutoCurve()
        curve.start(90, 40)
        self.assertIsNone(curve.update(74, 40))
        self.assertEqual(curve.update(74, 40), 80)
        self.assertIsNone(curve.update(64, 40))
        self.assertEqual(curve.update(64, 40), 65)

    def test_both_sensor_values_are_validated(self):
        curve = AutoCurve()
        with self.assertRaises(ValueError):
            curve.start(40, None)

    def test_optional_cpu_core_sensor_drives_the_curve(self):
        curve = AutoCurve()
        self.assertEqual(curve.start(48, 45, 72), 80)


if __name__ == "__main__":
    unittest.main()
