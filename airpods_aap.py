"""Apple Accessory Protocol (AAP) client for AirPods, shared by the CLI and the tray app.

Speaks AAP over L2CAP PSM 0x1001, as documented by LibrePods
(https://github.com/kavishdevar/librepods/blob/main/docs/AAP%20Definitions.md).
Only the Python standard library is used.
"""

import os
import re
import select
import socket
import subprocess
import time

PSM = 0x1001
APPLE_VENDOR = "004C"

HANDSHAKE = bytes.fromhex("00000400010002000000000000000000")
SET_FEATURES = bytes.fromhex("040004004d00d700000000000000")  # unlocks Adaptive / CA
REQUEST_NOTIFICATIONS = bytes.fromhex("040004000f00ffffffffff")

CONTROL_PREFIX = bytes.fromhex("040004000900")
BATTERY_PREFIX = bytes.fromhex("040004000400")
EAR_PREFIX = bytes.fromhex("040004000600")
METADATA_PREFIX = bytes.fromhex("040004001d00")

CMD_LISTENING_MODE = 0x0D
CMD_CONVERSATIONAL_AWARENESS = 0x28
CMD_ALLOW_OFF_MODE = 0x34  # 0x01 lets the "Off" listening mode be selected
CMD_ONE_BUD_ANC = 0x1B     # 0x01 keeps noise cancellation with one bud in (0x02: drops to transparency)

MODES = {"off": 1, "anc": 2, "transparency": 3, "adaptive": 4}
MODE_ALIASES = {
    "nc": "anc", "noise": "anc", "noise-cancellation": "anc",
    "t": "transparency", "trans": "transparency",
    "a": "adaptive", "adapt": "adaptive",
}
MODE_TITLES = {
    1: "Off",
    2: "Noise Cancellation",
    3: "Transparency",
    4: "Adaptive",
}
DEFAULT_CYCLE = ["anc", "transparency"]

LEFT, RIGHT, CASE = 0x04, 0x02, 0x08
BATTERY_PARTS = {LEFT: "Left", RIGHT: "Right", CASE: "Case"}
BATTERY_CHARGING, BATTERY_DISCONNECTED = 0x01, 0x04
EAR_STATUS = {0x00: "in ear", 0x01: "out of ear", 0x02: "in case"}


class AirPodsError(Exception):
    pass


def _apple_audio_devices(which):
    """MACs of Apple audio devices from `bluetoothctl devices <which>`."""
    try:
        out = subprocess.run(["bluetoothctl", "devices", which],
                             capture_output=True, text=True, timeout=5).stdout
        macs = []
        for mac in re.findall(r"Device ((?:[0-9A-F]{2}:){5}[0-9A-F]{2})", out):
            info = subprocess.run(["bluetoothctl", "info", mac],
                                  capture_output=True, text=True, timeout=5).stdout
            if f"Modalias: bluetooth:v{APPLE_VENDOR}" in info and "Audio Sink" in info:
                macs.append(mac)
        return macs
    except (OSError, subprocess.TimeoutExpired) as e:
        raise AirPodsError(f"bluetoothctl is unavailable: {e}")


def find_airpods():
    """Return the MAC of the first connected Apple audio device."""
    env = os.environ.get("AIRPODS_MAC")
    if env:
        return env
    macs = _apple_audio_devices("Connected")
    if macs:
        return macs[0]
    raise AirPodsError("No connected AirPods found")


def connect_bluetooth():
    """Ask BlueZ to connect the paired AirPods (audio profiles included)."""
    macs = [os.environ["AIRPODS_MAC"]] if os.environ.get("AIRPODS_MAC") else _apple_audio_devices("Paired")
    if not macs:
        raise AirPodsError("No paired AirPods found")
    for mac in macs:
        try:
            out = subprocess.run(["bluetoothctl", "--timeout", "20", "connect", mac],
                                 capture_output=True, text=True, timeout=25).stdout
        except (OSError, subprocess.TimeoutExpired) as e:
            raise AirPodsError(f"Could not connect to {mac}: {e}")
        if "Connection successful" in out:
            return mac
    raise AirPodsError("AirPods did not connect. Open the case near the computer")


