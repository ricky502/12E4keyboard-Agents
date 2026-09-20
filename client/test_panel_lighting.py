"""Selection highlight and bottom action-panel regression tests."""

import sys
import unittest
from pathlib import Path


HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import importlib.util


spec = importlib.util.spec_from_file_location("agentpad_clientd_lighting", HERE / "agentpad-clientd.py")
clientd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(clientd)


class PanelLightingTests(unittest.TestCase):
    def test_selected_agent_keeps_original_state_color(self):
        selected_rgb, selected_mode = clientd.agent_visual(2, "thinking_shared", 2)
        other_rgb, other_mode = clientd.agent_visual(1, "thinking_shared", 2)
        self.assertEqual(selected_rgb, clientd.STATE_COLORS["thinking_shared"][0])
        self.assertEqual(selected_mode, other_mode)
        self.assertTrue(all(a <= b for a, b in zip(other_rgb, selected_rgb)))
        self.assertNotEqual(other_rgb, selected_rgb)

    def test_only_selected_idle_agent_breathes(self):
        selected_rgb, selected_mode = clientd.agent_visual(2, "idle", 2)
        other_rgb, other_mode = clientd.agent_visual(1, "idle", 2)
        self.assertEqual(selected_rgb, clientd.STATE_COLORS["idle"][0])
        self.assertEqual(selected_mode, 2)
        self.assertEqual((other_rgb, other_mode), ((0, 0, 0), 0))

    def test_selection_never_changes_error_or_owner_hue(self):
        for state in ("thinking", "thinking_shared", "thinking_other", "error"):
            original, original_mode = clientd.STATE_COLORS[state]
            selected, selected_mode = clientd.agent_visual(0, state, 0)
            self.assertEqual((selected, selected_mode), (original, original_mode))

    def test_idle_action_panel(self):
        visuals = clientd.action_panel_visuals("idle")
        self.assertEqual(visuals[8][2], "idle")
        self.assertEqual(visuals[11][2], "idle")
        self.assertEqual(visuals[9][2], "off")
        self.assertEqual(visuals[10][2], "off")

    def test_waiting_complete_and_error_prompts(self):
        waiting = clientd.action_panel_visuals("needs_input")
        self.assertEqual(waiting[9][2], "needs_input")
        self.assertEqual(waiting[9][1], clientd.STATE_COLORS["needs_input"][1])
        complete = clientd.action_panel_visuals("complete")
        self.assertEqual(complete[11][2], "complete")
        error = clientd.action_panel_visuals("error")
        self.assertEqual({value[2] for value in error.values()}, {"error"})
        self.assertEqual({value[1] for value in error.values()},
                         {clientd.STATE_COLORS["error"][1]})

    def test_active_owner_states_leave_only_talk_lit(self):
        for state in ("thinking", "thinking_shared", "thinking_other"):
            visuals = clientd.action_panel_visuals(state)
            self.assertEqual(visuals[8][2], "idle")
            self.assertEqual({visuals[slot][2] for slot in (9, 10, 11)}, {"off"})


if __name__ == "__main__":
    unittest.main()
