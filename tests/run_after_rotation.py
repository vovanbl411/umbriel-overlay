#!/usr/bin/env python3
"""Запустить offline suite на rotated checkout, исключив тест, который вызвал runner."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_automation import AutomationTests  # noqa: E402


def main() -> int:
    loader = unittest.defaultTestLoader
    # Регрессионный тест запускает этот runner; его исключение делает вложенный прогон конечным.
    suite = unittest.TestSuite(
        AutomationTests(name)
        for name in loader.getTestCaseNames(AutomationTests)
        if name != "test_rotation_does_not_break_suite_after_two_rotations"
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
