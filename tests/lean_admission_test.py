"""Experiment-facing global Lean admission regressions."""

import _path  # noqa: F401
import asyncio
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

  def test_event_identity_isolated_across_tasks_and_copied_to_threads(self):
    with tempfile.TemporaryDirectory() as root:
      event_log = os.path.join(root, "events.jsonl")

      async def emit(cell):
        with lean_verifier_tool.event_identity(
            campaign_id="campaign", wave_id="wave", cell_id=cell
        ):
          await asyncio.sleep(0)
          await asyncio.to_thread(lean_verifier_tool._append_event, "thread", expected=cell)
          lean_verifier_tool._append_event("task", expected=cell)

      async def run():
        await asyncio.gather(emit("a"), emit("b"))

      with mock.patch.dict(os.environ, {
          "LEAP_EVENT_LOG": event_log, "LEAP_CELL_ID": "fallback"
      }):
        asyncio.run(run())
        lean_verifier_tool._append_event("outside", expected="fallback")
      events = [json.loads(line) for line in Path(event_log).read_text().splitlines()]
      self.assertEqual(len(events), 5)
      self.assertTrue(all(row["cell_id"] == row["expected"] for row in events))

  def test_file_slots_bound_overlapping_local_checks_and_emit_events(self):
    with tempfile.TemporaryDirectory() as root:
      event_log = os.path.join(root, "events.jsonl")
      active = 0
      peak = 0
      lock = threading.Lock()

      def held():
        nonlocal active, peak
        with lean_verifier_tool._global_lean_admission(
            check_kind="compile", check_id=f"check-{threading.get_ident()}"
        ):
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
          "LEAP_WAVE_ID": "wave",
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
      names = [event["event"] for event in events]
      self.assertEqual(names.count("lean_check_enqueued"), 2)
      self.assertEqual(names.count("lean_slot_acquired"), 2)
      self.assertEqual(names.count("lean_slot_released"), 2)
      acquired = [event for event in events if event["event"] == "lean_slot_acquired"]
      released = [event for event in events if event["event"] == "lean_slot_released"]
      self.assertGreater(max(event["queue_wait_seconds"] for event in acquired), 0)
      self.assertTrue(all(event["held_seconds"] > 0 for event in released))
      self.assertEqual(len({event["event_id"] for event in events}), 6)
      self.assertTrue(all(event["wave_id"] == "wave" for event in events))
      self.assertTrue(all(event["check_kind"] == "compile" for event in events))
      check_ids = {event["lean_check_id"] for event in events}
      self.assertEqual(len(check_ids), 2)
      for check_id in check_ids:
        self.assertEqual(
            [event["event"] for event in events if event["lean_check_id"] == check_id],
            ["lean_check_enqueued", "lean_slot_acquired", "lean_slot_released"],
        )


if __name__ == "__main__":
  unittest.main()

