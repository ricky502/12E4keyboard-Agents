"""Aggregate Feishu task activity by agent and originating conversation owner."""

import time


ACTIVE_STATES = {"thinking", "needs_input"}


class OwnerState:
    def __init__(self, self_owner):
        self.self_owner = self_owner or ""
        self.tasks = {}
        self.last_terminal = {}

    def update(self, agent, state, task_id, owner=None, chat=None, now=None):
        now = time.time() if now is None else now
        tasks = self.tasks.setdefault(agent, {})
        key = str(task_id) if task_id is not None else "legacy"
        previous = tasks.get(key)
        # A completed turn must not be revived by a delayed thinking heartbeat.
        if key != "legacy" and previous and previous["state"] not in ACTIVE_STATES and state in ACTIVE_STATES:
            return self.view(agent)
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
        return self.view(agent)

    def view(self, agent):
        active = [(key, task) for key, task in self.tasks.get(agent, {}).items()
                  if task["state"] in ACTIVE_STATES]
        owners = {task["owner"] for _, task in active if task["owner"]}
        own = bool(self.self_owner and self.self_owner in owners)
        other = bool(owners - {self.self_owner}) if self.self_owner else False
        unknown = any(not task["owner"] for _, task in active)
        if active:
            if own and (other or unknown):
                state = "thinking_shared"
            elif other and (own or unknown):
                state = "thinking_shared"
            elif other:
                state = "thinking_other"
            else:
                state = "thinking"
            task_id = max(active, key=lambda item: item[1]["updated_at"])[0]
        else:
            terminal = self.last_terminal.get(agent)
            state = terminal[0] if terminal else "idle"
            task_id = terminal[1] if terminal else None
        return {"state": state, "task_id": task_id,
                "active_tasks": len(active), "self_active": own,
                "other_active": other, "unknown_active": unknown}

    def expire(self, now, active_ttl, terminal_ttl):
        changed = []
        for agent, tasks in self.tasks.items():
            before = self.view(agent)
            for key, task in list(tasks.items()):
                ttl = active_ttl if task["state"] in ACTIVE_STATES else terminal_ttl
                if now - task["updated_at"] >= ttl:
                    del tasks[key]
            terminal = self.last_terminal.get(agent)
            if terminal and now - terminal[2] >= terminal_ttl:
                del self.last_terminal[agent]
            after = self.view(agent)
            if before != after:
                changed.append((agent, after))
        return changed
