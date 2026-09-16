"""Run with: python3 -m unittest client/test_feishu_owner_state.py"""

import sys
import unittest
import importlib.util
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from feishu_owner_state import OwnerState
from feishu_status_listener import parse_status

daemon_spec = importlib.util.spec_from_file_location(
    "agentpad_clientd", Path(__file__).parent / "agentpad-clientd.py")
daemon_module = importlib.util.module_from_spec(daemon_spec)
daemon_spec.loader.exec_module(daemon_module)
Daemon = daemon_module.Daemon


SELF = "ou_self"
OTHER = "ou_other"


class OwnerStateTests(unittest.TestCase):
    def setUp(self):
        self.states = OwnerState({"tanchun": SELF, "daiyu": SELF})

    def test_self_then_other_then_self_done_then_other_done(self):
        self.assertEqual(self.states.update("tanchun", "thinking", "a", SELF, now=10)["state"], "thinking")
        self.assertEqual(self.states.update("tanchun", "thinking", "b", OTHER, now=11)["state"], "thinking_shared")
        self.assertEqual(self.states.update("tanchun", "complete", "a", now=12)["state"], "thinking_other")
        self.assertEqual(self.states.update("tanchun", "complete", "b", now=13)["state"], "complete")

    def test_other_only_and_ownerless_heartbeat(self):
        self.assertEqual(self.states.update("daiyu", "thinking", "x", OTHER, now=10)["state"], "thinking_other")
        self.assertEqual(self.states.update("daiyu", "thinking", "x", now=11)["state"], "thinking_other")
        self.assertEqual(self.states.tasks["daiyu"]["x"]["owner"], OTHER)
        self.assertEqual(self.states.update("daiyu", "idle", "x", now=12)["state"], "idle")

    def test_two_tasks_same_owner_stay_blue(self):
        self.states.update("daiyu", "thinking", "x", SELF, now=10)
        self.assertEqual(self.states.update("daiyu", "thinking", "y", SELF, now=11)["state"], "thinking")
        self.assertEqual(self.states.update("daiyu", "complete", "x", now=12)["state"], "thinking")

    def test_late_heartbeat_does_not_revive_done_task(self):
        self.states.update("daiyu", "thinking", "x", SELF, now=10)
        self.states.update("daiyu", "complete", "x", now=11)
        self.assertEqual(self.states.update("daiyu", "thinking", "x", now=12)["state"], "complete")

    def test_expire_only_stale_owner(self):
        self.states.update("tanchun", "thinking", "a", SELF, now=10)
        self.states.update("tanchun", "thinking", "b", OTHER, now=20)
        changed = self.states.expire(30, active_ttl=15, terminal_ttl=60)
        self.assertEqual(changed[0][1]["state"], "thinking_other")

    def test_parse_owner_and_chat(self):
        status = parse_status('[AGENTPAD] {"agent":"tanchun","state":"thinking","task_id":"a",'
                              '"owner":"ou_self","chat":"oc_chat"}')
        self.assertEqual((status["owner"], status["chat"]), (SELF, "oc_chat"))
        self.assertIsNone(parse_status('[AGENTPAD] {"agent":"tanchun","state":"thinking",'
                                       '"owner":{"bad":true}}'))

    def test_unmapped_agent_never_mislabels_one_owner_as_other(self):
        self.assertEqual(self.states.update("xiangyun", "thinking", "a", OTHER, now=10)["state"], "thinking")
        self.assertTrue(self.states.view("xiangyun")["unknown_active"])
        self.assertEqual(self.states.update("xiangyun", "thinking", "b", SELF, now=11)["state"], "thinking_shared")

    def test_daemon_paints_physical_agent_slot(self):
        class Link:
            mock = True
            def __init__(self):
                self.packets = []
            def send(self, packet):
                self.packets.append(packet)
                return True

        link = Link()
        daemon = Daemon(link, {"feishu_status_self_owners": {"tanchun": SELF}})
        daemon.set_agent_state("tanchun", "thinking", "a", owner=SELF)
        self.assertEqual(link.packets[-2][:5], bytes([1, 0, 0, 60, 255]))
        daemon.set_agent_state("tanchun", "thinking", "b", owner=OTHER)
        self.assertEqual(link.packets[-2][:5], bytes([1, 0, 255, 190, 0]))
        daemon.set_agent_state("tanchun", "complete", "a")
        self.assertEqual(link.packets[-2][:5], bytes([1, 0, 255, 0, 0]))
        self.assertEqual(daemon.health()["feishu_owner_activity"]["tanchun"]["active_tasks"], 1)


if __name__ == "__main__":
    unittest.main()
