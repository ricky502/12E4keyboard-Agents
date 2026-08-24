#!/usr/bin/env python3
"""agentpad-commandd — local command adapter for the Agentpad keyboard.

This service deliberately separates HID handling from Agent-specific actions.
It opens local apps/Feishu chats directly, while command execution is disabled
unless an explicit, local command template is configured.
"""

import argparse
import ctypes
import json
import os
import shlex
import subprocess
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    from codex_appserver import CodexAppServer
except ImportError:
    CodexAppServer = None

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_CONFIG = {
    "bind": "127.0.0.1",
    "port": 8125,
    "token": "",
    "targets": {
        "tanchun": {"kind": "feishu", "app_id": "cli_aad5ad30b7b95bfb"},
        "daiyu": {"kind": "feishu", "app_id": "cli_a90727456ff9dcd3"},
        "xiangyun": {"kind": "feishu", "app_id": "cli_a914dfbd52785cc2"},
        "xiangling": {"kind": "feishu", "app_id": "cli_aafd607dfd78dcd8"},
        "baochai": {"kind": "feishu", "app_id": "cli_a935e72632f85cc6"},
        "yinger": {"kind": "feishu", "app_id": "cli_a9633fc1823cdcdd"},
        # The local Codex desktop client is packaged as ChatGPT on this Mac.
        # Launch the actual application rather than relying on a deep link
        # which macOS can accept without foregrounding a window.
        "codex": {"kind": "local", "app": "ChatGPT"},
        "claude-vscode": {"kind": "local", "app": "Visual Studio Code"},
    },
    "commands": {},
}

def publish_local_agent_state(state, task_id=None, source=None):
    """Send only local lifecycle metadata to the LED daemon."""
    body = {"agent": "codex", "state": state, "source": source or "codex-app-server"}
    if task_id:
        body["task_id"] = task_id
    try:
        request = urllib.request.Request(
            "http://127.0.0.1:8124/state", data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=1):
            pass
    except Exception:
        pass


CODEX = (CodexAppServer(codex_bin="/Users/ricky/.npm-global/bin/codex",
                        on_state=publish_local_agent_state)
         if CodexAppServer else None)


def load_config(path):
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            loaded = json.load(f)
        for key, value in loaded.items():
            if isinstance(value, dict) and isinstance(cfg.get(key), dict):
                cfg[key].update(value)
            else:
                cfg[key] = value
    return cfg


