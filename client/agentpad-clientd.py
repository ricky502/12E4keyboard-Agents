#!/usr/bin/env python3
"""agentpad-client — 老杨 Mac 上的点灯常驻程序（零依赖版，探春 2026-08-24）.

架构: 状态源(飞书/本机 Agent 适配器) --> 本程序 --raw HID--> 12E4 键盘灯
依赖: 仅 macOS 自带 python3 (3.9+) + 本包 hid/libhidapi.dylib (纯系统框架链接, 无需 brew/pip)

用法:
  ./agentpad-clientd.py --selftest       # 装完先跑: 找键盘→PING→彩灯扫一遍→恢复
  ./agentpad-clientd.py                  # 前台跑 daemon (调试用)
  ./agentpad-clientd.py --mock           # 无键盘模拟模式 (开发/演示)
  ./agentpad-clientd.py --port 8124      # 改端口

HTTP API (状态推送方用):
  POST /state       {"agent":"tanchun","state":"thinking","task_id":"...","updated_at":...}
                    # 或 {"slot":0,"state":...}; updated_at 是 Unix 秒，缺省为本机收到时刻
  POST /state/all   {"state":"off"}
  POST /brightness  {"value":160}
  POST /ping        强制 PING/PONG 往返
  GET  /health      键盘在线+各槽位状态
状态: idle(白) thinking(蓝) complete(绿) needs_input(琥珀呼吸) error(红闪) off
agent: tanchun/daiyu/xiangyun/xiangling/yinger/codex/claude-vscode/baochai (8 Agent)

键盘按键事件(KEY_EVENT 0x81): 日志记录 + (若 config.key_forward_url 配置) POST 转发。

config.json (首次自动生成, 可手改):
  {"port":8124, "brightness":160, "token":"", "bind":"127.0.0.1", "key_forward_url":"", "command_forward_url":"http://127.0.0.1:8125/command", "command_token":"", "feishu_local_observer":false}
  token 非空时所有请求须带请求头 X-Agentpad-Token: <同值>
"""

import argparse
import ctypes
import json
import os
import queue
import subprocess
import sys
import threading
import time
from ctypes import (POINTER, Structure, byref, c_char_p, c_int, c_ushort,
                    c_void_p, c_wchar_p, create_string_buffer)
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from ap_protocol import (LED_COUNT, PID, PROTO_VER, RAW_USAGE, RAW_USAGE_PAGE,
                         STATE_COLORS, VID, Virtual12E4, clear_all, parse,
                         ping, set_brightness, set_mode, set_slot)

DEFAULT_CONFIG = {"port": 8124, "brightness": 160, "token": "",
                  "bind": "127.0.0.1", "key_forward_url": "",
                  "command_forward_url": "http://127.0.0.1:8125/command",
                  "command_token": "", "feishu_local_observer": False,
                  "feishu_status_monitor": False, "feishu_status_app_id": "",
                  "feishu_status_chat_id": "", "thinking_timeout_s": 300,
                  "terminal_state_timeout_s": 1800,
                  # Optional, non-secret customization. This only changes
                  # local routing/presentation; it never reprograms 12E4.
                  "panel_profile": {}}
HEARTBEAT_S = 2.0
MISSES_TILL_OFFLINE = 3
RECONNECT_SCAN_S = 5.0
# 状态超过此时间没有更新，/health 标为 stale。
STATE_STALE_S = 15 * 60

AGENT_SLOTS = {
    0: "tanchun", 1: "daiyu", 2: "xiangyun", 3: "xiangling",
    4: "yinger", 5: "codex", 6: "claude-vscode", 7: "baochai",
}
FUNCTION_SLOTS = {8: "talk", 9: "approve", 10: "reject", 11: "new_task"}
SLOT_AGENTS = {**AGENT_SLOTS, **FUNCTION_SLOTS}
# The four rotary switches are wired in a different order from their rotary
# reports.  Physical buttons one and two were verified on this 12E4 as slots
# 14 and 15, respectively; use their intended local system actions.
ENCODER_PRESS_SLOTS = {12: 1, 13: 0, 14: 2, 15: 3}
# Bottom row is the keyboard/client power indicator.  It stays at the neutral
# idle white whenever this local daemon is running; only the eight Agent keys
# communicate Agent state.
FUNCTION_ONLINE_STATE = "idle"


