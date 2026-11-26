"""Draw percentage text across the notification button at its natural width."""

from __future__ import annotations

import ctypes
from ctypes import wintypes

import wx


class _IconIdentifier(ctypes.Structure):
    _fields_ = (
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uID", wintypes.UINT),
        ("guidItem", ctypes.c_byte * 16),
    )


class _BlendFunction(ctypes.Structure):
    _fields_ = (
        ("operation", ctypes.c_byte),
        ("flags", ctypes.c_byte),
        ("alpha", ctypes.c_ubyte),
        ("format", ctypes.c_byte),
    )


_user32 = ctypes.WinDLL("user32", use_last_error=True)
_shell32 = ctypes.WinDLL("shell32", use_last_error=True)
_shell32.Shell_NotifyIconGetRect.argtypes = (ctypes.POINTER(_IconIdentifier), ctypes.POINTER(wintypes.RECT))
_shell32.Shell_NotifyIconGetRect.restype = ctypes.c_long
_user32.GetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int)
_user32.GetWindowLongW.restype = wintypes.LONG
_user32.SetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int, wintypes.LONG)
_user32.SetWindowLongW.restype = wintypes.LONG
_user32.WindowFromPoint.argtypes = (wintypes.POINT,)
_user32.WindowFromPoint.restype = wintypes.HWND
_user32.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
_user32.GetAncestor.restype = wintypes.HWND
_user32.GetParent.argtypes = (wintypes.HWND,)
_user32.GetParent.restype = wintypes.HWND
_user32.SetParent.argtypes = (wintypes.HWND, wintypes.HWND)
_user32.SetParent.restype = wintypes.HWND
_user32.ScreenToClient.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.POINT))
_user32.ScreenToClient.restype = wintypes.BOOL
_user32.SetWindowPos.argtypes = (
    wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
    ctypes.c_int, ctypes.c_int, wintypes.UINT,
)
_user32.SetWindowPos.restype = wintypes.BOOL
_user32.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
_user32.GetClassNameW.restype = ctypes.c_int
_user32.UpdateLayeredWindow.argtypes = (
    wintypes.HWND, wintypes.HDC, ctypes.POINTER(wintypes.POINT), ctypes.POINTER(wintypes.SIZE),
    wintypes.HDC, ctypes.POINTER(wintypes.POINT), wintypes.DWORD,
    ctypes.POINTER(_BlendFunction), wintypes.DWORD,
)
_user32.UpdateLayeredWindow.restype = wintypes.BOOL

_TRAY_CLASSES = {
    "Shell_TrayWnd", "Shell_SecondaryTrayWnd", "NotifyIconOverflowWindow",
    "TopLevelWindowForOverflowXamlIsland",
}
_GWL_STYLE = -16
_GWL_EXSTYLE = -20
_WS_CHILD = 0x40000000
_WS_POPUP = 0x80000000
_WS_EX_LAYERED = 0x80000
_WS_EX_TRANSPARENT = 0x20
_WS_EX_NOACTIVATE = 0x08000000
_WS_EX_TOOLWINDOW = 0x80
_SWP_NOACTIVATE = 0x10
_ULW_ALPHA = 2


class TrayText(wx.Frame):
    """A transparent, click-through label centered on this app's tray button."""

    def __init__(self):
        super().__init__(
            None, title="Mouse Tray percentage",
            style=wx.FRAME_NO_TASKBAR | wx.BORDER_NONE,
        )
        # Layered alpha, click-through input, and no activation or Alt-Tab entry.
        style = _user32.GetWindowLongW(self.GetHandle(), _GWL_EXSTYLE)
        style |= _WS_EX_LAYERED | _WS_EX_TRANSPARENT | _WS_EX_NOACTIVATE | _WS_EX_TOOLWINDOW
        _user32.SetWindowLongW(self.GetHandle(), _GWL_EXSTYLE, style)
        self._placed: tuple | None = None

    def _icon_rect(self) -> wintypes.RECT | None:
        for window in wx.GetTopLevelWindows():
            # wxWidgets 3.2 uses uID 99 for its hidden taskbar helper window.
            identifier = _IconIdentifier(ctypes.sizeof(_IconIdentifier), window.GetHandle(), 99)
            rect = wintypes.RECT()
            if _shell32.Shell_NotifyIconGetRect(ctypes.byref(identifier), ctypes.byref(rect)) == 0:
                return rect
        return None

    def _host_at(self, rect: wintypes.RECT) -> int | None:
        point = wintypes.POINT((rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2)
        window = _user32.GetAncestor(_user32.WindowFromPoint(point), 2)
        class_name = ctypes.create_unicode_buffer(128)
        _user32.GetClassNameW(window, class_name, len(class_name))
        return window if class_name.value in _TRAY_CLASSES else None

    def place(self, bitmap: wx.Bitmap) -> bool:  # noqa: PLR0911 -- each native failure hides the label
        """Show the label on an exposed tray button, returning whether it fits."""
        rect = self._icon_rect()
        host = self._host_at(rect) if rect is not None else None
        if host is None:
            self.Hide()
            self._placed = None
            return False

        if _user32.GetParent(self.GetHandle()) != host:
            # A child moves and clips with the taskbar throughout auto-hide.
            # Keep the label hidden unless Windows accepts the attachment.
            style = _user32.GetWindowLongW(self.GetHandle(), _GWL_STYLE)
            _user32.SetWindowLongW(self.GetHandle(), _GWL_STYLE, (style & ~_WS_POPUP) | _WS_CHILD)
            _user32.SetParent(self.GetHandle(), host)
            if _user32.GetParent(self.GetHandle()) != host:
                self.Hide()
                self._placed = None
                return False

        width, height = bitmap.GetWidth(), bitmap.GetHeight()
        position = wintypes.POINT(
            (rect.left + rect.right - width) // 2,
            (rect.top + rect.bottom - height) // 2,
        )
        if not _user32.ScreenToClient(host, ctypes.byref(position)):
            self.Hide()
            self._placed = None
            return False
        placement = (host, position.x, position.y, id(bitmap))
        if placement == self._placed and self.IsShown():
            return True

        if not _user32.SetWindowPos(
            self.GetHandle(), None, position.x, position.y, width, height, _SWP_NOACTIVATE,
        ):
            self.Hide()
            self._placed = None
            return False
        dc = wx.MemoryDC(bitmap)
        try:
            success = _user32.UpdateLayeredWindow(
                self.GetHandle(), None, None,
                ctypes.byref(wintypes.SIZE(width, height)), dc.GetHandle(),
                ctypes.byref(wintypes.POINT(0, 0)), 0,
                ctypes.byref(_BlendFunction(0, 0, 255, 1)), _ULW_ALPHA,
            )
        finally:
            dc.SelectObject(wx.NullBitmap)
        if not success:
            self.Hide()
            self._placed = None
            return False
        self.ShowWithoutActivating()
        self._placed = placement
        return True
