"""agentpad raw HID protocol v1 — host side.

Mirror of qmk_firmware/keyboards/cxt_studio/12e4/keymaps/agentpad/keymap.c
32-byte packets. Keep the two files in sync when bumping the protocol.

Host -> keyboard:
  0x01 SET_SLOT   [cmd, slot(0-11), r, g, b]
  0x02 CLEAR_ALL  [cmd]
  0x03 SET_BRIGHT [cmd, scale(0-255)]
  0x10 SET_MODE   [cmd, slot(0-11), mode]   0=static 1=blink 2=breathe
  0x7E PING       [cmd, echo]
Keyboard -> host:
  0x7F PONG       [cmd, echo, proto, led_count]
  0x81 KEY_EVENT  [cmd, slot(0-15), pressed(1/0), layer]
  0x82 ENC_EVENT  [cmd, enc(0-3), clockwise(1/0), layer]
"""

EPSIZE = 32
PROTO_VER = 1
LED_COUNT = 12

VID, PID = 0x5754, 0xC401  # CXT Studio 12E4
RAW_USAGE_PAGE, RAW_USAGE = 0xFF60, 0x61  # QMK raw HID interface

# 状态语义 = README 色表；mode 见 firmware（琥珀呼吸/错误闪烁）
STATE_COLORS = {
    #            (r, g, b)   mode
    "idle":        ((60, 60, 60),  0),  # 白（暗白，防刺眼）
    "thinking":    ((0, 60, 255),  0),  # 蓝
    "complete":    ((0, 255, 60),  0),  # 绿
    "needs_input": ((255, 130, 0), 2),  # 琥珀·呼吸
    "error":       ((255, 0, 0),   1),  # 红·闪烁
    "off":         ((0, 0, 0),     0),  # 灭 / 无绑定
}


def _pkt(cmd, *args) -> bytes:
    b = bytes([cmd, *args])
    assert len(b) <= EPSIZE, f"packet overflow: {len(b)}"
    return b.ljust(EPSIZE, b"\x00")


def set_slot(slot: int, rgb: tuple) -> bytes:
    assert 0 <= slot < LED_COUNT
    return _pkt(0x01, slot, *rgb[:3])


def clear_all() -> bytes:
    return _pkt(0x02)


def set_brightness(scale: int) -> bytes:
    return _pkt(0x03, scale)


def set_mode(slot: int, mode: int) -> bytes:
    assert 0 <= slot < LED_COUNT
    return _pkt(0x10, slot, mode)


def ping(echo: int) -> bytes:
    return _pkt(0x7E, echo)


def parse(data: bytes):
    """-> dict or None if unknown/short."""
    if len(data) < EPSIZE:
        return None
    cmd = data[0]
    if cmd == 0x7F:
        return {"t": "pong", "echo": data[1], "proto": data[2], "led_count": data[3]}
    if cmd == 0x81:
        return {"t": "key", "slot": data[1], "pressed": data[2] == 1, "layer": data[3]}
    if cmd == 0x82:
        return {"t": "enc", "enc": data[1], "cw": data[2] == 1, "layer": data[3]}
    return None


class Virtual12E4:
    """Firmware mirror for loopback testing (no hardware needed).

    Implements exactly what keymap.c does: feed it host packets via
    feed(), read keyboard-originated packets from .outbox.
    """

    SLOT_TO_LED = (3, 2, 1, 0, 4, 5, 6, 7, 11, 10, 9, 8)  # snake wiring

    def __init__(self):
        self.slot_rgb = [[0, 0, 0] for _ in range(LED_COUNT)]
        self.slot_mode = [0] * LED_COUNT
        self.global_scale = 160
        self.outbox: list[bytes] = []

    def feed(self, pkt: bytes) -> None:
        assert len(pkt) == EPSIZE
        cmd, d = pkt[0], pkt
        if cmd == 0x01 and d[1] < LED_COUNT:
            self.slot_rgb[d[1]] = [d[2], d[3], d[4]]
        elif cmd == 0x02:
            self.slot_rgb = [[0, 0, 0] for _ in range(LED_COUNT)]
            self.slot_mode = [0] * LED_COUNT
        elif cmd == 0x03:
            self.global_scale = d[1]
        elif cmd == 0x10 and d[1] < LED_COUNT:
            self.slot_mode[d[1]] = d[2] % 3
        elif cmd == 0x7E:
            resp = bytearray(EPSIZE)
            resp[0], resp[1], resp[2], resp[3] = 0x7F, d[1], PROTO_VER, LED_COUNT
            self.outbox.append(bytes(resp))

    # -- test helpers: synthesize keyboard-originated events --
    def emit_key(self, slot: int, pressed: bool, layer: int = 0) -> None:
        b = bytearray(EPSIZE)
        b[0], b[1], b[2], b[3] = 0x81, slot, 1 if pressed else 0, layer
        self.outbox.append(bytes(b))

    def emit_enc(self, index: int, cw: bool, layer: int = 0) -> None:
        b = bytearray(EPSIZE)
        b[0], b[1], b[2], b[3] = 0x82, index, 1 if cw else 0, layer
        self.outbox.append(bytes(b))
