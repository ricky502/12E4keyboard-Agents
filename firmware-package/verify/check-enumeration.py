#!/usr/bin/env python3
"""agentpad 刷后验证: 键盘应以 5754:C401 枚举并暴露多个 HID 接口。"""
import ctypes
import glob
import os
import sys
import warnings

warnings.filterwarnings("ignore")
from ctypes import c_void_p, POINTER, byref, c_uint8, c_uint16, c_uint, c_char_p


def load_libusb():
    for p in (glob.glob("/opt/homebrew/lib/libusb-1.0*.dylib")
              + glob.glob("/usr/local/lib/libusb-1.0*.dylib")):
        if os.path.exists(p):
            return ctypes.cdll.LoadLibrary(p)
    print("❌ 找不到 libusb: brew install libusb"); sys.exit(2)


lib = load_libusb()
for fn, at, rt in [
    ("libusb_init", [POINTER(c_void_p)], ctypes.c_int),
    ("libusb_get_device_list", [c_void_p, POINTER(POINTER(c_void_p))], ctypes.c_ssize_t),
    ("libusb_free_device_list", [POINTER(c_void_p), ctypes.c_int], None),
    ("libusb_get_device_descriptor", [c_void_p, c_void_p], ctypes.c_int),
    ("libusb_open", [c_void_p, POINTER(c_void_p)], ctypes.c_int),
    ("libusb_close", [c_void_p], None),
    ("libusb_get_string_descriptor_ascii", [c_void_p, c_uint8, c_char_p, c_uint16], ctypes.c_int),
]:
    f = getattr(lib, fn); f.argtypes = at; f.restype = rt


class DevDesc(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("a", c_uint8), ("b", c_uint8), ("c", c_uint16),
                ("d", c_uint8), ("e", c_uint8), ("f", c_uint8), ("g", c_uint8), ("h", c_uint16),
                ("vid", c_uint16), ("pid", c_uint16),
                ("iM", c_uint8), ("iP", c_uint8), ("iS", c_uint8), ("nC", c_uint8)]


lib.libusb_get_device_descriptor.argtypes = [c_void_p, POINTER(DevDesc)]

ctx = c_void_p(); lib.libusb_init(byref(ctx))
lst = POINTER(c_void_p)(); n = lib.libusb_get_device_list(ctx, byref(lst))

found = False
for i in range(n):
    d = DevDesc(); lib.libusb_get_device_descriptor(lst[i], byref(d))
    if d.vid == 0x5754 and d.pid == 0xC401:
        found = True
        h = c_void_p()
        strs = []
        if lib.libusb_open(lst[i], byref(h)) == 0:
            for idx in (d.iM, d.iP):
                if idx:
                    b = ctypes.create_string_buffer(128)
                    if lib.libusb_get_string_descriptor_ascii(h, idx, b, 128) > 0:
                        strs.append(b.value.decode(errors="replace"))
            lib.libusb_close(h)
        print(f"✅ 键盘在线 5754:C401  配置数={d.nC}  {' | '.join(strs)}")
        print("   (配置描述符里的 HID 接口数需≥4 才算完整键盘+rawHID)")
if not found:
    print("❌ 5754:C401 不在线")
    print("   若刚刷完: 等几秒重跑; 若拔插过: 按 PCB 背面 RESET 看是否回 DFU (2ff4:0000/03eb:2ff4)")
    for i in range(n):
        d = DevDesc(); lib.libusb_get_device_descriptor(lst[i], byref(d))
        if d.vid in (0x2FF4, 0x03EB):
            print(f"   ⚠️ 检测到 DFU 模式 ({d.vid:04X}:{d.pid:04X}) —— 固件没起来, 重刷或 --rev8 恢复")
    sys.exit(1)
