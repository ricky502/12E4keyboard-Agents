#!/bin/bash
# agentpad-client 一键安装 (老杨 Mac) — 探春 2026-08-24
# 作用: 拷贝到 ~/Library/AgentpadClient + 注册 launchd 开机自启 + 自检
# 前置: 小键盘已刷成 agentpad 固件 (刷机包 README-Codex.md) 并插在这台 Mac 上
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
DST="$HOME/Library/AgentpadClient"
LABEL="com.agents.agentpad-client"
CMD_LABEL="com.agents.agentpad-commandd"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
CMD_PLIST="$HOME/Library/LaunchAgents/$CMD_LABEL.plist"
LOG="$HOME/Library/Logs/agentpad-client.log"
CMD_LOG="$HOME/Library/Logs/agentpad-commandd.log"

PY="$(command -v python3 || true)"
[ -z "$PY" ] && { echo "❌ 找不到 python3 (macOS: 装 Xcode Command Line Tools)"; exit 2; }
PY="$(readlink -f "$PY" 2>/dev/null || echo "$PY")"

echo "== 1/5 停止旧版服务并拷贝到 $DST"
# Stop first: the running daemon keeps libhidapi.dylib mapped, which prevents
# macOS from replacing the bundled dylib in place.
launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
launchctl bootout "gui/$UID/$CMD_LABEL" 2>/dev/null || true
mkdir -p "$DST" "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
# Earlier packages marked the bundled dylib read-only.  This directory belongs
# to the current user, so restore user-write permission before replacing it.
chmod -R u+w "$DST" 2>/dev/null || true
cp -R "$SRC/." "$DST/"
chmod +x "$DST/agentpad-clientd.py" 2>/dev/null || true
chmod +x "$DST/agentpad-commandd.py" 2>/dev/null || true
chmod +x "$DST/feishu_status_listener.py" 2>/dev/null || true
chmod +x "$DST/claude_status_hook.py" 2>/dev/null || true
echo "== 1.5/5 准备飞书状态监听依赖（独立环境，不改系统 Python）"
VENV="$DST/venv"
"$PY" -m venv "$VENV"
"$VENV/bin/python" -m pip install --disable-pip-version-check --quiet "lark-channel-sdk==1.2.0"
PY="$VENV/bin/python"
SWIFTC="$(xcrun --find swiftc 2>/dev/null || true)"
SDKROOT_PATH="$(xcrun --show-sdk-path 2>/dev/null || true)"
if [ -n "$SWIFTC" ] && [ -f "$DST/feishu_local_snapshot.swift" ]; then
  "$SWIFTC" -sdk "$SDKROOT_PATH" "$DST/feishu_local_snapshot.swift" -o "$DST/feishu-local-snapshot" \
    || echo "   ⚠️ 本机飞书只读采集器未编译；键盘基础功能不受影响"
fi
if [ -n "$SWIFTC" ] && [ -f "$DST/feishu_local_ocr.swift" ]; then
  "$SWIFTC" -sdk "$SDKROOT_PATH" "$DST/feishu_local_ocr.swift" -o "$DST/feishu-local-ocr" \
    || echo "   ⚠️ 本机飞书 OCR 采集器未编译；键盘基础功能不受影响"
fi

echo "== 2/5 生成命令适配器 launchd 配置 ($CMD_LABEL)"
cat > "$CMD_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$CMD_LABEL</string>
  <key>ProgramArguments</key><array>
    <string>$PY</string>
    <string>$DST/agentpad-commandd.py</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$CMD_LOG</string>
  <key>StandardErrorPath</key><string>$CMD_LOG</string>
</dict></plist>
EOF

launchctl bootout "gui/$UID/$CMD_LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UID" "$CMD_PLIST" 2>/dev/null || launchctl load -w "$CMD_PLIST"

echo "== 3/5 生成 launchd 配置 ($LABEL)"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array>
    <string>$PY</string>
    <string>$DST/agentpad-clientd.py</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict></plist>
EOF

echo "== 4/5 启动 daemon (launchd)"
launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UID" "$PLIST" 2>/dev/null || launchctl load -w "$PLIST"
sleep 2
launchctl print "gui/$UID/$LABEL" >/dev/null 2>&1 && echo "   daemon 已在跑 (KeepAlive=崩溃自动拉起/开机自启)" \
  || { echo "❌ launchd 启动失败, 看 $LOG"; exit 3; }

echo "== 5/5 通信自检 (需键盘已刷机并插着)"
"$PY" "$DST/agentpad-clientd.py" --selftest || echo "   ⚠️ 键盘自检未过 — daemon 已在跑并等键盘, 插上/刷好后自动接管"

echo "== 完成"
IP="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo '本机IP')"
cat <<EOF

✅ agentpad-client 安装完毕
   状态页:  curl http://$IP:8124/health
   点个灯:  curl -X POST http://$IP:8124/state -d '{"agent":"tanchun","state":"thinking"}'
   日志:    tail -f $LOG
   卸载:    bash $DST/uninstall.sh
   本机飞书模式: 键盘只控制本机飞书客户端，不连接 Mac Mini
EOF
