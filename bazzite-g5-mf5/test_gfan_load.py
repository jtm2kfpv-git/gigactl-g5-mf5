import unittest
from types import SimpleNamespace
from unittest.mock import patch

import gfan_load


class CpuLoadTests(unittest.TestCase):
    def test_parse_aggregate_ticks_ignores_guest_double_count(self):
        self.assertEqual(
            gfan_load.parse_cpu_times("cpu 110 50 40 720 30 5 4 11 120 5"),
            (970, 750),
        )

    def test_busy_percent_uses_idle_and_iowait_deltas(self):
        previous = gfan_load.parse_cpu_times("cpu 100 50 20 700 30 2 3 5 100 5")
        current = gfan_load.parse_cpu_times("cpu 110 50 40 720 30 5 4 11 120 5")
        self.assertEqual(gfan_load.cpu_percent(previous, current), 67)

    def test_first_sample_and_zero_delta_have_no_percentage(self):
        sample = (100, 70)
        self.assertIsNone(gfan_load.cpu_percent(None, sample))
        self.assertIsNone(gfan_load.cpu_percent(sample, sample))

    def test_rejects_invalid_proc_stat_line(self):
        with self.assertRaises(ValueError):
            gfan_load.parse_cpu_times("intr 10")


class GpuLoadTests(unittest.TestCase):
    def test_parse_nvidia_smi_output(self):
        self.assertEqual(gfan_load.parse_gpu_percent("0\n 47 \nN/A\n101\n"), 47)
        self.assertIsNone(gfan_load.parse_gpu_percent("N/A\n"))

    @patch("gfan_load.glob.glob", return_value=[])
    @patch("gfan_load.subprocess.run", return_value=SimpleNamespace(returncode=0, stdout="38\n"))
    @patch("gfan_load.shutil.which", return_value="/usr/bin/nvidia-smi")
    def test_prefers_nvidia_smi_when_available(self, _which, run, _glob):
        self.assertEqual(gfan_load.gpu_percent(), 38)
        run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
