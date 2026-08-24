#!/usr/bin/env python3
"""Claude Code lifecycle hook for Agentpad.

The hook intentionally discards Claude's stdin event payload.  It relays only
the requested light state to the local Agentpad HTTP service: no prompt,
tool-call arguments, response text, or project path is stored or transmitted.
"""

import argparse
import json
import sys
import urllib.request


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("state", choices=("thinking", "complete", "needs_input", "error"))
    args = ap.parse_args()
    # Consume and discard the event JSON so this works with every Claude hook.
    sys.stdin.read()
    payload = json.dumps({"agent": "claude-vscode", "state": args.state,
                          "source": "claude-code-hook"}).encode()
    request = urllib.request.Request("http://127.0.0.1:8124/state", data=payload,
                                     headers={"Content-Type": "application/json"},
                                     method="POST")
    try:
        with urllib.request.urlopen(request, timeout=1):
            pass
    except Exception:
        # Hooks must not change Claude's own execution outcome.
        pass


if __name__ == "__main__":
    main()
