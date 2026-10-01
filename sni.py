"""Minimal StatusNotifierItem (KDE/freedesktop tray icon) for a Qt app.

QSystemTrayIcon drops the click position that Plasma sends with Activate(x, y);
the tray widget needs it to open right under the icon, so the item is exported
here directly with dbus-python. D-Bus runs on a GLib loop in a background thread;
calls are forwarded to the Qt thread through queued signals.
"""

import os
import threading

import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage

ITEM_IFACE = "org.kde.StatusNotifierItem"
WATCHER = "org.kde.StatusNotifierWatcher"
PROPS_IFACE = "org.freedesktop.DBus.Properties"
PATH = "/StatusNotifierItem"


def _pixmaps(images):
    """QImages → a(iiay) in ARGB32 network byte order, as the spec wants."""
    out = []
    for img in images:
        img = img.convertToFormat(QImage.Format_ARGB32)
        w, h = img.width(), img.height()
        raw = bytes(img.constBits())[: w * h * 4]
        # QImage ARGB32 is native-endian (BGRA on little-endian); spec needs ARGB.
        argb = bytearray(len(raw))
        argb[0::4], argb[1::4], argb[2::4], argb[3::4] = raw[3::4], raw[2::4], raw[1::4], raw[0::4]
        out.append(dbus.Struct((dbus.Int32(w), dbus.Int32(h), dbus.ByteArray(bytes(argb))), signature="iiay"))
    return dbus.Array(out, signature="(iiay)")


class _Item(dbus.service.Object):
    def __init__(self, bus, bridge, app_id, title):
        super().__init__(bus, PATH)
        self.bridge = bridge
        self.props = {
            "Category": "Hardware",
            "Id": app_id,
            "Title": title,
            "Status": "Active",
            "WindowId": dbus.Int32(0),
            "IconName": "",
            "IconPixmap": dbus.Array([], signature="(iiay)"),
            "OverlayIconName": "",
            "OverlayIconPixmap": dbus.Array([], signature="(iiay)"),
            "AttentionIconName": "",
            "AttentionIconPixmap": dbus.Array([], signature="(iiay)"),
            "AttentionMovieName": "",
            "ToolTip": dbus.Struct(("", dbus.Array([], signature="(iiay)"), title, ""), signature="sa(iiay)ss"),
            "ItemIsMenu": False,
            "Menu": dbus.ObjectPath("/NO_DBUSMENU"),
        }

    # -- org.kde.StatusNotifierItem ------------------------------------------
    @dbus.service.method(ITEM_IFACE, in_signature="ii")
    def Activate(self, x, y):
        self.bridge.activated.emit(int(x), int(y))

    @dbus.service.method(ITEM_IFACE, in_signature="ii")
    def SecondaryActivate(self, x, y):
        self.bridge.secondary.emit(int(x), int(y))

    @dbus.service.method(ITEM_IFACE, in_signature="ii")
    def ContextMenu(self, x, y):
        self.bridge.context.emit(int(x), int(y))

    @dbus.service.method(ITEM_IFACE, in_signature="is")
    def Scroll(self, delta, orientation):
        pass

    @dbus.service.signal(ITEM_IFACE)
    def NewIcon(self):
        pass

    @dbus.service.signal(ITEM_IFACE)
    def NewToolTip(self):
        pass

    @dbus.service.signal(ITEM_IFACE)
    def NewTitle(self):
        pass

    @dbus.service.signal(ITEM_IFACE, signature="s")
    def NewStatus(self, status):
        pass

    # -- org.freedesktop.DBus.Properties --------------------------------------
    @dbus.service.method(PROPS_IFACE, in_signature="ss", out_signature="v")
    def Get(self, iface, name):
        return self.props[name]

    @dbus.service.method(PROPS_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, iface):
        return dbus.Dictionary(self.props, signature="sv")


class TrayItem(QObject):
    """Qt-side handle: signals carry the click position in global coordinates."""

    activated = Signal(int, int)    # left click
    secondary = Signal(int, int)    # middle click
    context = Signal(int, int)      # right click

    def __init__(self, app_id, title):
        super().__init__()
        self._ready = threading.Event()
        self._item = None
        threading.Thread(target=self._run, args=(app_id, title), daemon=True).start()
        self._ready.wait(5)

    def _run(self, app_id, title):
        DBusGMainLoop(set_as_default=True)
        self._loop = GLib.MainLoop()
        bus = dbus.SessionBus()
        name = f"org.kde.StatusNotifierItem-{os.getpid()}-1"
        self._name = dbus.service.BusName(name, bus)
        self._item = _Item(bus, self, app_id, title)

        def register():
            try:
                bus.get_object(WATCHER, "/StatusNotifierWatcher").RegisterStatusNotifierItem(
                    name, dbus_interface=WATCHER)
            except dbus.DBusException:
                pass  # no tray host yet; re-registered when the watcher appears
            return False

        # Plasma restarts re-create the watcher; register again whenever it shows up.
        bus.watch_name_owner(WATCHER, lambda owner: owner and GLib.idle_add(register))
        self._ready.set()
        self._loop.run()

    def _call(self, fn):
        GLib.idle_add(lambda: (fn(), False)[1])

    def set_icon(self, images):
        """images: QImages of several sizes."""
        data = _pixmaps(images)

        def apply():
            self._item.props["IconPixmap"] = data
            self._item.NewIcon()
        self._call(apply)

    def set_tooltip(self, title, text):
        def apply():
            self._item.props["ToolTip"] = dbus.Struct(
                ("", dbus.Array([], signature="(iiay)"), title, text), signature="sa(iiay)ss")
            self._item.NewToolTip()
        self._call(apply)