def apply_panel_profile(cfg: dict) -> list[str]:
    """Apply safe local presentation/routing overrides from config.json.

    The 12E4 firmware still emits the same numbered slots. A profile can
    reorder the eight Agent identities and customize RGB meanings without a
    reflash. Invalid values are ignored individually and returned by /doctor.
    """
    profile = cfg.get("panel_profile") or {}
    warnings = []
    agents = profile.get("agent_slots")
    if agents is not None:
        if (isinstance(agents, list) and len(agents) == 8 and
                all(isinstance(name, str) and name for name in agents) and
                len(set(agents)) == 8):
            AGENT_SLOTS.clear()
            AGENT_SLOTS.update(enumerate(agents))
        else:
            warnings.append("panel_profile.agent_slots 必须是 8 个不重复的 Agent 名称")

    actions = profile.get("function_actions")
    if actions is not None:
        expected = {"talk", "approve", "reject", "new_task"}
        if (isinstance(actions, list) and len(actions) == 4 and
                set(actions) == expected):
            FUNCTION_SLOTS.clear()
            FUNCTION_SLOTS.update({8 + index: action for index, action in enumerate(actions)})
        else:
            warnings.append("panel_profile.function_actions 必须恰好包含 talk/approve/reject/new_task")

    colors = profile.get("state_colors")
    if colors is not None:
        if not isinstance(colors, dict):
            warnings.append("panel_profile.state_colors 必须是对象")
        else:
            for state, definition in colors.items():
                if state not in STATE_COLORS:
                    warnings.append(f"未知状态颜色: {state}")
                    continue
                if (not isinstance(definition, dict) or
                        not isinstance(definition.get("rgb"), list) or
                        len(definition["rgb"]) != 3 or
                        not all(isinstance(value, int) and 0 <= value <= 255
                                for value in definition["rgb"]) or
                        not isinstance(definition.get("mode", 0), int) or
                        definition.get("mode", 0) not in (0, 1, 2)):
                    warnings.append(f"状态颜色 {state} 格式无效")
                    continue
                STATE_COLORS[state] = (tuple(definition["rgb"]), definition.get("mode", 0))

    SLOT_AGENTS.clear()
    SLOT_AGENTS.update({**AGENT_SLOTS, **FUNCTION_SLOTS})
    return warnings


def safe_panel_profile(cfg: dict) -> dict:
    """Return only non-secret local customization for GET /profile."""
    return {
        "agent_slots": [AGENT_SLOTS[slot] for slot in sorted(AGENT_SLOTS)],
        "function_actions": [FUNCTION_SLOTS[slot] for slot in sorted(FUNCTION_SLOTS)],
        "state_colors": {
            state: {"rgb": list(rgb), "mode": mode}
            for state, (rgb, mode) in STATE_COLORS.items()
        },
        "configured": bool(cfg.get("panel_profile")),
    }


def log(*a):
    print(time.strftime("[%H:%M:%S]"), *a, flush=True)


# --------------------------------------------------------------------------
# hidapi ctypes 绑定 (捆绑 dylib, 不依赖 brew/pip)
# --------------------------------------------------------------------------

class HidDeviceInfo(Structure):
    """hidapi 0.15 hid_device_info: 注意 next 指针在结构体末尾(官方头文件如此)."""
    _fields_ = [
        ("path", c_char_p),
        ("vendor_id", c_ushort),
        ("product_id", c_ushort),
        ("serial_number", c_wchar_p),
        ("release_number", c_ushort),
        ("manufacturer_string", c_wchar_p),
        ("product_string", c_wchar_p),
        ("usage_page", c_ushort),
        ("usage", c_ushort),
        ("interface_number", c_int),
        ("next", c_void_p),
    ]


def load_hidapi():
    p = os.path.join(HERE, "hid", "libhidapi.dylib")
    if not os.path.exists(p):
        log(f"❌ 缺 {p}"); sys.exit(2)
    lib = ctypes.CDLL(p)
    lib.hid_init.restype = c_int
    lib.hid_exit.restype = c_int
    lib.hid_enumerate.argtypes = [c_ushort, c_ushort]
    lib.hid_enumerate.restype = POINTER(HidDeviceInfo)
    lib.hid_free_enumeration.argtypes = [POINTER(HidDeviceInfo)]
    lib.hid_open_path.argtypes = [c_char_p]
    lib.hid_open_path.restype = c_void_p
    lib.hid_write.argtypes = [c_void_p, c_char_p, ctypes.c_size_t]
    lib.hid_write.restype = c_int
    lib.hid_read_timeout.argtypes = [c_void_p, c_char_p, ctypes.c_size_t, c_int]
    lib.hid_read_timeout.restype = c_int
    lib.hid_close.argtypes = [c_void_p]
    lib.hid_error.argtypes = [c_void_p]
    lib.hid_error.restype = c_wchar_p
    if lib.hid_init() != 0:
        log("❌ hid_init 失败"); sys.exit(2)
    return lib


