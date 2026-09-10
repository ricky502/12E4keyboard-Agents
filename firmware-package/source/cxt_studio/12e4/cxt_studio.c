// Copyright 2023 Colin Kinloch (@ColinKinloch)
// SPDX-License-Identifier: GPL-2.0-or-later

#include "quantum.h"

#ifdef ENCODER_ENABLE
bool encoder_update_kb(uint8_t index, bool clockwise) {
    // Agentpad owns all four encoder actions in its Raw HID callback.  Do not
    // append this board's legacy volume/RGB keycodes after forwarding an event.
    return encoder_update_user(index, clockwise);
}
#endif
