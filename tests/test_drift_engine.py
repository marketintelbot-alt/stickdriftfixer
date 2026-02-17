from __future__ import annotations

import unittest

import drift_engine as engine


class DriftEngineTests(unittest.TestCase):
    def build_config(self, **overrides: float) -> engine.StickRuntimeConfig:
        config = engine.StickRuntimeConfig(
            center_x=0.0,
            center_y=0.0,
            deadzone_x=0.1,
            deadzone_y=0.1,
        )
        for key, value in overrides.items():
            setattr(config, key, value)
        return config

    def test_deadzone_zeroes_small_input(self) -> None:
        processor = engine.StickProcessor()
        cfg = self.build_config(deadzone_x=0.15, deadzone_y=0.15, smoothing=0.0)

        result = processor.process((0.05, 0.04), cfg, dt=1 / 60)
        self.assertAlmostEqual(result.corrected[0], 0.0, places=5)
        self.assertAlmostEqual(result.corrected[1], 0.0, places=5)

    def test_anti_deadzone_outputs_minimum_non_zero(self) -> None:
        processor = engine.StickProcessor()
        cfg = self.build_config(
            deadzone_x=0.15,
            deadzone_y=0.15,
            anti_deadzone=0.15,
            smoothing=0.0,
        )

        result = processor.process((0.2, 0.0), cfg, dt=1 / 60)
        self.assertGreater(abs(result.corrected[0]), 0.14)

    def test_smoothing_reduces_jump(self) -> None:
        processor = engine.StickProcessor()
        cfg = self.build_config(deadzone_x=0.0, deadzone_y=0.0, smoothing=0.8)

        first = processor.process((1.0, 0.0), cfg, dt=1 / 60)
        second = processor.process((1.0, 0.0), cfg, dt=1 / 60)

        self.assertGreater(abs(second.corrected[0]), abs(first.corrected[0]))
        self.assertLess(abs(first.corrected[0]), 1.0)

    def test_adaptive_center_moves_toward_neutral_bias(self) -> None:
        processor = engine.StickProcessor()
        cfg = self.build_config(
            deadzone_x=0.08,
            deadzone_y=0.08,
            adaptive_center=True,
            adaptive_learning_rate=0.04,
            adaptive_limit=0.2,
            smoothing=0.0,
        )

        for _ in range(120):
            processor.process((0.08, -0.06), cfg, dt=1 / 60)

        result = processor.process((0.08, -0.06), cfg, dt=1 / 60)
        self.assertGreater(result.metrics.adaptive_x, 0.03)
        self.assertLess(result.metrics.adaptive_y, -0.02)

    def test_metrics_report_suppression(self) -> None:
        comp = engine.DriftCompensator()
        cfg = self.build_config(deadzone_x=0.12, deadzone_y=0.12, smoothing=0.0)

        for _ in range(150):
            left, right = comp.process_pair((0.09, 0.02), (0.07, -0.01), cfg, cfg, dt=1 / 60)

        self.assertGreaterEqual(left.metrics.suppression, 70.0)
        self.assertGreaterEqual(right.metrics.suppression, 70.0)


if __name__ == "__main__":
    unittest.main()
