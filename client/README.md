# agentpad-client — 点灯常驻程序（装在老杨 Mac 上）

> 作者：探春 2026-08-24。**前置：小键盘已刷成 agentpad 固件**（上一个包 `agentpad-刷机包`），键盘插在这台 Mac 上。
> 作用：开机自启的小服务，接收状态并点亮键盘；同时把键盘事件路由给本机/远程 Agent 适配器。
> 零依赖：不用 brew 不用 pip，只用 macOS 自带 python3 + 包内自带的 libhidapi.dylib。

## 日常诊断（无需刷机）

服务启动后，可用以下两个只读接口检查整条本地链路：

```bash
curl http://127.0.0.1:8124/doctor
curl http://127.0.0.1:8124/profile
```

`/doctor` 会分别报告：12E4 Raw HID 是否在线、命令适配器是否可访问、飞书状态监听状态、过期 Agent 状态和配置档警告。它不会发送飞书消息、不会改变键盘灯，也不会刷写固件。

首次安装后的完整 HID 灯控往返测试仍可运行：

```bash
python3 agentpad-clientd.py --selftest
```

该测试会短暂扫描 12 颗灯，应在没有正在执行的重要任务时运行。

## 本地配置档（无需刷机）

将 [panel-profile.example.json](panel-profile.example.json) 中的 `panel_profile` 段合并到 `config.json`，即可改变 8 个 Agent 的实体槽位顺序、底部四个动作顺序和各状态颜色；配置只在本机客户端加载，重启客户端后生效。

`talk` 目前是 **Option 修饰键**，不是语音输入法；本项目没有把任何按键绑定到 macOS 听写或飞书录音。

## 可视化按键编辑器

打开 <http://127.0.0.1:8124/> 即可使用本机编辑器。它会显示真实的 3×4 键位、当前状态颜色、四个旋钮的固定映射和诊断结果；点击“保存本机配置”后立即应用并原子写回当前 `config.json`。

- 前两排可编辑 8 个 Agent 的实体槽位顺序；Agent 名称必须与 `command-config.json` 的 `targets` 名称一致，才能正确打开对应入口。
- 最下一排可重新排列 Option、Enter、`/stop + Enter`、`/new + Enter` 四个已有动作。
- 可编辑待机、工作、完成、等待输入、异常、熄灭六种颜色与灯效模式。
- 四个旋钮在当前版本仅展示已验证的固定映射，不在网页中改动，避免重新引入以前的物理顺序错位问题。

编辑器只访问本机 `127.0.0.1` 服务；保存时不刷机、不发送飞书消息，也不会修改远程 Agent。

## 安装（一条命令）

```bash
cd <本包目录>
bash install.sh
```

装完自动：launchd 注册（开机自启+崩溃拉起）→ 通信自检（PING 键盘 + 12 键彩灯扫一遍）。

## 验证

```bash
curl http://localhost:8124/health
# 应返回 {"ok": true, "keyboard_online": true, ...}

# 点个灯试试（探春键应变蓝）:
curl -X POST http://localhost:8124/state -d '{"agent":"tanchun","state":"thinking"}'
# 灭掉:
curl -X POST http://localhost:8124/state -d '{"agent":"tanchun","state":"off"}'
```

## 键位 ↔ agent（8-Agent 布局）

| 键 | agent | 灯色语义 |
|---|---|---|
| 第一排 1-4 | 探春 / 黛玉 / 湘云 / 香菱 | 白=空闲 蓝=思考 绿=完成 琥珀呼吸=等输入 红闪=错误 |
| 第二排 1-4 | 莺儿 / Codex / VSCode Claude / 宝钗 | 同上 |
| 第三排 1-4 | 语音 / 批准 / 拒绝 / 新任务 | 当前选中 Agent 的命令 |

## 推状态 API（本机飞书适配器用）

```
POST /state        {"agent":"daiyu","state":"complete","task_id":"run-42","updated_at":1787490000,"source":"mac-mini"}
POST /state/all    {"state":"off"}
POST /brightness   {"value":160}
POST /ping         → 键盘往返测试
GET  /health       → 在线状态+全部槽位
```