def open_target(target):
    kind = target.get("kind")
    if kind == "uri" and target.get("uri"):
        return open_uri(target["uri"])
    if kind == "feishu" and target.get("app_id"):
        # Official Feishu AppLink: cli_ IDs identify bots, whereas the old
        # oc_ chat IDs do not reliably navigate the desktop client.
        uri = "lark://applink.feishu.cn/client/bot/open?appId=" + target["app_id"]
        subprocess.Popen(["open", uri], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
        return {"ok": True, "opened": uri}
    if kind == "feishu" and target.get("chat_id"):
        uri = "feishu://client/chat/open?chatId=" + target["chat_id"]
        subprocess.Popen(["open", uri], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
        return {"ok": True, "opened": uri}
    if kind == "local" and target.get("app"):
        subprocess.Popen(["open", "-a", target["app"]], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
        return {"ok": True, "opened_app": target["app"]}
    if kind == "collection":
        return {"ok": False, "err": "yinger has no chat window; collection adapter pending"}
    return {"ok": False, "err": "target has no open action"}


def open_uri(uri):
    subprocess.Popen(["open", uri], stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL)
    return {"ok": True, "opened": uri}


def local_zoom(clockwise):
    """Send Command + / - to the frontmost local app."""
    key_code = "24" if clockwise else "27"  # =/+ and - on a US Mac layout
    return run_local_applescript(
        f'tell application "System Events" to key code {key_code} using command down',
        "zoom_in" if clockwise else "zoom_out")


def local_play_pause():
    """Send the Mac's F8/media play-pause key to the frontmost system target."""
    return run_local_applescript(
        'tell application "System Events" to key code 100', "play_pause")


def local_volume(clockwise):
    direction = "+ 5" if clockwise else "- 5"
    return run_local_applescript(
        f'set volume output volume ((output volume of (get volume settings)) {direction})',
        "volume_up" if clockwise else "volume_down")


def run_local_applescript(script, action):
    try:
        proc = subprocess.run(["osascript", "-e", script], capture_output=True,
                              text=True, timeout=5)
        return {"ok": proc.returncode == 0, "action": action,
                "stdout": proc.stdout[-500:], "stderr": proc.stderr[-500:]}
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"ok": False, "action": action, "err": str(e)}


def run_backup_bottom_hotkey(action, pressed):
    """Replay the two left bottom-row keys from the owner's VIA backup.

    The physical voice key is Option and must preserve press/release state;
    the approval key is Return. Quartz avoids a background osascript waiting
    on an Automation consent dialog.
    """
    mappings = {"talk": 58, "approve": 36}  # macOS Option, Return
    key_code = mappings[action]
    try:
        quartz = ctypes.CDLL("/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
        quartz.CGEventCreateKeyboardEvent.argtypes = [ctypes.c_void_p, ctypes.c_ushort, ctypes.c_bool]
        quartz.CGEventCreateKeyboardEvent.restype = ctypes.c_void_p
        quartz.CGEventSetFlags.argtypes = [ctypes.c_void_p, ctypes.c_ulonglong]
        quartz.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
        cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        cf.CFRelease.argtypes = [ctypes.c_void_p]
        event = quartz.CGEventCreateKeyboardEvent(None, key_code, bool(pressed))
        if not event:
            raise RuntimeError("could not create keyboard event")
        quartz.CGEventPost(0, event)  # kCGHIDEventTap
        cf.CFRelease(event)
        return {"ok": True, "action": "backup_" + action, "pressed": bool(pressed)}
    except OSError as exc:
        return {"ok": False, "action": "backup_" + action, "err": str(exc)}


def run_codex_command_key(action):
    """Send one-shot Codex command keys to the currently focused app."""
    try:
        quartz = ctypes.CDLL("/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
        quartz.CGEventCreateKeyboardEvent.argtypes = [ctypes.c_void_p, ctypes.c_ushort, ctypes.c_bool]
        quartz.CGEventCreateKeyboardEvent.restype = ctypes.c_void_p
        quartz.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
        quartz.CGEventKeyboardSetUnicodeString.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ushort)]
        cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        cf.CFRelease.argtypes = [ctypes.c_void_p]
        if action == "new_task":
            # Inject text as Unicode, not physical key codes: Chinese IMEs map
            # the physical slash key to 、, while Unicode reliably yields /new.
            text = "/new"
            chars = (ctypes.c_ushort * len(text))(*(ord(ch) for ch in text))
            event = quartz.CGEventCreateKeyboardEvent(None, 0, True)
            if not event:
                raise RuntimeError("could not create Unicode keyboard event")
            quartz.CGEventKeyboardSetUnicodeString(event, len(text), chars)
            quartz.CGEventPost(0, event)
            cf.CFRelease(event)
            time.sleep(0.08)
            sequence = [36]  # Return, sent only after /new has arrived.
        else:
            sequence = [53]  # Escape = Codex decline/cancel.
        for key_code in sequence:
            for pressed in (True, False):
                event = quartz.CGEventCreateKeyboardEvent(None, key_code, pressed)
                if not event:
                    raise RuntimeError("could not create keyboard event")
                quartz.CGEventPost(0, event)
                cf.CFRelease(event)
        return {"ok": True, "action": action}
    except OSError as exc:
        return {"ok": False, "action": action, "err": str(exc)}


def run_configured_command(cfg, action, agent, body):
    template = cfg.get("commands", {}).get(action)
    if not template:
        return {"ok": False, "err": "command not configured", "action": action,
                "agent": agent}
    values = {"agent": agent or "", "action": action,
              "clockwise": str(bool(body.get("clockwise"))).lower()}
    try:
        if isinstance(template, str):
            argv = shlex.split(template.format(**values))
        elif isinstance(template, list) and all(isinstance(x, str) for x in template):
            argv = [x.format(**values) for x in template]
        else:
            return {"ok": False, "err": "command template must be string or argv list"}
        # Templates are explicit local configuration, but never invoke a shell.
        proc = subprocess.run(argv, capture_output=True,
                              text=True, timeout=15)
        return {"ok": proc.returncode == 0, "returncode": proc.returncode,
                "stdout": proc.stdout[-2000:], "stderr": proc.stderr[-2000:]}
    except KeyError as e:
        return {"ok": False, "err": "unknown template field", "field": str(e)}
    except (OSError, ValueError, subprocess.TimeoutExpired) as e:
        return {"ok": False, "err": str(e)}


def dispatch(cfg, body):
    action = str(body.get("action", ""))
    agent = str(body.get("agent", "")) or None
    if action == "select_agent":
        target = cfg.get("targets", {}).get(agent)
        if not target:
            return {"ok": False, "err": "unknown agent", "agent": agent}
        if agent == "claude-vscode":
            # Opening VS Code itself is stable across Claude extension
            # versions. Extension command IDs are intentionally not used for
            # selection because they change between releases.
            return open_target(target)
        return open_target(target)
    if action == "talk":
        return run_backup_bottom_hotkey("talk", body.get("pressed", True))
    if action == "approve":
        return run_backup_bottom_hotkey("approve", body.get("pressed", True))
    if action in {"reject", "new_task"}:
        return run_codex_command_key(action)
    target = cfg.get("targets", {}).get(agent, {})
    if target.get("kind") == "feishu" and action in {"new_task", "approve", "reject"}:
        # Keep every remote-Agent interaction visibly local in Feishu.  The
        # keyboard never sends hidden messages or calls the Mac Mini.
        result = open_target(target)
        result.update({"action": action, "requires_visible_feishu_action": True})
        return result
    if agent == "claude-vscode":
        # These commands are provided by the installed Claude Code VSCode
        # extension. VSCode decides whether an accept/reject is currently
        # applicable; the keyboard client separately gates both actions on
        # `needs_input` state before they reach this adapter.
        claude_commands = {
            "new_task": "claude-vscode.newConversation",
            "approve": "claude-vscode.acceptProposedDiff",
            "reject": "claude-vscode.rejectProposedDiff",
        }
        if action in claude_commands:
            return open_uri("vscode://command/" + claude_commands[action])
    if action == "encoder":
        enc = int(body.get("source", -1))
        clockwise = bool(body.get("clockwise"))
        # The CXT 12E4 reports physical dials left-to-right as 2, 3, 1, 0.
        # Owner-confirmed layout: model, effort, volume, zoom.
        if enc == 2:
            if agent == "codex" and CODEX:
                return CODEX.cycle_model(clockwise)
            action = "model_next" if clockwise else "model_prev"
            return run_configured_command(cfg, action, agent, body)
        if enc == 3:
            if agent == "codex" and CODEX:
                return CODEX.adjust_effort(clockwise)
            action = "effort_up" if clockwise else "effort_down"
            return run_configured_command(cfg, action, agent, body)
        if enc == 1:
            return local_volume(clockwise)
        if enc == 0:
            return local_zoom(clockwise)
        return {"ok": False, "err": "unknown encoder", "encoder": enc}
    return run_configured_command(cfg, action, agent, body)


def make_handler(cfg):
    token = cfg.get("token") or ""

    class Handler(BaseHTTPRequestHandler):
        def reply(self, code, obj):
            raw = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def authorized(self):
            return not token or self.headers.get("X-Agentpad-Token", "") == token

        def do_GET(self):
            if self.path == "/health":
                self.reply(200, {"ok": True, "service": "agentpad-commandd",
                                 "time": int(time.time())})
            else:
                self.reply(404, {"ok": False, "err": "not found"})

        def do_POST(self):
            if not self.authorized():
                self.reply(401, {"ok": False, "err": "bad token"})
                return
            try:
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n).decode() or "{}")
                result = dispatch(cfg, body)
                self.reply(200 if result.get("ok") else 409, result)
            except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as e:
                self.reply(400, {"ok": False, "err": str(e)})
            except Exception as e:
                # A local integration failure must not tear down the HTTP
                # response; the keyboard client can then report the error
                # cleanly and keep processing later controls.
                self.reply(500, {"ok": False, "err": str(e)})

        def log_message(self, *_):
            pass

    return Handler


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.path.join(HERE, "command-config.json"))
    ap.add_argument("--bind")
    ap.add_argument("--port", type=int)
    args = ap.parse_args()
    cfg = load_config(args.config)
    if args.bind:
        cfg["bind"] = args.bind
    if args.port:
        cfg["port"] = args.port
    server = ThreadingHTTPServer((cfg["bind"], int(cfg["port"])), make_handler(cfg))
    print(f"agentpad-commandd listening on {cfg['bind']}:{cfg['port']}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