def enumerate_raw_interface(lib):
    """-> raw HID 接口 path (usage 0xFF60:0x61) 或 None. 结构体布局错位会自检出."""
    head = lib.hid_enumerate(VID, PID)
    if not head:
        return None
    path, node, hops = None, head, 0
    while node and hops < 16:
        info = node.contents
        if info.vendor_id != VID or info.product_id != PID:
            lib.hid_free_enumeration(head)
            raise RuntimeError("hidapi 结构体布局与 dylib 不符 (vendor_id 校验失败)")
        if info.usage_page == RAW_USAGE_PAGE and info.usage == RAW_USAGE:
            path = info.path  # c_char_p -> bytes, 随链表释放仍有效? 拷贝保平安
            path = ctypes.string_at(info.path) if info.path else None
            break
        nxt = info.next
        node = ctypes.cast(nxt, POINTER(HidDeviceInfo)) if nxt else None
        hops += 1
    lib.hid_free_enumeration(head)
    return path


class KeyboardLink:
    """真键盘 (ctypes hidapi) 或 Virtual12E4 mock."""

    def __init__(self, mock: bool):
        self.mock = mock
        self.lib = None if mock else load_hidapi()
        self.dev = None
        # HID handles become invalid immediately when the keyboard is unplugged.
        # Keep every open/read/write/close operation serialized so a status
        # update can never write through a handle another thread just closed.
        self._io_lock = threading.RLock()
        self.virtual = Virtual12E4() if mock else None
        self.last_sent = []  # mock: 发往键盘的包 (测试用)

    def open(self) -> bool:
        if self.mock:
            return True
        with self._io_lock:
            if self.dev:
                return True
            path = enumerate_raw_interface(self.lib)
            if not path:
                return False
            self.dev = self.lib.hid_open_path(path)
            return bool(self.dev)

    def send(self, pkt: bytes) -> bool:
        """-> False = 设备故障 (调用方应转 offline 并重连)."""
        try:
            if self.mock:
                self.last_sent.append(pkt)
                self.virtual.feed(pkt)
                return True
            with self._io_lock:
                # Do not call into hidapi after unplug/close. hidapi's macOS
                # backend dereferences a null handle and would SIGSEGV.
                if not self.dev:
                    return False
                buf = create_string_buffer(b"\x00" + pkt, 33)  # macOS 前置 report-id 0
                return self.lib.hid_write(self.dev, buf, 33) == 33
        except Exception:
            return False

    def read(self, timeout_ms: int):
        raw = None
        if self.mock:
            if self.virtual.outbox:
                raw = self.virtual.outbox.pop(0)
        else:
            with self._io_lock:
                if not self.dev:
                    return None
                buf = create_string_buffer(64)
                n = self.lib.hid_read_timeout(self.dev, buf, 64, timeout_ms)
                if n > 0:
                    raw = buf.raw[:n]
        return parse(raw) if raw else None

    def close(self):
        if self.mock:
            return
        with self._io_lock:
            dev, self.dev = self.dev, None
            if dev:
                self.lib.hid_close(dev)


# --------------------------------------------------------------------------
# daemon 本体
# --------------------------------------------------------------------------