- agent 名：`tanchun / daiyu / xiangyun / xiangling / yinger / codex / claude-vscode / baochai`
- state：`idle / thinking / complete / needs_input / error / off`
- `task_id`、`updated_at`（Unix 秒）和 `source` 可选。`/health` 会返回每个 Agent 的这些信息。为避免旧任务状态长期遗留，`thinking` 超过 5 分钟、完成/异常/等待输入超过 30 分钟且没有新事件时，会自动恢复为待机。

### 香菱：企业微信智能机器人

香菱的 Agent 键会打开本机「企业微信」，不再跳转飞书。企业微信的 Bot ID 与 Secret 只保存在 macOS 登录钥匙串：服务名 `Agentpad WeCom AI Bot`，账号分别为 `xiangling.bot_id` 与 `xiangling.secret`；不写入配置、源码或版本库。企业微信 API 的 Bot ID/Secret 用于其长连接机器人服务，不是桌面客户端的公开聊天链接。

键盘事件会通过 `command_forward_url` 转给命令适配器，格式示例：

```json
{"action":"approve","agent":"daiyu","source":9,"selected_slot":1}
{"action":"encoder","agent":"claude-vscode","source":3,"selected_slot":6,"clockwise":true}
```

“批准/拒绝”只会在选中 Agent 处于 `needs_input` 时打开并聚焦对应的本机飞书会话，不会后台点击卡片；“语音”键同样只打开当前选中的飞书会话（或 VSCode Claude），录音与转写仍由对应客户端完成。

## 配置

`~/Library/AgentpadClient/config.json`（首次运行自动生成）：
`port`（默认 8124）、`brightness`（默认 160）、`bind`（默认 127.0.0.1）、`token`（默认空；设值后请求须带 `X-Agentpad-Token` 头）、`key_forward_url`（原始键盘事件转发地址）、`command_forward_url`（Agentpad 命令适配器地址）、`command_token`（命令适配器的同名鉴权令牌）。

`token` 与 `command_token` 建议各使用不同的长随机值；不要把它们或飞书 App Secret 放进固件、聊天记录或版本库。

### 飞书状态组（所有 Agent 同时显示）

启用 `feishu_status_monitor:true` 后，客户端通过飞书官方出站长连接接收状态；不接入 Mac Mini，也不需要公网回调。`feishu_status_app_id` 填 Agentpad monitor 的 App ID，`feishu_status_chat_id` 填专用状态群的 `oc_...` ID。App Secret 只保存于 macOS 登录钥匙串，服务名为 `Agentpad Feishu Status Monitor`、账号为 App ID；不会写入此配置文件。

状态群消息只接受这一种格式，其他聊天内容在本机直接丢弃、不会保存：

```
[AGENTPAD] {"agent":"tanchun","state":"thinking","task_id":"optional"}
```

## 排障

| 症状 | 处理 |
|---|---|
| 防火墙弹窗"是否允许接入网络连接" | 点**允许**（局域网收状态必须） |
| `/health` 里 `keyboard_online:false` | 键盘没插/没刷机 → 跑刷机包的 `verify/check-enumeration.py`；daemon 会自动重连，插上即接管 |
| selftest 报"没找到接口" | 同上；若系统设置→隐私与安全性→**输入监控**里有 python3/Terminal 被拦，勾上 |
| 日志 | `tail -f ~/Library/Logs/agentpad-client.log` |
| 卸载 | `bash ~/Library/AgentpadClient/uninstall.sh` |

## 边界（Codex 注意）

- 本包不动键盘固件、不碰 DFU——刷机归上一个包
- `hid/libhidapi.dylib` 是探春打包的（仅链系统框架+已 ad-hoc 签名），别替换别升级
- daemon 挂了 launchd 会拉起；改了 config.json 后 `launchctl kickstart -k gui/$(id -u)/com.agents.agentpad-client` 重启生效
