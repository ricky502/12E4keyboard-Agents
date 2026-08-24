#!/usr/bin/env python3
"""Small JSON-RPC client for the local Codex app-server protocol.

It manages a dedicated Agentpad Codex thread. It does not start a turn on its
own and therefore cannot execute work until the command adapter asks it to.
"""

import json
import os
import queue
import subprocess
import threading
import uuid


class CodexAppServer:
    def __init__(self, codex_bin="codex", cwd=None, model=None, effort=None,
                 on_state=None):
        self.codex_bin = codex_bin
        self.cwd = cwd or os.getcwd()
        self.model = model
        self.effort = effort
        self.proc = None
        self.thread_id = None
        self.turn_id = None
        self.models = []
        self._next_id = 1
        self._responses = queue.Queue()
        self._reader = None
        self.on_state = on_state

    def start(self):
        if self.proc and self.proc.poll() is None:
            return
        # launchd deliberately starts Agentpad with a minimal PATH. The Codex
        # npm entry point uses `#!/usr/bin/env node`, so expose the locally
        # installed Node runtime explicitly when this is a background service.
        env = os.environ.copy()
        node_dirs = ["/opt/homebrew/bin", "/usr/local/bin"]
        path_entries = env.get("PATH", "").split(":")
        env["PATH"] = ":".join([p for p in node_dirs if p not in path_entries] + path_entries)
        self.proc = subprocess.Popen(
            [self.codex_bin, "app-server", "--stdio"],
            cwd=self.cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, bufsize=1, env=env)
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        # Current Codex app-server requires the client capability object in
        # the initialize handshake, even when Agentpad opts into no optional
        # capabilities. Without it the server can drop the connection before
        # replying, leaving the model dial unresponsive.
        try:
            self.call("initialize", {"clientInfo": {
                "name": "agentpad", "title": "Agentpad", "version": "0.1"
            }, "capabilities": {}})
        except Exception as exc:
            self.close()
            raise RuntimeError(f"Codex app-server initialization failed: {exc}") from exc
        self.notify("initialized", {})

    def _read_loop(self):
        for line in self.proc.stdout:
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            # App-server notifications carry the actual turn lifecycle.  Keep
            # them outside the RPC response queue so a notification can never
            # be mistaken for a response or make a dial operation time out.
            if message.get("method") and "id" not in message:
                self._publish_turn_state(message)
            else:
                self._responses.put(message)

    def _publish_turn_state(self, message):
        if not self.on_state:
            return
        method = str(message.get("method", ""))
        params = message.get("params") or {}
        state = None
        if method in {"turn/started", "turn/start", "turn/updated"}:
            state = "thinking"
        elif method in {"turn/completed", "turn/complete"}:
            state = "complete"
        elif method in {"turn/failed", "turn/error", "turn/errored"}:
            state = "error"
        elif method in {"turn/interrupted", "turn/cancelled"}:
            state = "idle"
        if state:
            turn = params.get("turn") if isinstance(params, dict) else {}
            task_id = (turn or {}).get("id") if isinstance(turn, dict) else None
            try:
                self.on_state(state, task_id=task_id, source="codex-app-server")
            except Exception:
                # Status reporting must never interrupt a real Codex turn.
                pass

    def notify(self, method, params):
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def call(self, method, params, timeout=20):
        request_id = self._next_id
        self._next_id += 1
        self._send({"jsonrpc": "2.0", "id": request_id,
                    "method": method, "params": params})
        deferred = []
        while True:
            msg = self._responses.get(timeout=timeout)
            if msg.get("id") == request_id:
                if "error" in msg:
                    raise RuntimeError(msg["error"])
                return msg.get("result")
            deferred.append(msg)
        # Notifications are intentionally consumed here; a production bridge
        # will publish them to the Agentpad state pipeline.

    def _send(self, msg):
        if not self.proc or self.proc.poll() is not None:
            raise RuntimeError("Codex app-server is not running")
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()

    def ensure_thread(self):
        self.start()
        if not self.thread_id:
            params = {"cwd": self.cwd, "ephemeral": False}
            if self.model:
                params["model"] = self.model
            if self.effort:
                params["reasoningEffort"] = self.effort
            result = self.call("thread/start", params)
            self.thread_id = result.get("thread", {}).get("id")
        return self.thread_id

    def send_text(self, text):
        thread_id = self.ensure_thread()
        if self.on_state:
            self.on_state("thinking", source="codex-app-server")
        params = {"threadId": thread_id,
                  "input": [{"type": "text", "text": text}],
                  "clientUserMessageId": str(uuid.uuid4())}
        if self.model:
            params["model"] = self.model
        if self.effort:
            params["effort"] = self.effort
        result = self.call("turn/start", params)
        self.turn_id = result.get("turn", {}).get("id")
        return result

    def interrupt(self):
        if self.thread_id and self.turn_id:
            return self.call("turn/interrupt", {
                "threadId": self.thread_id, "turnId": self.turn_id})
        return {"ok": False, "err": "no active Codex turn"}

    def list_models(self):
        self.start()
        result = self.call("model/list", {})
        self.models = result.get("data", []) if isinstance(result, dict) else []
        return result

    def set_model(self, model):
        self.model = model
        return {"ok": True, "model": model, "applies_on": "next_turn"}

    def adjust_effort(self, clockwise):
        levels = ["low", "medium", "high", "xhigh", "max", "ultra"]
        current = self.effort if self.effort in levels else "medium"
        index = levels.index(current)
        index = min(len(levels) - 1, index + 1) if clockwise else max(0, index - 1)
        self.effort = levels[index]
        return {"ok": True, "effort": self.effort, "applies_on": "next_turn"}

    def cycle_model(self, clockwise):
        if not self.models:
            self.list_models()
        usable = [m.get("model") or m.get("id") for m in self.models
                  if not m.get("hidden")]
        usable = [m for m in usable if m]
        if not usable:
            return {"ok": False, "err": "no models returned"}
        current = self.model if self.model in usable else usable[0]
        index = usable.index(current)
        index = (index + (1 if clockwise else -1)) % len(usable)
        return self.set_model(usable[index])

    def close(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
        self.proc = None