class Daemon:
    def __init__(self, link: KeyboardLink, cfg: dict):
        self.link = link
        self.cfg = cfg
        # A ready panel keeps every configured key visible: Agent keys breathe
        # while idle, while the bottom-row function keys remain solid white.
        self.states = {s: "idle" for s in range(LED_COUNT)}
        self.state_meta = {s: {"updated_at": 0, "task_id": None, "source": None}
                           for s in range(LED_COUNT)}
        for s in FUNCTION_SLOTS:
            self.state_meta[s] = {"updated_at": time.time(), "task_id": None,
                                  "source": "client-online"}
        for s in AGENT_SLOTS:
            self.state_meta[s] = {"updated_at": time.time(), "task_id": None,
                                  "source": "local-agentpad-ready"}
        self.online = False
        self.t0 = time.time()
        self.key_events = []          # 最近按键事件 (环形, /health 里带最近 8 条)
        self._echo = 0
        self._misses = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._next_reconnect_scan = 0.0
        self.selected_agent = 0
        self._press_times = {}
        self.profile_warnings = []
        # Raw-HID reads must never wait for a slow local app integration.
        # Commands run off the keyboard I/O thread so the panel remains
        # responsive while Codex refreshes its model catalogue.
        # Codex model discovery can take seconds.  It must never queue ahead
        # of volume, zoom, play/pause, or the physical function keys.
        self._command_queues = {
            "codex": queue.Queue(maxsize=1),
            "local": queue.Queue(maxsize=32),
        }
        for lane, command_queue in self._command_queues.items():
            threading.Thread(target=self._command_worker, args=(command_queue,),
                             daemon=True, name=f"agentpad-command-{lane}").start()

    # ---- 状态 -> 灯 ----
    def set_state(self, slot: int, state: str, task_id=None, updated_at=None, source=None) -> str:
        if state not in STATE_COLORS:
            return f"unknown state {state!r}"
        if not (0 <= slot < LED_COUNT):
            return f"slot out of range 0-{LED_COUNT - 1}"
        # Function keys are not Agent status LEDs. Keep them lit as the
        # local-power/client-online indicator even if a broad API update asks
        # to clear every slot.
        if slot in FUNCTION_SLOTS:
            state, task_id, source = FUNCTION_ONLINE_STATE, None, "client-online"
        rgb, mode = STATE_COLORS[state]
        # Visually distinguish connected Agent keys from the bottom-row power
        # indicators: a ready Agent breathes white; function keys stay static.
        if slot in AGENT_SLOTS and state == "idle":
            mode = 2
        prev = self.states[slot]
        try:
            updated_at = float(updated_at) if updated_at is not None else time.time()
        except (TypeError, ValueError):
            updated_at = time.time()
        with self._lock:
            self.states[slot] = state
            self.state_meta[slot] = {"updated_at": updated_at, "task_id": task_id,
                                     "source": source}
            ok1 = self.link.send(set_slot(slot, rgb))
            ok2 = self.link.send(set_mode(slot, mode))
        if not (ok1 and ok2):
            self.online = False
        return f"{SLOT_AGENTS.get(slot, slot)}[{slot}]: {prev} -> {state}"

    def boot_paint(self):
        with self._lock:
            self.link.send(set_brightness(self.cfg.get("brightness", 160)))
            self.link.send(clear_all())
        for s in range(LED_COUNT):
            meta = self.state_meta[s]
            self.set_state(s, self.states[s], **meta)

    def expire_agent_states(self):
        """Return stale remote LEDs to ready-white instead of leaving a history
        snapshot on the keyboard forever.

        A missing completion is most visible as a blue light, so it expires
        sooner.  Terminal states remain visible longer for acknowledgement.
        A newly received event always wins and immediately repaints the slot.
        """
        now = time.time()
        thinking_ttl = max(30, int(self.cfg.get("thinking_timeout_s", 300)))
        terminal_ttl = max(60, int(self.cfg.get("terminal_state_timeout_s", 1800)))
        expired = []
        with self._lock:
            for slot in AGENT_SLOTS:
                state = self.states[slot]
                updated = self.state_meta[slot].get("updated_at") or 0
                if not updated or state == "idle":
                    continue
                ttl = thinking_ttl if state == "thinking" else terminal_ttl
                if now - updated >= ttl:
                    expired.append((slot, state, int(now - updated)))
        for slot, previous, age in expired:
            result = self.set_state(slot, "idle", source="state-timeout")
            log(f"⌛ 状态超时 {SLOT_AGENTS[slot]} {previous} ({age}s) -> idle ({result})")

    def resolve_slot(self, body: dict) -> int:
        """body 里 agent 名或 slot 数字 -> 槽位; 无效返回 -1."""
        if "slot" in body:
            try:
                return int(body["slot"])
            except (TypeError, ValueError):
                return -1
        agent = str(body.get("agent", "")).lower()
        for slot, name in AGENT_SLOTS.items():
            if name == agent:
                return slot
        return -1

    def _command_for_slot(self, slot: int) -> str:
        """Map the four bottom keys to stable adapter action names."""
        return FUNCTION_SLOTS.get(slot, "select_agent")

    def acknowledge_completion(self, slot: int):
        """A press on a green Agent key acknowledges that completed task."""
        if slot in AGENT_SLOTS and self.states[slot] == "complete":
            result = self.set_state(slot, "idle", source="key-acknowledged")
            log(f"✓ 已确认完成 {SLOT_AGENTS[slot]} -> 白灯 ({result})")

    # ---- 心跳: PING/PONG + 事件泵 + 断线重连 ----
    def heartbeat(self):
        while not self._stop.is_set():
            self.expire_agent_states()
            if not self.link.mock and not self.link.dev:
                now = time.monotonic()
                # When unplugged, only scan for a returned USB device. Never
                # perform HID I/O until a fresh handle was opened.
                if now < self._next_reconnect_scan:
                    self._stop.wait(min(HEARTBEAT_S, self._next_reconnect_scan - now))
                    continue
                self._next_reconnect_scan = now + RECONNECT_SCAN_S
                if self.link.open():          # 重连成功
                    log("✅ 键盘重新上线, 重刷灯态")
                    self.online, self._misses = False, 0
                    self.boot_paint()
                else:
                    self._stop.wait(2.0)
                    continue
            self._echo = (self._echo + 1) & 0xFF or 1
            with self._lock:
                sent = self.link.send(ping(self._echo))
            got = None
            if sent:
                deadline = time.time() + HEARTBEAT_S
                while time.time() < deadline and got is None:
                    got = self.link.read(200)
                    if got and not (got["t"] == "pong" and got["echo"] == self._echo):
                        self._dispatch(got)   # 心跳窗口里先处理事件
                        got = None
            if got and got["t"] == "pong":
                self._misses, self.online = 0, True
            else:
                self._misses += 1
                if self._misses >= MISSES_TILL_OFFLINE:
                    if self.online:
                        log(f"⚠️ 键盘失联 ({self._misses} 次无 PONG)")
                    self.online = False
                    if self.link.mock:
                        self._misses = 0      # mock 永远在线
                    elif self._misses >= MISSES_TILL_OFFLINE + 2:
                        self.link.close()     # 彻底重开设备
                        self._misses = 0
            while True:
                pkt = self.link.read(0)
                if not pkt:
                    break
                self._dispatch(pkt)
            self._stop.wait(HEARTBEAT_S)

    def _dispatch(self, pkt):
        if pkt["t"] == "key":
            log(f"🔑 key slot={pkt['slot']}({SLOT_AGENTS.get(pkt['slot'], '?')}) "
                f"{'down' if pkt['pressed'] else 'up'} layer={pkt['layer']}")
            self.key_events.append({"t": int(time.time()), "slot": pkt["slot"],
                                    "name": SLOT_AGENTS.get(pkt["slot"]),
                                    "pressed": pkt["pressed"]})
            del self.key_events[:-8]
            slot = pkt["slot"]
            if pkt["pressed"]:
                self._press_times[slot] = time.monotonic()
                if slot in AGENT_SLOTS:
                    self.acknowledge_completion(slot)
                    self.selected_agent = slot
                    self._forward_command("select_agent", AGENT_SLOTS[slot], slot)
            if slot in FUNCTION_SLOTS:
                action = self._command_for_slot(slot)
                # Option and Return must mirror physical press/release. The
                # two right function keys remain one-shot actions on press.
                if pkt["pressed"] or action in ("talk", "approve"):
                    self._forward_command(action, AGENT_SLOTS.get(self.selected_agent), slot,
                                          pressed=bool(pkt["pressed"]))
            # Restored firmware emits the owner's original native shortcuts:
            # Option / Return / Copy / Paste.  Do not duplicate them here.
            if pkt["pressed"] and slot in ENCODER_PRESS_SLOTS:
                encoder = ENCODER_PRESS_SLOTS[slot]
                log(f"⏺ encoder press {encoder} (local system action)")
                self._forward_command("encoder_press", source=encoder)
            self._forward_key(self.key_events[-1])
        elif pkt["t"] == "enc":
            log(f"🎚 enc {pkt['enc']} {'cw' if pkt['cw'] else 'ccw'} layer={pkt['layer']}")
            # The firmware performs the backup JSON mapping directly.  This
            # prevents the former Codex model/effort routing from returning.

    def _forward_key(self, ev):
        url = self.cfg.get("key_forward_url") or ""
        if not url:
            return
        try:
            import urllib.request
            req = urllib.request.Request(url, data=json.dumps(ev).encode(),
                                         headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=2).read()
        except Exception as e:
            log(f"⚠️ key_forward 失败: {e}")

    def _forward_command(self, action, agent=None, source=None, **extra):
        url = self.cfg.get("command_forward_url") or ""
        if not url:
            return
        body = {"action": action, "agent": agent, "source": source,
                "selected_slot": self.selected_agent,
                "task_id": self.state_meta.get(self.selected_agent, {}).get("task_id"),
                **extra}
        # Keep slow model/effort RPC isolated.  A spin may produce dozens of
        # detents, but only the in-flight + one latest desired setting are
        # useful; system controls retain their own immediate lane.
        lane = "codex" if action == "encoder" and source in (2, 3) else "local"
        try:
            self._command_queues[lane].put_nowait((url, body))
        except queue.Full:
            if lane == "codex":
                # Replace a stale queued Codex detent with the latest one.
                try:
                    self._command_queues[lane].get_nowait()
                    self._command_queues[lane].task_done()
                    self._command_queues[lane].put_nowait((url, body))
                except queue.Empty:
                    pass
            else:
                log("⚠️ local command queue 满，丢弃一个过快事件")

    def _command_worker(self, command_queue):
        """Forward commands without blocking the HID heartbeat/event pump."""
        import urllib.request
        while not self._stop.is_set():
            try:
                url, body = command_queue.get(timeout=0.25)
            except queue.Empty:
                continue
            try:
                headers = {"Content-Type": "application/json"}
                command_token = self.cfg.get("command_token") or ""
                if command_token:
                    headers["X-Agentpad-Token"] = command_token
                req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers)
                # Model list initialization can take several seconds on first
                # use; waiting here is harmless because this is a worker.
                with urllib.request.urlopen(req, timeout=25) as response:
                    reply = json.loads(response.read().decode() or "{}")
                if reply.get("ok"):
                    if reply.get("action", "").startswith("volume_"):
                        level = reply.get("volume")
                        suffix = f" → {level}%" if level is not None else ""
                        log(f"✓ 第三个旋钮：{reply['action']}{suffix}")
                    else:
                        log(f"✓ command_forward {reply.get('action', body.get('action', '?'))}")
                else:
                    log(f"⚠️ command_forward {body.get('action', '?')} 未执行: {reply}")
            except Exception as e:
                log(f"⚠️ command_forward {body.get('action', '?')} 失败: {e}")
            finally:
                command_queue.task_done()

    def health(self):
        now = time.time()
        agent_status = {}
        for s in range(LED_COUNT):
            meta = self.state_meta[s]
            agent_status[SLOT_AGENTS.get(s, str(s))] = {
                "state": self.states[s], **meta,
                "stale": bool(meta["updated_at"] and now - meta["updated_at"] > STATE_STALE_S),
            }
        return {"ok": True, "keyboard_online": self.online,
                "proto": PROTO_VER, "uptime_s": int(time.time() - self.t0),
                "states": {SLOT_AGENTS.get(s, s): self.states[s] for s in range(LED_COUNT)},
                "agent_status": agent_status,
                "selected_agent": AGENT_SLOTS.get(self.selected_agent),
                "last_keys": self.key_events[-8:],
                "feishu_status_monitor": self.feishu_status_listener.health()
                if hasattr(self, "feishu_status_listener") else {"enabled": False}}

    def doctor(self):
        """Read-only diagnosis of each local link in the Agentpad chain."""
        now = time.time()
        stale_agents = [SLOT_AGENTS[slot] for slot in AGENT_SLOTS
                        if self.state_meta[slot]["updated_at"] and
                        now - self.state_meta[slot]["updated_at"] > STATE_STALE_S]
        command_check = {"configured": bool(self.cfg.get("command_forward_url")),
                         "ok": False}
        endpoint = self.cfg.get("command_forward_url") or ""
        if endpoint:
            try:
                from urllib.parse import urlsplit, urlunsplit
                import urllib.request
                parsed = urlsplit(endpoint)
                health_url = urlunsplit((parsed.scheme, parsed.netloc, "/health", "", ""))
                with urllib.request.urlopen(health_url, timeout=0.8) as response:
                    payload = json.loads(response.read().decode() or "{}")
                command_check.update({"ok": bool(payload.get("ok")),
                                      "endpoint": health_url,
                                      "service": payload.get("service")})
            except Exception as exc:
                command_check.update({"endpoint": endpoint, "error": str(exc)[:180]})
        feishu = (self.feishu_status_listener.health()
                  if hasattr(self, "feishu_status_listener") else {"enabled": False})
        return {
            "ok": self.online and command_check["ok"],
            "generated_at": int(now),
            "keyboard": {"online": self.online, "mock": self.link.mock,
                         "raw_hid_handle_open": bool(self.link.dev) if not self.link.mock else True,
                         "vid_pid": f"{VID:04X}:{PID:04X}", "protocol": PROTO_VER},
            "command_adapter": command_check,
            "feishu_status_listener": feishu,
            "states": {"stale_agents": stale_agents,
                       "selected_agent": AGENT_SLOTS.get(self.selected_agent),
                       "thinking_timeout_s": self.cfg.get("thinking_timeout_s"),
                       "terminal_state_timeout_s": self.cfg.get("terminal_state_timeout_s")},
            "profile": safe_panel_profile(self.cfg),
            "warnings": self.profile_warnings,
            "next_steps": (["键盘未在线：插回已刷 Agentpad 固件的 12E4，daemon 会自动重连"]
                           if not self.online else []) +
                          (["命令适配器未就绪：检查 agentpad-commandd 服务"]
                           if not command_check["ok"] else []),
        }

    def set_agent_state(self, agent, state, task_id=None, source=None):
        slot = next((s for s, name in AGENT_SLOTS.items() if name == agent), -1)
        if slot < 0:
            return
        result = self.set_state(slot, state, task_id=task_id, source=source)
        log(f"✦ 飞书状态 {agent} -> {state} ({result})")

    def observe_feishu_local(self):
        """Read the local Feishu accessibility tree and update only visible hints."""
        helper = os.path.join(HERE, "feishu_local_observer.py")
        while not self._stop.is_set():
            try:
                proc = subprocess.run([sys.executable, helper], capture_output=True,
                                      text=True, timeout=7)
                hint = json.loads(proc.stdout or "{}")
                if hint.get("ok") and hint.get("agent") and hint.get("state"):
                    slot = next((s for s, name in AGENT_SLOTS.items() if name == hint["agent"]), -1)
                    if slot >= 0 and self.states[slot] != hint["state"]:
                        result = self.set_state(slot, hint["state"], source="local-feishu-ui")
                        log(f"👁 本机飞书 {hint['agent']} -> {hint['state']} ({result})")
                elif not hint.get("ok"):
                    log(f"⚠️ 本机飞书状态采集未返回: {hint.get('err', 'unknown error')}")
            except Exception as exc:
                log(f"⚠️ 本机飞书状态采集失败: {exc}")
            self._stop.wait(4.0)


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

