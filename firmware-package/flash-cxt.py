#!/usr/bin/env python3
"""CXT 12E4 agentpad 刷机工具（0824 定稿，探春逆向，供 Codex/任何人执行）.

目标键盘: CXT Studio 12E4 (atmega32u4, 12键+4旋钮)
bootloader: Atmel FLIP AVR8 方言魔改版（官方工具箱=QMK Toolbox换皮+原版dfu-programmer）

本脚本一条龙: 等 DFU 出现 → 擦除 → 写入 → 启动 → 验证键盘复活。

用法:
  python3 flash-cxt.py                # 刷 agentpad 固件 (默认)
  python3 flash-cxt.py --rev8         # 刷回原厂 Rev.8 (恢复用)
  python3 flash-cxt.py --no-launch    # 只写不启动

前置: brew install libusb   (脚本自动找 /opt/homebrew 或 /usr/local 的 dylib)
物理: 键盘插 USB; 脚本提示时按 PCB 背面 RESET 轻触开关进 DFU。

协议实证 (2026-08-23 深夜逆向, 详见 PROTOCOL.md):
  擦除 = DNLOAD [04 00 FF], GETSTATUS 轮询 ≤20s
  写入 = DNLOAD [01 00 sHi sLo eHi eLo] + 数据 + 16B footer('DFU'签名, CRC恒0)
  启动 = DNLOAD [04 03 00] + 零长 DNLOAD
  wValue 事务号每次 DNLOAD 全局递增 (对齐 dfu-programmer device->transaction++)
  设备可能以 2ff4:0000 (描述符错位) 或 03eb:2ff4 (标准) 枚举 —— 两个都认。
"""
import ctypes
import glob
import os
import sys
import time
import warnings

warnings.filterwarnings("ignore")
from ctypes import c_void_p, POINTER, byref, c_uint8, c_uint16, c_uint, c_char_p

APP_SIZE = 0x7000
DATA_PER_MSG = 10  # 6+10+16 = 32 字节 = 单 USB 包(实测安全尺寸)
FOOTER = bytes([0, 0, 0, 0, 16, 0x44, 0x46, 0x55, 0x01, 0x10, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF])
KEYBOARD_VID, KEYBOARD_PID = 0x5754, 0xC401  # 刷完应枚举成这个


def log(*a): print(*a, flush=True)


def load_libusb():
    for p in (glob.glob("/opt/homebrew/lib/libusb-1.0*.dylib")
              + glob.glob("/usr/local/lib/libusb-1.0*.dylib")
              + ["/opt/homebrew/lib/libusb-1.0.dylib", "/usr/local/lib/libusb-1.0.dylib"]):
        if os.path.exists(p):
            return ctypes.cdll.LoadLibrary(p), p
    log("❌ 找不到 libusb，请先: brew install libusb")
    sys.exit(2)


lib, LIBPATH = load_libusb()
for fn, at, rt in [
    ("libusb_init", [POINTER(c_void_p)], ctypes.c_int),
    ("libusb_get_device_list", [c_void_p, POINTER(POINTER(c_void_p))], ctypes.c_ssize_t),
    ("libusb_free_device_list", [POINTER(c_void_p), ctypes.c_int], None),
    ("libusb_open", [c_void_p, POINTER(c_void_p)], ctypes.c_int),
    ("libusb_close", [c_void_p], None),
    ("libusb_claim_interface", [c_void_p, ctypes.c_int], ctypes.c_int),
    ("libusb_control_transfer", [c_void_p, c_uint8, c_uint8, c_uint16, c_uint16, c_char_p, c_uint16, c_uint], ctypes.c_int),
]:
    f = getattr(lib, fn); f.argtypes = at; f.restype = rt


class DevDesc(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("bLength", c_uint8), ("bDescriptorType", c_uint8), ("bcdUSB", c_uint16),
                ("bDeviceClass", c_uint8), ("bDeviceSubClass", c_uint8), ("bDeviceProtocol", c_uint8),
                ("bMaxPacketSize0", c_uint8), ("bcdDevice", c_uint16),
                ("idVendor", c_uint16), ("idProduct", c_uint16),
                ("iManufacturer", c_uint8), ("iProduct", c_uint8), ("iSerialNumber", c_uint8),
                ("bNumConfigurations", c_uint8)]


lib.libusb_get_device_descriptor.argtypes = [c_void_p, POINTER(DevDesc)]

BOOTLOADERS = [(0x2FF4, 0x0000), (0x03EB, 0x2FF4)]  # 错位枚举 + 标准枚举, 都认


def scan(ctx):
    """返回 (bootloader设备 or None, 键盘app是否在线)."""
    lst = POINTER(c_void_p)()
    n = lib.libusb_get_device_list(ctx, byref(lst))
    bl = kb = None
    for i in range(n):
        d = DevDesc()
        lib.libusb_get_device_descriptor(lst[i], byref(d))
        if (d.idVendor, d.idProduct) in BOOTLOADERS:
            bl = lst[i]
        elif d.idVendor == KEYBOARD_VID and d.idProduct == KEYBOARD_PID:
            kb = True
    return bl, kb


