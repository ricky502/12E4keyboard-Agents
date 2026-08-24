#!/usr/bin/env python3
"""Private Feishu status listener for Agentpad.

This is deliberately a *status* channel, not a chat archive. It accepts only
an exact, one-line marker from the configured status group, updates the local
keyboard state, and keeps neither the original message nor chat history.
"""

import asyncio
import json
import re
import subprocess
import threading
import time

VALID_AGENTS = {"tanchun", "daiyu", "xiangyun", "xiangling", "yinger", "codex", "claude-vscode", "baochai"}
VALID_STATES = {"idle", "thinking", "complete", "needs_input", "error", "off"}


def read_secret(service: str, account: str) -> str:
    """Read the app secret from the user's login keychain, never config.json."""
    try:
        result = subprocess.run(
            ["/usr/bin/security", "find-generic-password", "-s", service, "-a", account, "-w"],
            capture_output=True, text=True, timeout=5, check=False)
        return result.stdout.strip() if result.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def parse_status(text: str):
    """Accept only the documented marker and a small JSON object."""
    if not isinstance(text, str):
        return None
    # Feishu represents a structured @ mention in text events as an XML-like
    # prefix. It is delivery metadata, not part of the Agentpad marker.
    text = re.sub(r'^\s*<at\s+user_id="[^"]+"></at>\s*', "", text)
    # Feishu may vary the internal representation of the structured @ prefix.
    # Treat everything before the final status marker as transport metadata;
    # the complete trailing marker is still required.
    match = re.search(r"\[AGENTPAD\]\s*(\{.{1,1200}\})\s*$", text, flags=re.DOTALL)
    if not match:
        return None
    try:
        body = json.loads(match.group(1))
    except (TypeError, ValueError):
        return None
    if not isinstance(body, dict) or body.get("agent") not in VALID_AGENTS or body.get("state") not in VALID_STATES:
        return None
    task_id = body.get("task_id")
    if task_id is not None and not isinstance(task_id, (str, int, float)):
        return None
    return {"agent": body["agent"], "state": body["state"], "task_id": str(task_id) if task_id is not None else None}


class FeishuStatusListener:
    """Runs the official Feishu channel SDK in a background thread."""

    KEYCHAIN_SERVICE = "Agentpad Feishu Status Monitor"

    def __init__(self, cfg, on_status, log):
        self.cfg, self.on_status, self.log = cfg, on_status, log
        self.connected, self.last_event_at, self.last_error = False, 0.0, None

    def health(self):
        return {"enabled": bool(self.cfg.get("feishu_status_monitor")), "connected": self.connected,
                "last_event_at": self.last_event_at or None, "last_error": self.last_error}

    def start(self):
        if self.cfg.get("feishu_status_monitor"):
            threading.Thread(target=self._run, daemon=True, name="agentpad-feishu-status").start()

    def _run(self):
        app_id = str(self.cfg.get("feishu_status_app_id", "")).strip()
        if not app_id:
            self.last_error = "missing feishu_status_app_id"
            self.log("⚠️ 飞书状态监听未启用：缺少 App ID")
            return
        secret = read_secret(self.KEYCHAIN_SERVICE, app_id)
        if not secret:
            self.last_error = "missing keychain secret"
            self.log("⚠️ 飞书状态监听等待钥匙串中的 App Secret")
            return
        try:
            from lark_channel import FeishuChannel, InboundConfig
        except ImportError:
            self.last_error = "missing lark-channel-sdk"
            self.log("⚠️ 飞书状态监听缺少 lark-channel-sdk")
            return
        group_id = str(self.cfg.get("feishu_status_chat_id", "")).strip()

        async def listen():
            # Keep a metadata-only raw-event trace while commissioning. It
            # never logs message text; it distinguishes delivery problems
            # from Channel policy filtering for bot-to-bot group messages.
            channel = FeishuChannel(
                app_id=app_id, app_secret=secret,
                inbound=InboundConfig(emit_raw_events=True),
            )

            def field(obj, name, default=None):
                return obj.get(name, default) if isinstance(obj, dict) else getattr(obj, name, default)

            async def on_raw(data):
                event = field(data, "event")
                message = field(event, "message")
                chat_id = field(message, "chat_id", "")
                header = field(data, "header")
                self.log("↳ 飞书事件已到达", field(header, "event_type", "unknown"),
                         "group=" + str(chat_id or "(none)"))
                if not group_id or chat_id != group_id:
                    return
                content = field(message, "content", "")
                if isinstance(content, str):
                    try:
                        content = json.loads(content).get("text", "")
                    except ValueError:
                        return
                elif isinstance(content, dict):
                    content = content.get("text", "")
                else:
                    return
                status = parse_status(content)
                if not status:
                    return
                self.last_event_at = time.time()
                self.on_status(**status, source="feishu-status-group")

            async def on_message(msg):
                # The group ID is the privacy boundary. Direct messages and ordinary
                # chats are discarded before their contents are parsed.
                # Current SDK exposes ``chat_id`` directly; legacy versions
                # retain it under ``conversation``. Accept both shapes.
                chat_id = getattr(msg, "chat_id", "") or getattr(
                    getattr(msg, "conversation", None), "chat_id", "")
                if not group_id or chat_id != group_id:
                    return
                status = parse_status(getattr(msg, "content_text", ""))
                if not status:
                    return
                self.last_event_at = time.time()
                self.on_status(**status, source="feishu-status-group")

            channel.on("message", on_message)
            channel.on("raw", on_raw)
            self.connected, self.last_error = True, None
            self.log("✅ 飞书状态监听已通过本机出站长连接启动")
            await channel.connect()

        try:
            asyncio.run(listen())
        except Exception as exc:
            self.connected = False
            self.last_error = f"{type(exc).__name__}: {exc}"[:240]
            self.log("⚠️ 飞书状态监听断开:", self.last_error)