def make_handler(daemon: Daemon):
    token = daemon.cfg.get("token") or ""

    class H(BaseHTTPRequestHandler):
        def _json(self, code, obj):
            body = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _authed(self) -> bool:
            return not token or self.headers.get("X-Agentpad-Token", "") == token

        def _body(self, raw=None) -> dict:
            if raw is None:
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n) if n else b""
            if not raw:
                return {}
            try:
                return json.loads(raw.decode() or "{}")
            except (ValueError, UnicodeDecodeError):
                return {}

        def do_GET(self):
            if self.path == "/health":
                self._json(200, daemon.health())
            elif self.path == "/doctor":
                self._json(200, daemon.doctor())
            elif self.path == "/profile":
                self._json(200, {"ok": True, "profile": safe_panel_profile(daemon.cfg),
                                 "warnings": daemon.profile_warnings})
            else:
                self._json(404, {"ok": False, "err": "not found"})

        def do_POST(self):
            raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            if not self._authed():
                self._json(401, {"ok": False, "err": "bad token"})
                return
            body = self._body(raw)
            if self.path == "/state":
                slot = daemon.resolve_slot(body)
                state = str(body.get("state", ""))
                if slot < 0:
                    self._json(400, {"ok": False, "err": "unknown agent/slot",
                                     "agents": list(AGENT_SLOTS.values())})
                else:
                    msg = daemon.set_state(slot, state, body.get("task_id"),
                                           body.get("updated_at"), body.get("source"))
                    self._json(200 if "->" in msg else 400, {"ok": "->" in msg, "msg": msg})
            elif self.path == "/state/all":
                for s in range(LED_COUNT):
                    daemon.set_state(s, str(body.get("state", "off")), body.get("task_id"),
                                     body.get("updated_at"), body.get("source"))
                self._json(200, {"ok": True, "msg": "all slots updated"})
            elif self.path == "/brightness":
                daemon.link.send(set_brightness(int(body.get("value", 160))))
                self._json(200, {"ok": True})
            elif self.path == "/clear":
                daemon.link.send(clear_all())
                for s in range(LED_COUNT):
                    daemon.states[s] = FUNCTION_ONLINE_STATE
                    daemon.state_meta[s] = {"updated_at": time.time(), "task_id": None,
                                            "source": "client-online" if s in FUNCTION_SLOTS else "local-agentpad-ready"}
                    rgb, mode = STATE_COLORS[daemon.states[s]]
                    if s in AGENT_SLOTS:
                        mode = 2
                    daemon.link.send(set_slot(s, rgb))
                    daemon.link.send(set_mode(s, mode))
                self._json(200, {"ok": True})
            elif self.path == "/ping":
                daemon._echo = (daemon._echo + 1) & 0xFF or 1
                daemon.link.send(ping(daemon._echo))
                t0, got = time.time(), None
                while time.time() - t0 < 2 and got is None:
                    got = daemon.link.read(100)
                self._json(200, {"ok": bool(got), "pong": got,
                                 "rtt_ms": int((time.time() - t0) * 1000)})
            else:
                self._json(404, {"ok": False, "err": "not found"})

        def log_message(self, *a):  # 安静: 只留业务日志
            pass

    return H


