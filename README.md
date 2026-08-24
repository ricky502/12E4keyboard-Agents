# 12E4keyboard-Agents

将 CXT Studio 12E4 客制化小键盘改造成 Agent 工作台：用实体按键切换 Agent、用灯光展示任务状态，并在 macOS 本机接入飞书、Codex 和 VS Code Claude 工作流。

## 项目组成

- `firmware-package/`：12E4 的 Agentpad 固件、刷机脚本、USB/HID 协议与恢复原厂固件说明。
- `client/`：macOS 常驻客户端，负责键盘灯效、按键/旋钮命令、飞书状态监听，以及 Codex、Claude 的本机适配。
- `今日开发报告-2026-08-24.md`：当天完成内容与可用范围。

## 当前可用功能

- 8 个 Agent 槽位及状态灯：待机、工作、完成、等待输入、异常。
- 飞书群状态消息的本机实时监听；不需要与远程 Agent 主机建立网络连接。
- 4 个功能键：语音、批准、拒绝、新任务；4 个旋钮：模型、思考深度、音量、缩放。
- macOS 开机自启、USB/HID 连接自检与断线重连。

## 快速开始

1. 先阅读 `firmware-package/README-Codex.md` 并按说明刷入固件。
2. 再阅读 `client/README.md`，安装本机常驻客户端。
3. 飞书 App Secret 仅存 macOS 钥匙串，不写入配置文件或版本库。

## 安全说明

本仓库不包含飞书 App Secret、访问令牌、macOS 钥匙串内容、个人飞书聊天记录或个人键位备份。请以示例配置为基础，在自己的设备上完成配置。
