#!/usr/bin/env python3
"""Read locally visible Feishu UI signals for Agentpad; never sends messages."""

import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
HELPER = os.path.join(HERE, "feishu-local-ocr")
FALLBACK_HELPER = os.path.join(HERE, "feishu-local-snapshot")
RECIPIENTS = {
    "探春": "tanchun", "黛玉": "daiyu", "湘云": "xiangyun", "香菱": "xiangling",
    "宝钗": "baochai", "莺儿": "yinger",
}


def snapshot():
    # The local Accessibility snapshot avoids launching the screen-capture
    # helper from the background service when it is already available.
    helpers = [path for path in (FALLBACK_HELPER, HELPER) if os.path.exists(path)]
    if not helpers:
        return {"ok": False, "err": "local Feishu helper not built"}
    errors = []
    for helper in helpers:
        try:
            output = subprocess.run([helper], capture_output=True, text=True, timeout=8)
            parsed = json.loads(output.stdout or "{}")
            if not output.returncode and parsed.get("ok"):
                return parsed
            errors.append(parsed.get("err") or output.stderr.strip() or "snapshot failed")
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            errors.append(str(exc))
    return {"ok": False, "err": "; ".join(errors)}


def infer_status(data):
    text = data.get("text", "")
    # The composer reliably identifies the current chat (for example
    # "发送给 宝钗Hermes"). Prefer it over transcript mentions: agents often
    # discuss one another, which otherwise causes an unrelated LED to change.
    recipient = next((name for name in RECIPIENTS
                      if re.search(r"发送给\\s*" + re.escape(name), text)), None)
    if not recipient:
        # OCR sees the active conversation header even when the compose-field
        # placeholder is not visible. The header normally occurs before the
        # transcript; use this only as a local visible hint.
        recipient = next((name for name in RECIPIENTS if name in text), None)
    if not recipient:
        return {"ok": True, "agent": None, "state": None, "reason": "no active agent chat"}
    # Focus on the most recently exposed controls/content. Older transcript text
    # should not keep a keyboard LED in a stale state forever.
    tail = text[-2200:].lower()
    if "[generating" in tail or "生成中" in tail:
        state, reason = "thinking", "local Feishu shows generating"
    elif "/approve" in tail or "批准" in tail or "继续" in tail:
        state, reason = "needs_input", "local Feishu shows an action control"
    elif any(word in tail for word in ("error", "失败", "异常", "429")):
        state, reason = "error", "local Feishu shows error signal"
    else:
        state, reason = "idle", "active Feishu conversation"
    return {"ok": True, "agent": RECIPIENTS[recipient], "state": state, "reason": reason}


if __name__ == "__main__":
    result = snapshot()
    print(json.dumps(infer_status(result) if result.get("ok") else result, ensure_ascii=False))
