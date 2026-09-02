#!/usr/bin/env python3
"""Send Codex lifecycle state to the loopback-only Agentpad service.

The hook receives JSON from Codex on standard input.  It intentionally reads
only identifiers (never the user's prompt or the transcript) and posts the
selected state supplied on the command line.
"""

import json
import sys
import urllib.error
import urllib.request


def main() -> None:
    state = sys.argv[1]
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        event = {}

    body = {
        "agent": "codex",
        "state": state,
        "source": "codex-desktop-hook",
    }
    task_id = event.get("turn_id") or event.get("session_id")
    if task_id:
        body["task_id"] = str(task_id)

    request = urllib.request.Request(
        "http://127.0.0.1:8124/state",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=1):
            pass
    except (OSError, urllib.error.URLError):
        # A temporary unavailable keypad/client must never block Codex.
        pass

    print(json.dumps({"continue": True}))


if __name__ == "__main__":
    main()
