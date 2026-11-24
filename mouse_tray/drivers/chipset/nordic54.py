"""ATK mice using the 64-byte HID battery protocol.

A 64-byte report (ID 8) tagged with command 0x72, on a dedicated HID collection
(usage page 0xFF05). The Nordic 54L15-based ATK Zero and the NearLink NANO
receiver used by the ATK A9 Plus both support this battery query.

    write   08 7D 72 02 00 00 07 01 00 ...
    read    08 72 00 3A 00 07 01 64 16 11 00 ...

In the request, byte 2 is the command, byte 5 the link index and byte 6 the
sub-index (7 = battery). In the reply, byte 2 is a status (``0`` = the mouse
answered, ``1`` = it did not), byte 3 the payload length, bytes 5-6 echo the
request, byte 7 is the percent (0x64 = 100%) and bytes 8-9 the cell voltage in
millivolts, little-endian (0x1116 = 4374 mV). The observed requests use 0x7D in
byte 1. The ATK Zero also answers when that byte is 0x00, 0x7C or 0xFF.

The link index matters: ``0`` reaches a mouse on the cable, ``1`` a mouse behind
the dongle. With the wrong one the device either stays silent or replays a stale
answer flagged ``status=1``.

Both links report the percent at byte 7. The cable additionally gives the cell
voltage at bytes 8-9; over the air those two bytes hold junk, so only the percent
is read there. The gauge is voltage-based, so on the cable it saturates at 100%
during the constant-voltage phase (~4.37 V) while the mouse reads a few percent
lower once unplugged -- that is the gauge, not a stub value.

On the ATK Zero, sub-index 8 gives the charge state (0x02 on the cable and
0x00 off it). Sub-indices 9, 0x1A, 0x1C, 0x20, 0x22 and 0x23 hold config.
Its dongle relays only the battery query.

The ATK Zero receiver's PID depends on the pairing channel, so the model ships
with several different dongles ("8k dongle-L0" at 0x124F, "8k dongle-L1" at
0x1155, and so on). The A9 Plus is supported via the shared NearLink NANO
receiver (0x1216).

The older Nordic 52840 mice (ATK/VXE/VGN/Zaopin/Scyrox) speak a simpler 17-byte
protocol -- see :mod:`~mouse_tray.drivers.chipset.nordic52`. Reference implementation:
https://github.com/Fan4Metal/ATK_tray
"""

from __future__ import annotations

import logging
from typing import ClassVar

from ...battery import BatteryStatus
from ..driver import MouseModel, register
from ..hid import HidDriver

log = logging.getLogger(__name__)

_USAGE_PAGE = 0xFF05
_USAGE = 0x0001
_CMD = 0x72
_BATTERY = 0x07  # sub-index of the battery query

# The dongle is reachable but the mouse behind it is not answering -- as with
# Logitech receivers, a sleeping mouse is indistinguishable from an absent one.
_ASLEEP = BatteryStatus(present=True, asleep=True)


def _model(name: str, vid: int, pid_wireless: int, pid_wired: int | None) -> MouseModel:
    return MouseModel(name, vid, pid_wireless, pid_wired, _USAGE_PAGE, _USAGE)


@register
class Nordic54Driver(HidDriver):
    vendor = "ATK"
    models: ClassVar[list[MouseModel]] = [
        # One row per receiver PID: the same mouse comes with different dongles
        # depending on the pairing channel.
        _model("ATK Zero", 0x373B, 0x1155, 0x1154),  # "8k dongle-L1"
        _model("ATK Zero", 0x373B, 0x124F, 0x1154),  # "8k dongle-L0"
        _model("ATK A9 Plus / NearLink NANO", 0x373B, 0x1216, None),
    ]

    def read_status(self) -> BatteryStatus:
        wired = self._connected_wired()
        report = [0] * 64
        report[0] = 0x08  # report ID
        report[1] = 0x7D
        report[2] = _CMD
        report[3] = 0x02
        report[5] = 0x00 if wired else 0x01  # link index: cable / dongle
        report[6] = _BATTERY
        report[7] = 0x01
        res = self._transact(report, 64, feature=False, delay=0.1)
        if res is None:
            return BatteryStatus.absent()
        if len(res) < 10 or res[1] != _CMD or res[5] != _BATTERY or res[2] != 0x00:
            # Answered, but not by the mouse -- it is asleep or out of range.
            log.info("%s no answer from the mouse: %s", self.name, res[:8])
            return _ASLEEP

        percent = res[7]
        if not wired:
            log.info("%s battery=%s (wireless)", self.name, percent)
            return BatteryStatus(present=True, percent=percent, asleep=False)

        millivolts = res[8] | (res[9] << 8)
        log.info("%s battery=%s (wired, %s mV)", self.name, percent, millivolts)
        return BatteryStatus(
            present=True,
            percent=percent,
            charging=percent < 100,
            full=percent >= 100,
            asleep=False,
        )