# --------------------------------------------------------------------------
# selftest: 找键盘 → PING → 每键彩扫 → 恢复
# --------------------------------------------------------------------------

def selftest(link: KeyboardLink) -> int:
    log("① 找 raw HID 接口 (5754:C401 usage FF60:61)...")
    if not link.open():
        log("❌ 没找到. 键盘插了吗? 刷机成功了吗? (跑 verify/check-enumeration.py 看枚举)")
        return 1
    log("✅ 接口已打开")
    log("② PING/PONG...")
    link.send(ping(0x5A))
    got, t0 = None, time.time()
    while time.time() - t0 < 2 and got is None:
        got = link.read(100)
    if not (got and got["t"] == "pong"):
        log(f"❌ 无 PONG: {got}")
        return 1
    log(f"✅ PONG proto=v{got['proto']} leds={got['led_count']}")
    log("③ 彩灯扫描 (每键 红→绿→蓝, 共 12 键)...")
    link.send(set_brightness(200))
    for slot in range(LED_COUNT):
        for rgb in ((255, 0, 0), (0, 255, 0), (0, 80, 255)):
            link.send(set_slot(slot, rgb))
            time.sleep(0.12)
        link.send(set_slot(slot, (0, 0, 0)))
    log("④ 恢复全灭...")
    link.send(clear_all())
    link.close()
    log("🎉 selftest 全过 — 键盘通信与灯控正常, 可以启动 daemon 了")
    return 0