def load_image(path):
    raw = open(path, "rb").read()
    if not path.endswith(".hex"):
        return raw
    mem = bytearray(b"\xFF" * APP_SIZE)
    hi = 0
    for ln in raw.decode(errors="replace").splitlines():
        if not ln.startswith(":"):
            continue
        b = bytes.fromhex(ln[1:])
        cnt, a16, typ = b[0], (b[1] << 8) | b[2], b[3]
        data = b[4:4 + cnt]
        if typ == 4:
            hi = ((data[0] << 8) | data[1]) << 16
        elif typ == 0:
            a = hi + a16
            if a + cnt > APP_SIZE:
                log(f"❌ HEX 越界: 0x{a + cnt:X} ( bootloader 区被碰, 拒刷 )"); sys.exit(2)
            mem[a:a + cnt] = data
    return bytes(mem)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    agentpad_hex = os.path.join(here, "firmware", "cxt_studio_12e4_agentpad_v6_backup_with_volume.hex")
    rev8_hex = os.path.join(here, "firmware", "cxt_labs_cxt12e4_D&M_Rev8_0530.hex")
    target = rev8_hex if "--rev8" in sys.argv else agentpad_hex
    no_launch = "--no-launch" in sys.argv

    img = load_image(target)
    img = img + b"\xFF" * (APP_SIZE - len(img))
    nz = sum(1 for b in img if b != 0xFF)
    tag = "原厂Rev.8" if "--rev8" in sys.argv else "agentpad(QMK)"
    log(f"[img] {tag}: {os.path.basename(target)} 非FF {nz}B / {APP_SIZE}")

    ctx = c_void_p()
    lib.libusb_init(byref(ctx))

    # --- 0. 等 DFU (最长 180s, 提示按 RESET) ---
    bl, kb = scan(ctx)
    if bl is None:
        log("⏳ 键盘不在 DFU 模式。请按键盘 PCB 背面的 RESET 轻触开关(旋钮支架附近)")
        t0 = time.time()
        while time.time() - t0 < 180:
            time.sleep(0.2)
            bl, kb = scan(ctx)
            if bl:
                break
        if bl is None:
            log("❌ 180 秒没等到 DFU，退出（未做任何写入）")
            return 2
    log("[usb] ✅ DFU 已在线")

    h = c_void_p()
    if lib.libusb_open(bl, byref(h)) != 0:
        log("❌ 打不开设备（重插一次 USB 再跑本脚本）"); return 2
    lib.libusb_claim_interface(h, 0)

    buf = ctypes.create_string_buffer(64)
    txn = [0]

    def getstatus():
        rc = lib.libusb_control_transfer(h, 0xA1, 3, 0, 0, buf, 6, 5000)
        if rc < 6: return None, 0, None
        raw = buf.raw
        return raw[0], int.from_bytes(raw[1:4], "little"), raw[4]

    def dnload(data):
        b = ctypes.create_string_buffer(bytes(data), len(data))
        rc = lib.libusb_control_transfer(h, 0x21, 1, txn[0] & 0xFFFF, 0, b, len(data), 25000)
        txn[0] += 1
        return rc

    st, tmo, sd = getstatus()
    log(f"[st] DFU 初始 status={st} poll={tmo} state={sd} (state=2 才能刷)")
    if sd != 2:
        log("⚠️ 状态不在 idle —— 先重插 USB 再跑一次")

    # --- 1. 擦除 ---
    rc = dnload([0x04, 0x00, 0xFF])
    log(f"[erase] [04 00 FF] rc={rc}")
    if rc != 3:
        log("❌ 擦除命令被拒（重插 USB 再跑）"); return 4
    t0 = time.time()
    while time.time() - t0 < 25:
        st, tmo, sd = getstatus()
        if st is None:
            time.sleep(0.3); continue
        if sd == 2 or sd == 10:
            break
        time.sleep(max(tmo, 100) / 1000)
    st, tmo, sd = getstatus()
    log(f"[erase] {'✅' if (st == 0 and sd == 2) else '❌'} status={st} state={sd} 用时{time.time()-t0:.1f}s")
    if not (st == 0 and sd == 2):
        return 4

    # --- 2. 写入 ---
    t0 = time.time()
    nmsg = 0
    addr = 0
    while addr < APP_SIZE:
        n = min(DATA_PER_MSG, APP_SIZE - addr)
        if img[addr:addr + n] == b"\xFF" * n:
            addr += n; continue
        msg = bytes([0x01, 0x00, (addr >> 8) & 0xFF, addr & 0xFF,
                     ((addr + n - 1) >> 8) & 0xFF, (addr + n - 1) & 0xFF]) \
              + img[addr:addr + n] + FOOTER
        rc = dnload(msg)
        if rc != len(msg):
            log(f"❌ 写入失败 @0x{addr:04X} rc={rc}"); return 5
        st, tmo, sd = getstatus()
        if st is None or st != 0:
            log(f"❌ 写后状态异常 @0x{addr:04X} status={st} state={sd}"); return 5
        addr += n
        nmsg += 1
        if nmsg % 200 == 0:
            log(f"  ... 0x{addr:04X} ({nmsg} 消息) {time.time()-t0:.1f}s")
    log(f"[write] ✅ 写完 {nmsg} 条消息, 用时 {time.time()-t0:.1f}s")

    # --- 3. 启动 ---
    if not no_launch:
        rc = dnload([0x04, 0x03, 0x00])
        log(f"[launch] [04 03 00] rc={rc}")
        rc = dnload(b"")
        log(f"[launch] 零长DNLOAD rc={rc}")
    lib.libusb_close(h)

    # --- 4. 验证键盘复活 ---
    if not no_launch:
        log("[verify] 等键盘枚举 (5754:C401)...")
        t0 = time.time()
        while time.time() - t0 < 12:
            time.sleep(0.5)
            bl, kb = scan(ctx)
            if kb:
                log(f"[verify] ✅✅✅ 键盘已复活! (t={time.time()-t0:.1f}s) 刷机成功")
                return 0
        log("[verify] ⚠️ 12 秒内没等到键盘枚举。可能固件没起来 → 按 RESET 回 DFU, 用 --rev8 恢复原厂, 再回报探春")
        return 6
    return 0


if __name__ == "__main__":
    sys.exit(main())
