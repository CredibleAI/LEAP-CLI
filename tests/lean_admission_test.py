"""Experiment-facing global Lean admission regressions."""

import _path  # noqa: F401
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest import mock

import lean_verifier_tool


class GlobalLeanAdmissionTest(unittest.TestCase):

  def test_file_slots_bound_overlapping_local_checks_and_emit_events(self):
    with tempfile.TemporaryDirectory() as root:
      event_log = os.path.join(root, "events.jsonl")
      active = 0
      peak = 0
      lock = threading.Lock()

      def held():
        nonlocal active, peak
        with lean_verifier_tool._global_lean_admission():
          with lock:
            active += 1
            peak = max(peak, active)
          time.sleep(0.08)
          with lock:
            active -= 1

      env = {
          "LEAP_LEAN_SLOT_DIR": os.path.join(root, "slots"),
          "LEAP_MAX_LEAN_CHECKS": "1",
          "LEAP_EVENT_LOG": event_log,
          "LEAP_CAMPAIGN_ID": "campaign",
          "LEAP_CELL_ID": "cell",
      }
      with mock.patch.dict(os.environ, env, clear=False):
        threads = [threading.Thread(target=held) for _ in range(2)]
        for thread in threads:
          thread.start()
        for thread in threads:
          thread.join()
      self.assertEqual(peak, 1)
      events = [
          json.loads(line)
          for line in Path(event_log).read_text(encoding="utf-8").splitlines()
      ]
      self.assertEqual(
          [event["event"] for event in events],
          [
              "lean_slot_acquired",
              "lean_slot_released",
              "lean_slot_acquired",
              "lean_slot_released",
          ],
      )
      self.assertGreater(events[2]["queue_wait_seconds"], 0)


if __name__ == "__main__":
  unittest.main()

