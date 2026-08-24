# CXT Studio 12E4 bootloader 协议实证（探春 2026-08-23 深夜逆向）

> 给后续维护者/Codex 的完整技术底档。所有结论均实测或从权威源码核对，无猜测项。

## 设备

| 模式 | USB 枚举 | 说明 |
|---|---|---|
| 正常键盘（原厂 Rev.8） | `5754:C401`，8 个 HID 接口（含 ff60:0061 raw HID） | 刷机成功的标志 |
| DFU/bootloader | `2ff4:0000`（描述符错位）**或** `03eb:2ff4`（标准） | 同一设备，描述符字段错位是其固件 bug |

- 芯片 atmega32u4，app 区 `0x0000-0x6FFF`（28672B），bootloader 区 `0x7000+` 受保护
- bootloader = **Atmel FLIP AVR8 官方方言**（doc7618）魔改：改了 VID、关了读回（防抄板）
- 官方工具箱 = QMK Toolbox 0.2.1 换皮，捆的 dfu-programmer 原封未动 → 官方刷机就是标准 FLIP
- 描述符错位现象：真 VID (03eb) 坐在 bcdDevice 槽、PID (2ff4) 坐在 idVendor 槽。同款病在罗技克隆接收器/Apple 内建 hub 上也有，不是读取 bug

## 进 DFU 的方法

1. **PCB 背面 RESET 轻触开关**（旋钮支架附近）——最可靠，官方教程步骤 7
2. 原厂固件运行时，VIA-C 私有协议 cmd 1 (jumpToBootloader) —— 对 Rev.8 实测只回 echo 不跳，不可依赖

## 命令表（control OUT 0x21, bRequest=1 DNLOAD；wValue=事务号，每次 DNLOAD 全局递增）

| 命令 | 字节 | 说明 |
|---|---|---|
| 全片擦除 | `[04 00 FF]` | 3 字节；GETSTATUS 轮询最长 20s；st=1 NOTDONE + state=4 BUSY = 还在擦 |
| 写入 | `[01 00 sHi sLo eHi eLo] + 数据 + footer16` | 地址大端在包头（无需 set-address）；footer = `00 00 00 00 10 44 46 55 01 10 FF×6`（CRC 恒 0，'DFU' 签名） |
| 启动 | `[04 03 00]` + 零长 DNLOAD | 跳去跑 app |
| GETSTATUS | control IN 0xA1, bRequest=3, wLength=6 | 返回 (status, pollTimeout 3B LE, state)；state=2 dfuIDLE |

- AVR8 **不需要** select_memory_unit（`[06 03 00 unit]` 是 AVR32/XMEGA 的，dfu-programmer 对 AVR8 直接跳过）
- 数据尺寸：单条消息 = 6 + 数据 + 16；**32 字节整包（数据 10B）是实测安全尺寸**（bMaxPacketSize0=32）
- 读回（UPLOAD 组 0x03）：**被关闭**，任何读取/verify 都会失败——这不是错误，是防抄板。dfu-programmer 报 "Memory read error" 正因此

## 血泪教训（勿重蹈）

1. **不要发残缺命令**：两字节 `[04 03]`（缺第三字节）会把 bootloader 解析器整体卡死（所有 control 超时）
2. **不要对 DFU 设备做 USB reset**：会把设备直接打下总线（彻底消失），只能拔插 USB 救
3. 卡死后唯一恢复法 = 拔插 USB（bootloader 不受任何写入影响，永远安全）
4. dfu-programmer 若能用（它认 03eb:2ff4）：`erase --force` → `flash --force --suppress-validation <hex>` → `launch` 也可，但读回被禁所以 verify 必须关

## 恢复原厂

任何时候：进 DFU → `python3 flash-cxt.py --rev8` → 键盘回到出厂 Rev.8。
VIA 键位/宏配置备份在探春处（`agentpad/backups/via_config/`）。

## agentpad 固件（已编入本包 firmware/cxt_studio_12e4_agentpad.hex）

- QMK 编译产物，27220/28672 (94%)
- raw HID ff60:0061 通道，协议：SET_SLOT(slot,mode,r,g,b)/CLEAR_ALL/SET_BRIGHT/SET_MODE/PING→PONG/KEY_EVENT/ENC_EVENT
- SLOT_TO_LED 蛇形映射 {3,2,1,0,4,5,6,7,11,10,9,8}；静态/闪烁/呼吸三模式
- 布局 v4：一排=探春/黛玉/湘云/香菱；二排=句号/退格/截图/宝钗；三排=说话/批准/复制/粘贴
- 刷机成功判据 = 键盘以 `5754:C401` 重新枚举（脚本自动验证）。灯效需要 daemon 发 SET_SLOT 才会亮，见后续 agentpad-client 包
