#!/bin/bash
# agentpad-client 卸载: 停 daemon + 删 launchd + 删程序目录 (配置一并删)
set -euo pipefail
LABEL="com.agents.agentpad-client"
CMD_LABEL="com.agents.agentpad-commandd"
DST="$HOME/Library/AgentpadClient"
launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || launchctl unload -w "$HOME/Library/LaunchAgents/$LABEL.plist" 2>/dev/null || true
launchctl bootout "gui/$UID/$CMD_LABEL" 2>/dev/null || launchctl unload -w "$HOME/Library/LaunchAgents/$CMD_LABEL.plist" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
rm -f "$HOME/Library/LaunchAgents/$CMD_LABEL.plist"
rm -rf "$DST"
echo "✅ 已卸载 (日志保留在 ~/Library/Logs/agentpad-client.log 和 ~/Library/Logs/agentpad-commandd.log)"
