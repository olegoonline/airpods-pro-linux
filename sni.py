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
MENU_IFACE = "com.canonical.dbusmenu"
MENU_PATH = "/MenuBar"
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
            # Plasma draws this menu natively, so it closes on outside clicks
            # (a Qt menu under XWayland never sees clicks on Wayland surfaces).
            "Menu": dbus.ObjectPath(MENU_PATH),
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


class _Menu(dbus.service.Object):
    """com.canonical.dbusmenu: a flat menu of labels, checkmarks and separators."""

    def __init__(self, bus, bridge):
        super().__init__(bus, MENU_PATH)
        self.bridge = bridge
        self.items = []      # [{"id", "label", "enabled", "checked", "separator"}]
        self.revision = 1

    def _props(self, item):
        if item.get("separator"):
            return dbus.Dictionary({"type": "separator"}, signature="sv")
        props = {"label": item["label"], "enabled": bool(item.get("enabled", True))}
        if item.get("checked") is not None:
            props["toggle-type"] = "radio"
            props["toggle-state"] = dbus.Int32(1 if item["checked"] else 0)
        return dbus.Dictionary(props, signature="sv")

    def _node(self, item):
        return dbus.Struct((dbus.Int32(item["id"]), self._props(item), dbus.Array([], signature="v")),
                           signature="ia{sv}av")

    def set_items(self, items):
        self.items = items
        self.revision += 1
        self.LayoutUpdated(dbus.UInt32(self.revision), dbus.Int32(0))

    @dbus.service.method(MENU_IFACE, in_signature="iias", out_signature="u(ia{sv}av)")
    def GetLayout(self, parent_id, depth, names):
        children = dbus.Array([self._node(i) for i in self.items], signature="v")
        root = dbus.Struct((dbus.Int32(0), dbus.Dictionary({"children-display": "submenu"}, signature="sv"),
                            children), signature="ia{sv}av")
        return dbus.UInt32(self.revision), root

    @dbus.service.method(MENU_IFACE, in_signature="aias", out_signature="a(ia{sv})")
    def GetGroupProperties(self, ids, names):
        wanted = set(int(i) for i in ids)
        return dbus.Array([dbus.Struct((dbus.Int32(i["id"]), self._props(i)), signature="ia{sv}")
                           for i in self.items if not wanted or i["id"] in wanted], signature="(ia{sv})")

    @dbus.service.method(MENU_IFACE, in_signature="is", out_signature="v")
    def GetProperty(self, item_id, name):
        for i in self.items:
            if i["id"] == item_id:
                return self._props(i).get(name, "")
        return ""

    @dbus.service.method(MENU_IFACE, in_signature="isvu")
    def Event(self, item_id, event_id, data, timestamp):
        if event_id == "clicked":
            self.bridge.menu_clicked.emit(int(item_id))

    @dbus.service.method(MENU_IFACE, in_signature="a(isvu)", out_signature="ai")
    def EventGroup(self, events):
        for item_id, event_id, data, timestamp in events:
            self.Event(item_id, event_id, data, timestamp)
        return dbus.Array([], signature="i")

    @dbus.service.method(MENU_IFACE, in_signature="i", out_signature="b")
    def AboutToShow(self, item_id):
        return False

    @dbus.service.method(MENU_IFACE, in_signature="ai", out_signature="aiai")
    def AboutToShowGroup(self, ids):
        return dbus.Array([], signature="i"), dbus.Array([], signature="i")

    @dbus.service.signal(MENU_IFACE, signature="ui")
    def LayoutUpdated(self, revision, parent):
        pass

    @dbus.service.signal(MENU_IFACE, signature="a(ia{sv})a(ias)")
    def ItemsPropertiesUpdated(self, updated, removed):
        pass

    @dbus.service.method(PROPS_IFACE, in_signature="ss", out_signature="v")
    def Get(self, iface, name):
        return self.GetAll(iface)[name]

    @dbus.service.method(PROPS_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, iface):
        return dbus.Dictionary({"Version": dbus.UInt32(3), "TextDirection": "ltr", "Status": "normal",
                                "IconThemePath": dbus.Array([], signature="s")}, signature="sv")


class TrayItem(QObject):
    """Qt-side handle: signals carry the click position in global coordinates."""

    activated = Signal(int, int)    # left click
    secondary = Signal(int, int)    # middle click
    context = Signal(int, int)      # right click (only without a menu)
    menu_clicked = Signal(int)      # id of the DBusMenu entry

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
        self._menu = _Menu(bus, self)

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

    def set_menu(self, items):
        """items: dicts with id, label, enabled, checked (None for a plain entry) or separator."""
        items = [dict(i) for i in items]
        self._call(lambda: self._menu.set_items(items))

    def set_tooltip(self, title, text):
        def apply():
            self._item.props["ToolTip"] = dbus.Struct(
                ("", dbus.Array([], signature="(iiay)"), title, text), signature="sa(iiay)ss")
            self._item.NewToolTip()
        self._call(apply)
