# Agentpad v2：8-Agent 固件

固件文件：`cxt_studio_12e4_agentpad_v2_8agent.hex`

后续修复版：`cxt_studio_12e4_agentpad_v3_encoderfix.hex`。此版本在固件层
强制截断四个旋钮的原厂媒体音量/RGB 动作，只保留 Agentpad Raw HID 事件。

## 本版本内容

- 第一排：探春、黛玉、湘云、香菱
- 第二排：莺儿、Codex、VSCode Claude、宝钗
- 第三排：语音、批准、拒绝、新任务
- 四个旋钮全部启用并通过 Raw HID `ENC_EVENT` 上报
- 禁止 CXT 原生固件层自动修改音量或 RGB，旋钮动作交给本机客户端按配置执行
- 保留 Raw HID 状态灯、心跳和按键事件协议

## 当前状态

- 已完成 QMK 编译验证。
- 尚未刷写到键盘。
- 刷写前必须先确认键盘处于 DFU 模式，并保留原厂 Rev.8 恢复文件。
- 刷写后需要使用新版 agentpad-client 进行按键和旋钮联调。

## 相关构建输入

- `cxt_studio/12e4/keyboard.json`
- `cxt_studio/12e4/cxt_studio.c`
- `cxt_studio/12e4/keymaps/agentpad/keymap.c`
- `cxt_studio/12e4/keymaps/agentpad/rules.mk`
