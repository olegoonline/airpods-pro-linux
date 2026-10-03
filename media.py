"""Pause / resume desktop media players over MPRIS (D-Bus), for ear detection,
and a soft one-ear chime played straight to the AirPods sink."""

import array
import math
import os
import subprocess
import tempfile
import threading
import wave

import dbus

MPRIS = "org.mpris.MediaPlayer2."
PLAYER_IFACE = "org.mpris.MediaPlayer2.Player"


def _players(bus):
    return [n for n in bus.list_names() if n.startswith(MPRIS)]


def pause_playing():
    """Pause every player that is playing; return their bus names for resume()."""
    paused = []
    try:
        bus = dbus.SessionBus()
        for name in _players(bus):
            try:
                obj = bus.get_object(name, "/org/mpris/MediaPlayer2")
                status = obj.Get(PLAYER_IFACE, "PlaybackStatus",
                                 dbus_interface="org.freedesktop.DBus.Properties", timeout=1)
                if status == "Playing":
                    obj.Pause(dbus_interface=PLAYER_IFACE, timeout=1)
                    paused.append(str(name))
            except dbus.DBusException:
                continue
    except dbus.DBusException:
        pass
    return paused


def resume(names):
    """Resume only the players pause_playing() stopped (and that still exist)."""
    try:
        bus = dbus.SessionBus()
        alive = set(_players(bus))
        for name in names:
            if name in alive:
                try:
                    bus.get_object(name, "/org/mpris/MediaPlayer2").Play(
                        dbus_interface=PLAYER_IFACE, timeout=1)
                except dbus.DBusException:
                    continue
    except dbus.DBusException:
        pass


# ------------------------------------------------------------------ chime

RATE = 48000
_chimes = {}  # side -> wav path


def _chime_file(side):
    """Short soft sine with a smooth envelope, only in the "left" or "right" channel."""
    if side not in _chimes:
        lead, length = int(RATE * 0.15), int(RATE * 0.35)  # silence lets a suspended sink wake up
        frames = array.array("h", [0] * (lead + length) * 2)
        ch = 0 if side == "left" else 1
        for n in range(length):
            t = n / RATE
            env = math.sin(math.pi * min(1.0, t / 0.03) / 2) * math.exp(-t * 9)
            v = env * (math.sin(2 * math.pi * 523 * t) + 0.3 * math.sin(2 * math.pi * 1046 * t))
            frames[(lead + n) * 2 + ch] = int(v * 0.18 * 32767)
        path = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir(),
                            f"airpods-chime-{side}.wav")
        with wave.open(path, "wb") as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(frames.tobytes())
        _chimes[side] = path
    return _chimes[side]


def _airpods_sink(mac):
    prefix = "bluez_output." + mac.replace(":", "_")
    try:
        out = subprocess.run(["pactl", "list", "short", "sinks"],
                             capture_output=True, text=True, timeout=2).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) > 1 and parts[1].startswith(prefix):
            return parts[1]
    return None


def chime(mac, side):
    """Play the chime in one earbud; does nothing if the AirPods have no audio sink."""
    def run():
        sink = _airpods_sink(mac)
        if sink:
            subprocess.run(["pw-play", "--target", sink, _chime_file(side)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
    threading.Thread(target=run, daemon=True).start()
