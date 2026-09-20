# Agentpad v2：8-Agent 固件

当前推荐固件：`cxt_studio_12e4_agentpad_v14_native_encoders.hex`

v14 保留 v13 的固件原生 Option / Enter，并将四个旋钮旋转改成原生 USB
键。物理顺序固定为：1 屏幕亮度、2 快退/快进、3 系统音量、4 文字缩放/
网页视频倍速。四号旋钮按压会在缩放和倍速模式之间切换。旋转不再经过
本机 HTTP/脚本队列，连续操作的响应更接近普通硬件键盘。

v3/v4 虽然标注为 Raw HID 版本，但历史源码仍保留了旋钮原生动作。
v12 已从源码重新编译，并确认四个旋钮回调只发送 Agentpad Raw HID 事件，
所有动作交给本机客户端执行。

已验证版本：`cxt_studio_12e4_agentpad_v4_encoderfix_verified.hex`。该版本
修复了 v3 中旋钮回调未实际阻止 QMK 默认音量分支的问题；应优先使用此文件。

## 本版本内容

- 第一排：探春、黛玉、湘云、香菱
- 第二排：莺儿、Codex、VSCode Claude、宝钗
- 第三排：语音、批准、拒绝、新任务
- 四个旋钮全部启用，旋转动作由固件直接发送原生 USB 键
- 四号旋钮按压同步切换文字缩放与网页视频倍速模式
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
