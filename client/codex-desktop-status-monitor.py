#!/usr/bin/env python3
"""Drive Agentpad's Codex LED from local Codex Desktop turn state.

Only lifecycle metadata is read. Prompts, responses, and tool arguments are
never inspected.
"""

import json
import os
import re
import sqlite3
import time
import urllib.request


CODEX_HOME = os.path.expanduser("~/.codex")
TURN_DB = os.path.join(CODEX_HOME, "thread_history_1.sqlite")
LOG_DB = os.path.join(CODEX_HOME, "logs_2.sqlite")
AGENTPAD_STATE_URL = "http://127.0.0.1:8124/state"
POLL_SECONDS = 0.5
THINKING_HEARTBEAT_SECONDS = 45.0
# Ignore abandoned inProgress rows left by a much older Codex build or crash.
# A live owner process is still required, so this is only a broad safety cap.
MAX_TURN_AGE_SECONDS = 7 * 24 * 60 * 60
PID_PATTERN = re.compile(r"(?:^|:)pid:(\d+)(?::|$)")


def publish(state, task_id=None):
    payload = {
        "agent": "codex",
        "state": state,
        "source": "codex-desktop-turn-monitor",
    }
    if task_id:
        payload["task_id"] = task_id
    request = urllib.request.Request(
        AGENTPAD_STATE_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=1):
            pass
    except OSError:
        # Agentpad may be restarting or the keyboard may be unplugged.
        pass


def connect(path):
    return sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=1)


def process_is_alive(process_uuid):
    if not process_uuid:
        return False
    match = PID_PATTERN.search(process_uuid)
    if not match:
        return False
    try:
        os.kill(int(match.group(1)), 0)
        return True
    except PermissionError:
        # Sandboxed Codex processes may be visible but not signalable.
        return True
    except (OSError, ValueError):
        return False


def active_turns(turn_connection, log_connection):
    cutoff = int(time.time()) - MAX_TURN_AGE_SECONDS
    rows = turn_connection.execute(
        "SELECT thread_id, turn_id, started_at FROM thread_turns "
        "WHERE status = 'inProgress' AND started_at >= ? "
        "ORDER BY started_at DESC",
        (cutoff,),
    ).fetchall()

    active = []
    for thread_id, turn_id, started_at in rows:
        owner = log_connection.execute(
            "SELECT process_uuid FROM logs "
            "WHERE thread_id = ? AND process_uuid IS NOT NULL "
            "ORDER BY id DESC LIMIT 1",
            (thread_id,),
        ).fetchone()
        if owner and process_is_alive(owner[0]):
            active.append((thread_id, turn_id, started_at))
    return active


def main():
    turn_connection = None
    log_connection = None
    current_state = None
    active_signature = ()
    last_task_id = None
    last_publish = 0.0

    while True:
        try:
            if turn_connection is None:
                turn_connection = connect(TURN_DB)
            if log_connection is None:
                log_connection = connect(LOG_DB)

            active = active_turns(turn_connection, log_connection)
            signature = tuple(sorted(turn_id for _, turn_id, _ in active))
            now = time.monotonic()

            if active:
                newest_task_id = active[0][1]
                if current_state != "thinking" or signature != active_signature:
                    publish("thinking", newest_task_id)
                    current_state = "thinking"
                    active_signature = signature
                    last_task_id = newest_task_id
                    last_publish = now
                elif now - last_publish >= THINKING_HEARTBEAT_SECONDS:
                    publish("thinking", newest_task_id)
                    last_publish = now
            elif current_state == "thinking":
                publish("complete", last_task_id)
                current_state = "complete"
                active_signature = ()
                last_publish = now
            elif current_state is None:
                # Clear stale status left behind if the monitor was not running.
                publish("idle")
                current_state = "idle"
                last_publish = now
        except sqlite3.Error:
            if turn_connection is not None:
                turn_connection.close()
            if log_connection is not None:
                log_connection.close()
            turn_connection = None
            log_connection = None
            time.sleep(2)
            continue

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