# --------------------------------------------------------------------------

def load_config() -> dict:
    p = os.path.join(HERE, "config.json")
    if not os.path.exists(p):
        with open(p, "w") as f:
            json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=1)
        log(f"已生成默认配置 {p}")
    cfg = dict(DEFAULT_CONFIG)
    try:
        cfg.update(json.load(open(p)))
    except (OSError, ValueError) as e:
        log(f"⚠️ config.json 读不了 ({e}), 用默认")
    return cfg


def main():
    ap = argparse.ArgumentParser(description="agentpad-client daemon")
    ap.add_argument("--mock", action="store_true", help="虚拟键盘 (无硬件演示)")
    ap.add_argument("--selftest", action="store_true", help="通信+灯控自检后退出")
    ap.add_argument("--port", type=int, help="覆盖 config 端口")
    args = ap.parse_args()

    link = KeyboardLink(mock=args.mock)
    if args.selftest:
        sys.exit(selftest(link))

    cfg = load_config()
    if args.port:
        cfg["port"] = args.port
    profile_warnings = apply_panel_profile(cfg)
    for warning in profile_warnings:
        log(f"⚠️ 配置档: {warning}")
    d = Daemon(link, cfg)
    d.profile_warnings = profile_warnings
    from feishu_status_listener import FeishuStatusListener
    d.feishu_status_listener = FeishuStatusListener(cfg, d.set_agent_state, log)
    if not link.open():
        log("⚠️ 键盘暂不在线 — daemon 照常启动并监听 HTTP, 键盘插上后自动接管")
    else:
        log("✅ 键盘已连接")
        d.online = True
    d.boot_paint()

    threading.Thread(target=d.heartbeat, daemon=True).start()
    if cfg.get("feishu_local_observer"):
        threading.Thread(target=d.observe_feishu_local, daemon=True).start()
    d.feishu_status_listener.start()
    bind = cfg.get("bind", "0.0.0.0")
    port = int(cfg.get("port", 8124))
    httpd = ThreadingHTTPServer((bind, port), make_handler(d))
    lan_ip = ""
    try:
        import socket as _s
        _tmp = _s.socket(_s.AF_INET, _s.SOCK_DGRAM)
        _tmp.connect(("10.255.255.255", 1))
        lan_ip = _tmp.getsockname()[0]
        _tmp.close()
    except OSError:
        pass
    log(f"🚀 agentpad-client 已监听 http://{lan_ip}:{port}  (health: /health)")
    log("   推状态: curl -X POST http://%s:%d/state -d '{\"agent\":\"tanchun\",\"state\":\"thinking\"}'" % (lan_ip, port))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    d._stop.set()
    link.close()
    log("stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
