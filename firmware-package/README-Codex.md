# agentpad 刷机操作手册（执行者：Codex｜作者：探春｜2026-08-24）

> 你的任务：把老杨的 CXT Studio 12E4 小键盘刷成 agentpad 固件（AI agent 状态灯控制台）。
> 本包一切就绪，你按本文档执行即可。协议细节想深究看 `PROTOCOL.md`，不想看也完全不影响执行。

## 背景（30 秒版）

- 键盘芯片 atmega32u4，bootloader 是 Atmel FLIP 方言魔改（读回被禁、VID 错位），**dfu-util/dfu-programmer 大概率认不出或半残**
- 探春已写好直刷脚本 `flash-cxt.py`（绕过所有标准工具，直接 libusb 对话 bootloader）
- 原厂固件 Rev.8 在 `firmware/` 里，**随时可刷回**，不存在变砖风险

## 第 0 步：前置检查

```bash
brew install libusb     # 刷机脚本依赖（若已装会秒过）
python3 --version       # 需 3.9+，macOS 自带即可
```

## 第 1 步：接键盘

键盘 USB 插到这台 Mac。插上后跑：

```bash
python3 - <<'EOF'
import subprocess; print(subprocess.run(["system_profiler","SPUSBDataType","-detailLevel","basic"],capture_output=True,text=True).stdout)
EOF
```

在输出里找 CXT / 2ff4 / 03eb / 5754 字样确认设备在总线上（找不到就换 USB 口/线再试）。

## 第 2 步：刷机（一条命令）

```bash
cd <本包目录>
python3 flash-cxt.py
```

脚本会：
1. 提示**按键盘 PCB 背面的 RESET 轻触开关**（旋钮支架附近，可能要用指甲或笔尖；这时告诉老杨：「请按键盘背面的 RESET 键」）
2. 等 DFU 出现（最长 180s）→ 擦除（≤20s）→ 写入（~2700 条消息，约 1-2 分钟）→ 启动 → 自动验证键盘以 `5754:C401` 复活
3. 全程有日志，哪步失败都有明确提示

**脚本卡住/失败怎么办**：
- 任何「卡死/超时」→ 让老杨拔插一次键盘 USB，重跑脚本（bootloader 永远不会坏，这是它的硬件保护区）
- 连续 3 次失败 → 停手，把完整日志发给老杨转探春，不要自由发挥（尤其不要尝试 dfu-util / USB reset / 自己改协议字节）

## 第 3 步：验证

脚本自带验证（等 `5754:C401` 枚举）。额外可跑：

```bash
python3 verify/check-enumeration.py
```

看到 `5754:C401` + 多个 HID 接口 = 刷机成功 ✅ 向老杨报捷，然后提醒他：**灯不会自己亮**，灯效要等探春的 agentpad-client 常驻程序（下一包），本包只负责把固件写进去。

## 恢复原厂（任何时候）

```bash
python3 flash-cxt.py --rev8
```

30 秒回到出厂状态。VIA 键位配置的 JSON 备份在探春那边也有。

## 红线（必读）

1. **禁止** `dfu-util`、`avrdude`、任何「聪明的替代方案」——只跑本包脚本
2. **禁止** 对 DFU 设备做 USB reset（会把设备打下总线，只能拔插救）
3. **禁止**改 `flash-cxt.py` 里的协议字节再试（每个字节都是实测换来的，详见 PROTOCOL.md 的血泪教训）
4. 键盘进 DFU 靠 RESET 键（物理），软件方式对 Rev.8 无效，别浪费时间
5. 失败重试只允许「拔插 USB + 重跑脚本」这一种姿势

## 成功后

告诉老杨：「刷机成功，键盘已运行 agentpad 固件」。然后这个包的任务结束。agentpad-client（点灯 daemon + 开机自启）由探春另行交付。
