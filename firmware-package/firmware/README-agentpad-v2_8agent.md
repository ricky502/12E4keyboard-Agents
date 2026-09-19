# Agentpad v2：8-Agent 固件

当前推荐固件：`cxt_studio_12e4_agentpad_v13_native_bottom_keys.hex`

v13 在 v12 的 Raw-HID 旋钮和状态灯基础上，将第三排左侧两个键改为
固件原生 USB 键盘输出：语音键为左 Option，批准键为 Enter。这样 macOS
不再把它们当软件合成事件，连续使用语音输入时的响应与电脑键盘一致。
其余主键、旋钮按压和旋转仍通过 Raw HID 交给本机客户端处理。

v3/v4 虽然标注为 Raw HID 版本，但历史源码仍保留了旋钮原生动作。
v12 已从源码重新编译，并确认四个旋钮回调只发送 Agentpad Raw HID 事件，
所有动作交给本机客户端执行。

已验证版本：`cxt_studio_12e4_agentpad_v4_encoderfix_verified.hex`。该版本
修复了 v3 中旋钮回调未实际阻止 QMK 默认音量分支的问题；应优先使用此文件。

## 本版本内容

- 第一排：探春、黛玉、湘云、香菱
- 第二排：莺儿、Codex、VSCode Claude、宝钗
- 第三排：语音、批准、拒绝、新任务
- 四个旋钮全部启用并通过 Raw HID `ENC_EVENT` 上报
- 禁止 CXT 原生固件层自动修改音量、缩放或 RGB，旋钮动作交给本机客户端按配置执行
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
