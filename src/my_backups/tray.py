"""Small StatusNotifierItem implementation for cross-desktop tray support."""
from pathlib import Path

import gi
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, Gio, GLib

from .metadata import APP_ICON, APP_NAME


SNI_XML = """
<node>
  <interface name="org.kde.StatusNotifierItem">
    <property name="Category" type="s" access="read"/>
    <property name="Id" type="s" access="read"/>
    <property name="Title" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="WindowId" type="u" access="read"/>
    <property name="IconName" type="s" access="read"/>
    <property name="IconPixmap" type="a(iiay)" access="read"/>
    <property name="AttentionIconName" type="s" access="read"/>
    <property name="AttentionIconPixmap" type="a(iiay)" access="read"/>
    <property name="OverlayIconName" type="s" access="read"/>
    <property name="OverlayIconPixmap" type="a(iiay)" access="read"/>
    <property name="ToolTip" type="(sa(iiay)ss)" access="read"/>
    <property name="ItemIsMenu" type="b" access="read"/>
    <property name="Menu" type="o" access="read"/>
    <method name="ContextMenu"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
    <method name="Activate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
    <method name="SecondaryActivate"><arg type="i" direction="in"/><arg type="i" direction="in"/></method>
    <method name="Scroll"><arg type="i" direction="in"/><arg type="s" direction="in"/></method>
    <signal name="NewStatus"><arg type="s"/></signal>
    <signal name="NewIcon"/>
    <signal name="NewToolTip"/>
  </interface>
</node>
"""


def load_icon_pixmaps(icon_path=None, sizes=(16, 22, 32, 48, 64)):
    """Return SNI ARGB32 pixels so the desktop need not resolve an icon name."""
    source = Path(icon_path or Path(__file__).with_name("data") / "icon.png")
    pixmaps = []
    for size in sizes:
        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(
            str(source), size, size, True)
        pixels = bytes(pixbuf.get_pixels())
        rowstride = pixbuf.get_rowstride()
        channels = pixbuf.get_n_channels()
        argb = bytearray()
        for y_pos in range(pixbuf.get_height()):
            for x_pos in range(pixbuf.get_width()):
                offset = y_pos * rowstride + x_pos * channels
                red, green, blue = pixels[offset:offset + 3]
                alpha = pixels[offset + 3] if channels == 4 else 255
                argb.extend((alpha, red, green, blue))
        pixmaps.append((pixbuf.get_width(), pixbuf.get_height(), bytes(argb)))
    return pixmaps


class TrayIcon:
    PATH = "/StatusNotifierItem"

    def __init__(self, app):
        self.app = app
        self.connection = app.get_dbus_connection()
        self.registration_id = 0
        self.registered_with_watcher = False
        self.status = "Active"
        self.icon_pixmaps = load_icon_pixmaps()
        if self.connection is not None:
            info = Gio.DBusNodeInfo.new_for_xml(SNI_XML)
            self.registration_id = self.connection.register_object(
                self.PATH, info.interfaces[0], self._method_call,
                self._get_property, None)
            self._register_watcher()

    def _register_watcher(self):
        if self.connection is None:
            return False
        try:
            self.connection.call_sync(
                "org.kde.StatusNotifierWatcher", "/StatusNotifierWatcher",
                "org.kde.StatusNotifierWatcher", "RegisterStatusNotifierItem",
                GLib.Variant("(s)", (self.connection.get_unique_name(),)), None,
                Gio.DBusCallFlags.NONE, 500, None)
            self.registered_with_watcher = True
        except GLib.Error:
            self.registered_with_watcher = False
        return False

    def retry_registration(self):
        if not self.registered_with_watcher:
            self._register_watcher()
        return True

    def _get_property(self, _connection, _sender, _path, _interface, name):
        values = {
            "Category": GLib.Variant("s", "SystemServices"),
            "Id": GLib.Variant("s", APP_ICON),
            "Title": GLib.Variant("s", APP_NAME),
            "Status": GLib.Variant("s", self.status),
            "WindowId": GLib.Variant("u", 0),
            "IconName": GLib.Variant("s", APP_ICON),
            "IconPixmap": GLib.Variant("a(iiay)", self.icon_pixmaps),
            "AttentionIconName": GLib.Variant("s", "dialog-warning-symbolic"),
            "AttentionIconPixmap": GLib.Variant("a(iiay)", self.icon_pixmaps),
            "OverlayIconName": GLib.Variant("s", ""),
            "OverlayIconPixmap": GLib.Variant("a(iiay)", []),
            "ToolTip": GLib.Variant("(sa(iiay)ss)",
                                    (APP_ICON, self.icon_pixmaps, APP_NAME,
                                     "Running in the background")),
            "ItemIsMenu": GLib.Variant("b", False),
            "Menu": GLib.Variant("o", "/"),
        }
        return values.get(name)

    def _method_call(self, _connection, _sender, _path, _interface, method,
                     _parameters, invocation):
        if method == "Activate":
            GLib.idle_add(self.app.show_main_window)
        elif method in ("ContextMenu", "SecondaryActivate"):
            GLib.idle_add(self.app.show_tray_controller)
        invocation.return_value(None)

    def set_attention(self, attention):
        if self.connection is None or not self.registration_id:
            return
        status = "NeedsAttention" if attention else "Active"
        self.status = status
        self.connection.emit_signal(None, self.PATH, "org.kde.StatusNotifierItem",
                                    "NewStatus", GLib.Variant("(s)", (status,)))

    def close(self):
        if self.connection is not None and self.registration_id:
            self.connection.unregister_object(self.registration_id)
            self.registration_id = 0
