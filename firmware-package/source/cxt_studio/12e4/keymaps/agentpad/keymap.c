// agentpad keymap — CXT Studio 12E4 as AI agent status console (M1b)
//
// Raw HID protocol v1 (32-byte packets, little structure, big simplicity):
//   Host -> keyboard:
//     0x01 SET_SLOT      [cmd, slot(0-11), r, g, b]      set slot color
//     0x02 CLEAR_ALL     [cmd]                            all slots black, static
//     0x03 SET_BRIGHT    [cmd, scale(0-255)]              global brightness scale
//     0x10 SET_MODE      [cmd, slot(0-11), mode]          0=static 1=blink 2=breathe
//     0x7E PING          [cmd, echo]                      health check
//   Keyboard -> host:
//     0x7F PONG          [cmd, echo, proto=1, led_count=12]
//     0x81 KEY_EVENT     [cmd, slot(0-15), pressed(1/0), layer]
//     0x82 ENC_EVENT     [cmd, enc(0-3), clockwise(1/0), layer]
//
// Slot numbering = physical: slot = row*4 + col (rows 0-2 are the 12 light keys,
// row 3 = encoder pushes, slots 12-15, no LEDs on this hardware).
// LED wiring is snaked, so SLOT_TO_LED translates slot -> rgb_matrix index.

#include QMK_KEYBOARD_H
#include "raw_hid.h"
#include <string.h>

#define AP_PROTO_VER 1
#define AP_LED_COUNT 12
#define AP_EPSIZE 32 // raw HID report size on this platform (AP_EPSIZE, AVR)

// matrix[r][c] -> rgb_matrix led index, from 12e4 g_led_config layout:
// row0 (right-to-left): [0,3],[0,2],[0,1],[0,0] ; row1 L->R ; row2 R->L
static const uint8_t SLOT_TO_LED[AP_LED_COUNT] = {3, 2, 1, 0, 4, 5, 6, 7, 11, 10, 9, 8};

static uint8_t slot_rgb[AP_LED_COUNT][3]; // per-slot target color
static uint8_t slot_mode[AP_LED_COUNT];   // 0=static 1=blink 2=breathe
static uint8_t global_scale = 160;        // comfortable default for ws2812

static uint8_t ap_scale8(uint8_t v, uint8_t s) {
    return (uint16_t)v * s / 255;
}

// 目标布局：
//   第一排: 探春 / 黛玉 / 湘云 / 香菱
//   第二排: 莺儿 / Codex / VSCode Claude / 宝钗
//   第三排: 语音 / 批准 / 拒绝 / 新任务
//   第四排: 一号灯开关 / 二号睡眠 / 三号播放暂停 / 四号保留备份粘贴
const uint16_t PROGMEM keymaps[][MATRIX_ROWS][MATRIX_COLS] = {
    [0] = LAYOUT(
        KC_NO,   KC_NO,   KC_NO,   KC_NO,
        KC_NO,   KC_NO,   KC_NO,   KC_NO,
        KC_NO,   KC_NO,   KC_NO,   KC_NO,
        RM_TOGG, KC_PWR,   KC_MPLY,  LGUI(KC_V)
    )
};

void raw_hid_receive(uint8_t *data, uint8_t length) {
    uint8_t resp[AP_EPSIZE] = {0};
    switch (data[0]) {
        case 0x01: // SET_SLOT
            if (data[1] < AP_LED_COUNT) {
                slot_rgb[data[1]][0] = data[2];
                slot_rgb[data[1]][1] = data[3];
                slot_rgb[data[1]][2] = data[4];
            }
            break;
        case 0x02: // CLEAR_ALL
            memset(slot_rgb, 0, sizeof(slot_rgb));
            memset(slot_mode, 0, sizeof(slot_mode));
            break;
        case 0x03: // SET_BRIGHT
            global_scale = data[1];
            break;
        case 0x10: // SET_MODE
            if (data[1] < AP_LED_COUNT) {
                slot_mode[data[1]] = data[2] % 3;
            }
            break;
        case 0x7E: // PING -> PONG
            resp[0] = 0x7F;
            resp[1] = data[1];          // echo token
            resp[2] = AP_PROTO_VER;
            resp[3] = AP_LED_COUNT;
            raw_hid_send(resp, AP_EPSIZE);
            break;
        default:
            break;
    }
}

bool rgb_matrix_indicators_user(void) {
    uint32_t now = timer_read();
    for (uint8_t slot = 0; slot < AP_LED_COUNT; slot++) {
        uint8_t s = global_scale;
        switch (slot_mode[slot]) {
            case 1: // blink ~2Hz, 50% duty
                if (!((now >> 8) & 1)) s = 0;
                break;
            case 2: { // breathe, ~4s triangle
                uint16_t w   = (now >> 4) & 0xFF;
                uint8_t  tri = (w < 128) ? (uint8_t)(w * 2) : (uint8_t)(510 - w * 2);
                s            = ap_scale8(s, tri);
                break;
            }
        }
        rgb_matrix_set_color(SLOT_TO_LED[slot],
                             ap_scale8(slot_rgb[slot][0], s),
                             ap_scale8(slot_rgb[slot][1], s),
                             ap_scale8(slot_rgb[slot][2], s));
    }
    // Encoder presses are handled by the local Agentpad client.  Keeping
    // them raw-HID only prevents accidental media/system key events on macOS.
    return false;
}

bool process_record_user(uint16_t keycode, keyrecord_t *record) {
    uint8_t pkt[AP_EPSIZE] = {0};
    pkt[0] = 0x81; // KEY_EVENT
    pkt[1] = record->event.key.row * 4 + record->event.key.col; // slot 0-15
    pkt[2] = record->event.pressed ? 1 : 0;
    pkt[3] = (uint8_t)get_highest_layer(layer_state);
    raw_hid_send(pkt, AP_EPSIZE);
    return false;
}

bool encoder_update_user(uint8_t index, bool clockwise) {
    // Report detents only.  The macOS Agentpad client owns all encoder
    // actions, including brightness, seek, volume, zoom, and playback speed.
    // Do not emit QMK's native media/zoom keycodes here: doing so would make
    // playback-speed mode change the browser zoom at the same time.
    uint8_t pkt[AP_EPSIZE] = {0};
    pkt[0] = 0x82; // ENC_EVENT
    pkt[1] = index;
    pkt[2] = clockwise ? 1 : 0;
    pkt[3] = (uint8_t)get_highest_layer(layer_state);
    raw_hid_send(pkt, AP_EPSIZE);
    return false;
}
