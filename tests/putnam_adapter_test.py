"""Experiment-facing root-mode and required-definition regressions."""

import _path  # noqa: F401
import os
import tempfile
import unittest
from unittest import mock

import actions
import claim_terminal
import dag
import pipeline
import state_manager


REQUIRED = "noncomputable abbrev putnam_solution : Nat := sorry"


def graph_with_required_definition():
  graph = dag.ProofGraph()
  graph.graph_metadata.update(
      root_id="putnam_root",
      required_definitions=REQUIRED,
      required_definition_names=["putnam_solution"],
  )
  graph.add_node(
      dag.ProofGraphNode(
          id="putnam_root",
          informal_problem=state_manager.models.InformalProblem(
              statement="theorem putnam_root : True"
          ),
          search_metadata={"phase": "formal"},
      )
  )
  return graph


class RequiredDefinitionsTest(unittest.TestCase):

  def test_requires_exact_signature_but_accepts_agent_body(self):
    graph = graph_with_required_definition()
    self.assertIn(
        "missing",
        state_manager._validate_required_definitions(
            graph, "putnam_root", ""
        ),
    )
    self.assertIn(
        "signature changed",
        state_manager._validate_required_definitions(
            graph,
            "putnam_root",
            "noncomputable abbrev putnam_solution : Int := 3",
        ),
    )
    self.assertIsNone(
        state_manager._validate_required_definitions(
            graph,
            "putnam_root",
            "noncomputable abbrev putnam_solution : Nat := 3",
        )
    )

  def test_formal_root_bypasses_planner_and_renders_solution_hole(self):
    source = "import Mathlib\n\ntheorem putnam_root : True := by\n  sorry\n"
    with tempfile.TemporaryDirectory() as root:
      with mock.patch.object(
          state_manager.graph_init_guard,
          "check_root_compiles",
          return_value=None,
      ):
        result = state_manager.run_state_manager(
            state_manager.StateManagerInput(
                action="init_graph",
                root_dir=root,
                root_id="putnam_root",
                statement=source,
                root_phase="formal",
                required_definitions=REQUIRED,
                freeze_root_plan=True,
            )
        )
      self.assertTrue(result.success, result.error_message)
      manager = state_manager.ProofGraphStateManager(
          filepath=os.path.join(root, "proof_graph.json"),
          root_dir=root,
          root_id="putnam_root",
      )
      claimed = manager.claim_next_subgoal()
      self.assertEqual(claimed["phase"], "formal")
      self.assertEqual(claimed["action_type"], "lemma_proof_worker")
      with open(claimed["scaffold_path"], encoding="utf-8") as f:
        scaffold = f.read()
      self.assertIn(REQUIRED, scaffold)
      ok, message = actions.declare(
          manager,
          "putnam_root",
          "replan",
          "The frozen root treatment remains the required plan.",
      )
      self.assertTrue(ok, message)
      graph = manager.read_graph()
      self.assertEqual(
          pipeline.current_phase_name(graph.nodes["putnam_root"]), "formal"
      )
      self.assertFalse(
          graph.nodes["putnam_root"].search_metadata["processing"]
      )


  def test_formal_submission_budget_is_atomic_and_terminal(self):
    with tempfile.TemporaryDirectory() as root:
      manager = state_manager.ProofGraphStateManager(
          filepath=os.path.join(root, "proof_graph.json"),
          root_dir=root,
          root_id="putnam_root",
      )
      graph = graph_with_required_definition()
      graph.nodes["putnam_root"].search_metadata["processing"] = True
      manager.initialize_graph(graph)
      with mock.patch.dict(
          os.environ, {"LEAP_MAX_FORMAL_SUBMISSIONS": "1"}, clear=False
      ):
        admitted, _ = manager._admit_formal_submission("putnam_root")
        exhausted, message = manager._admit_formal_submission("putnam_root")
      self.assertTrue(admitted)
      self.assertFalse(exhausted)
      self.assertIn("BUDGET EXHAUSTED", message)
      saved = manager.read_graph()
      self.assertEqual(saved.graph_metadata["formal_submission_count"], 1)
      self.assertEqual(saved.graph_metadata["terminal_state"], "budget_exhausted")
      self.assertFalse(saved.nodes["putnam_root"].search_metadata["processing"])
      self.assertIsNone(manager.claim_next_subgoal())
      terminal = claim_terminal.why_nothing_to_claim(saved, "putnam_root")
      self.assertIn("BUDGET_EXHAUSTED", terminal)


if __name__ == "__main__":
  unittest.main()
