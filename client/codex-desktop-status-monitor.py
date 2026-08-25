#!/usr/bin/env python3
"""Drive Agentpad's Codex LED from local Codex Desktop activity.

This monitor reads only record metadata from Codex's local log database.  It
never reads prompts, responses, tool arguments, or any feedback-log body.
"""

import json
import sqlite3
import time
import urllib.request


CODEX_LOG_DB = "/Users/ricky/.codex/logs_2.sqlite"
AGENTPAD_STATE_URL = "http://127.0.0.1:8124/state"
POLL_SECONDS = 0.75
QUIET_SECONDS = 6.0
ACTIVITY_TARGETS = (
    "codex_core::session::turn",
    "codex_core::stream_events_utils",
    "codex_core::tools::parallel",
    "codex_core::session::world_state",
)


def publish(state, task_id=None):
    payload = {
        "agent": "codex",
        "state": state,
        "source": "codex-desktop-log-monitor",
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


def connect():
    return sqlite3.connect(
        "file:%s?mode=ro" % CODEX_LOG_DB,
        uri=True,
        timeout=1,
    )


def newest_id(connection):
    return connection.execute("SELECT COALESCE(MAX(id), 0) FROM logs").fetchone()[0]


def activity_after(connection, last_id):
    placeholders = ",".join("?" for _ in ACTIVITY_TARGETS)
    query = (
        "SELECT id, thread_id FROM logs "
        "WHERE id > ? AND thread_id IS NOT NULL AND target IN (%s) "
        "ORDER BY id" % placeholders
    )
    return connection.execute(query, (last_id, *ACTIVITY_TARGETS)).fetchall()


def main():
    connection = None
    last_id = 0
    current_state = "idle"
    last_activity = 0.0
    active_thread = None
    publish("idle")  # clear any stale status left by an older integration.

    while True:
        try:
            if connection is None:
                connection = connect()
                # Establish a baseline: historical conversations are not active work.
                last_id = newest_id(connection)

            rows = activity_after(connection, last_id)
            if rows:
                last_id = rows[-1][0]
                active_thread = rows[-1][1]
                last_activity = time.monotonic()
                if current_state != "thinking":
                    publish("thinking", active_thread)
                    current_state = "thinking"

            if current_state == "thinking" and time.monotonic() - last_activity >= QUIET_SECONDS:
                publish("complete", active_thread)
                current_state = "complete"
        except sqlite3.Error:
            if connection is not None:
                connection.close()
            connection = None
            time.sleep(2)
            continue

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
