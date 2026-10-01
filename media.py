"""Pause / resume desktop media players over MPRIS (D-Bus), for ear detection."""

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