class AirPods:
    """AAP connection. Use as a context manager, or call open()/close()."""

    def __init__(self, mac):
        self.mac = mac
        self.sock = None
        self.name = None
        self.mode = None
        self.ca = None
        self.battery = {}  # part -> (level, status)
        self.ears = None
        self.controls = {}  # last value the AirPods reported per control command

    def open(self):
        self.sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_SEQPACKET,
                                  socket.BTPROTO_L2CAP)
        self.sock.settimeout(5)
        try:
            self.sock.connect((self.mac, PSM))
            for packet in (HANDSHAKE, SET_FEATURES, REQUEST_NOTIFICATIONS):
                self.sock.send(packet)
                time.sleep(0.05)
        except OSError as e:
            self.sock.close()
            raise AirPodsError(f"Could not connect to {self.mac}: {e}")
        return self

    def close(self):
        if self.sock:
            self.sock.close()

    def __enter__(self):
        return self.open()

    def __exit__(self, *exc):
        self.close()

    def fileno(self):
        return self.sock.fileno()

    def parse(self, data):
        """Update state from one incoming packet."""
        if data.startswith(CONTROL_PREFIX) and len(data) >= 8:
            self.controls[data[6]] = data[7]
            if data[6] == CMD_LISTENING_MODE:
                self.mode = data[7]
            elif data[6] == CMD_CONVERSATIONAL_AWARENESS:
                self.ca = data[7] == 0x01
        elif data.startswith(BATTERY_PREFIX) and len(data) >= 7:
            for i in range(data[6]):
                part = data[7 + i * 5: 12 + i * 5]
                if len(part) == 5:
                    self.battery[part[0]] = (part[2], part[3])
        elif data.startswith(EAR_PREFIX) and len(data) >= 8:
            self.ears = (data[6], data[7])
        elif data.startswith(METADATA_PREFIX):
            # Name is the first NUL-terminated string after a 5-byte preamble.
            self.name = data[11:].split(b"\0", 1)[0].decode("utf-8", "replace") or None

    def read_packet(self):
        """Read and parse one packet; raises AirPodsError if the link is gone."""
        try:
            data = self.sock.recv(1024)
        except BlockingIOError:
            raise  # non-blocking socket drained; caller decides
        except OSError as e:
            raise AirPodsError(f"Connection lost: {e}")
        if not data:
            raise AirPodsError("Connection closed")
        self.parse(data)
        return data

    def pump(self, seconds, until=None):
        """Read packets for up to `seconds`, stopping early once until() is true."""
        deadline = time.monotonic() + seconds
        while (left := deadline - time.monotonic()) > 0:
            if until and until():
                return True
            ready, _, _ = select.select([self.sock], [], [], left)
            if ready:
                self.read_packet()
        return bool(until and until())

    def sync(self):
        self.pump(3, lambda: self.mode is not None and self.battery)

    def send_control(self, cmd, value):
        self.sock.send(CONTROL_PREFIX + bytes([cmd, value, 0, 0, 0]))

    def send_mode(self, mode):
        self.send_control(CMD_LISTENING_MODE, mode)

    def send_ca(self, enabled):
        self.send_control(CMD_CONVERSATIONAL_AWARENESS, 0x01 if enabled else 0x02)

    def set_mode(self, mode):
        self.send_mode(mode)
        self.pump(2, lambda: self.mode == mode)
        return self.mode

    def set_ca(self, enabled):
        self.send_ca(enabled)
        self.pump(1.5, lambda: self.ca == enabled)
        return self.ca

    def battery_level(self, part):
        """Level in percent, or None when that part isn't reporting."""
        level, status = self.battery.get(part, (None, BATTERY_DISCONNECTED))
        return None if status == BATTERY_DISCONNECTED else level

    def battery_text(self):
        parts = []
        for part in (LEFT, RIGHT, CASE):
            level = self.battery_level(part)
            if level is not None:
                charging = self.battery[part][1] == BATTERY_CHARGING
                parts.append(f"{BATTERY_PARTS[part]} {level}%" + (" ⚡" if charging else ""))
        return ", ".join(parts) or "unknown"


def resolve_mode(name):
    name = MODE_ALIASES.get(name.lower(), name.lower())
    if name not in MODES:
        raise AirPodsError(f"Unknown mode: {name}")
    return MODES[name]
