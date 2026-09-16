"""Dial-four routing and fast font zoom regression tests."""

import importlib.util
import queue
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))


def load_module(filename, name):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


clientd = load_module("agentpad-clientd.py", "agentpad_clientd_zoom_test")
commandd = load_module("agentpad-commandd.py", "agentpad_commandd_zoom_test")


class EncoderZoomTests(unittest.TestCase):
    def test_zoom_uses_quartz_command_shortcuts(self):
        with patch.object(commandd, "post_key_code", return_value={"ok": True}) as post:
            commandd.local_zoom(True)
            commandd.local_zoom(False)
        self.assertEqual(post.call_args_list[0].args, (24, "zoom_in"))
        self.assertEqual(post.call_args_list[1].args, (27, "zoom_out"))
        self.assertEqual([call.kwargs["flags"] for call in post.call_args_list],
                         [1 << 20, 1 << 20])

    def test_dial_four_rotation_and_press_share_ordered_lane(self):
        daemon = clientd.Daemon.__new__(clientd.Daemon)
        daemon.cfg = {"command_forward_url": "http://127.0.0.1:8125/command"}
        daemon.selected_agent = 0
        daemon.state_meta = {0: {"task_id": None}}
        daemon._command_queues = {name: queue.Queue(maxsize=64)
                                  for name in ("codex", "local", "zoom")}
        daemon._forward_command("encoder", source=0, clockwise=True)
        daemon._forward_command("encoder_press", source=0)
        daemon._forward_command("encoder", source=0, clockwise=False)
        self.assertTrue(daemon._command_queues["local"].empty())
        self.assertEqual([daemon._command_queues["zoom"].get_nowait()[1]["action"]
                          for _ in range(3)],
                         ["encoder", "encoder_press", "encoder"])


if __name__ == "__main__":
    unittest.main()
