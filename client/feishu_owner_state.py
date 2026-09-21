"""Aggregate Feishu task activity by agent and originating conversation owner."""

import time


ACTIVE_STATES = {"thinking", "needs_input"}


class OwnerState:
    def __init__(self, self_owners):
        self.self_owners = self_owners if isinstance(self_owners, dict) else {}
        self.tasks = {}
        self.last_terminal = {}
        self.last_order = {}
        self.dropped_stale = {}
        self.applied_seq = {}

    def update(self, agent, state, task_id, owner=None, chat=None, now=None,
               ts=None, seq=None):
        now = time.time() if now is None else now
        tasks = self.tasks.setdefault(agent, {})
        key = str(task_id) if task_id is not None else "legacy"
        previous = tasks.get(key)
        ordered = (isinstance(ts, int) and not isinstance(ts, bool) and
                   isinstance(seq, int) and not isinstance(seq, bool))
        if ordered:
            order_key = (agent, key)
            incoming = (seq, ts)
            prior = self.last_order.get(order_key)
            if prior is not None and incoming <= prior:
                self.dropped_stale[agent] = self.dropped_stale.get(agent, 0) + 1
                result = self.view(agent)
                result["_applied"] = False
                return result
            self.last_order[order_key] = incoming
            self.applied_seq[agent] = max(seq, self.applied_seq.get(agent, seq))
        # Legacy packets have no ordering proof, so retain the old protection
        # against a delayed active heartbeat reviving a terminal task.
        elif (key != "legacy" and previous and
              previous["state"] not in ACTIVE_STATES and state in ACTIVE_STATES):
            result = self.view(agent)
            result["_applied"] = False
            return result
        if previous and previous["owner"] and owner and previous["owner"] != owner:
            # The first authenticated owner of a task wins; never reassign it.
            owner = previous["owner"]
        tasks[key] = {
            "owner": owner or (previous or {}).get("owner"),
            "chat": chat or (previous or {}).get("chat"),
            "state": state,
            "updated_at": now,
        }
        if state not in ACTIVE_STATES:
            self.last_terminal[agent] = (state, key, now)
        result = self.view(agent)
        result["_applied"] = True
        return result

    def view(self, agent):
        active = [(key, task) for key, task in self.tasks.get(agent, {}).items()
                  if task["state"] in ACTIVE_STATES]
        owners = {task["owner"] for _, task in active if task["owner"]}
        self_owner = self.self_owners.get(agent) or ""
        own = bool(self_owner and self_owner in owners)
        other = bool(owners - {self_owner}) if self_owner else False
        unknown = any(not task["owner"] for _, task in active) or bool(owners and not self_owner)
        if active:
            if own and other:
                state = "thinking_shared"
            elif other and not unknown:
                state = "thinking_other"
            else:
                # An unmapped or ownerless task cannot prove who is working.
                state = "thinking"
            task_id = max(active, key=lambda item: item[1]["updated_at"])[0]
        else:
            terminal = self.last_terminal.get(agent)
            state = terminal[0] if terminal else "idle"
            task_id = terminal[1] if terminal else None
        return {"state": state, "task_id": task_id,
                "active_tasks": len(active), "self_active": own,
                "other_active": other, "unknown_active": unknown,
                "applied_seq": self.applied_seq.get(agent),
                "dropped_stale": self.dropped_stale.get(agent, 0)}

    def expire(self, now, active_ttl, terminal_ttl):
        changed = []
        for agent, tasks in self.tasks.items():
            before = self.view(agent)
            active_expired = False
            for key, task in list(tasks.items()):
                ttl = active_ttl if task["state"] in ACTIVE_STATES else terminal_ttl
                if now - task["updated_at"] >= ttl:
                    active_expired = active_expired or task["state"] in ACTIVE_STATES
                    del tasks[key]
            # A stale active task must fall back to idle, never resurrect an
            # older complete/error/idle snapshot.
            if active_expired and not any(
                    task["state"] in ACTIVE_STATES for task in tasks.values()):
                self.last_terminal.pop(agent, None)
            terminal = self.last_terminal.get(agent)
            if terminal and now - terminal[2] >= terminal_ttl:
                del self.last_terminal[agent]
            after = self.view(agent)
            if before != after:
                changed.append((agent, after))
        return changed
