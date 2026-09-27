"""Ownership-aware clipboard lease. Never discards unsupported user formats.

The lease lasts through runner verification, not a guessed sleep after Ctrl+V.
Snapshots remain only in the host/worker's memory and are never journaled.
"""
import win32clipboard as clipboard
import win32con
from ..contracts import AxisError

SUPPORTED = {win32con.CF_TEXT, win32con.CF_UNICODETEXT, win32con.CF_OEMTEXT, win32con.CF_LOCALE}


def replace_text(text, previous=None, *, check=None):
    try:
        clipboard.OpenClipboard()
    except Exception:
        raise AxisError("CLIPBOARD_BUSY", "Clipboard is in use")
    try:
        if previous:
            if clipboard.GetClipboardSequenceNumber() != previous["sequence"]:
                raise AxisError("CLIPBOARD_CHANGED", "Clipboard changed outside AXIS")
            original = previous["formats"]
        else:
            formats, current = [], 0
            while True:
                current = clipboard.EnumClipboardFormats(current)
                if not current: break
                formats.append(current)
            if set(formats)-SUPPORTED:
                raise AxisError("CLIPBOARD_UNSUPPORTED", "Clipboard contains rich/binary formats; use Unicode typing or explicitly change the clipboard first")
            original = [(kind, clipboard.GetClipboardData(kind)) for kind in formats]
        # Snapshot/enumeration may be slow. Refuse before the first write;
        # rollback and later restoration must remain possible after expiry.
        if check is not None:
            check()
        try:
            clipboard.EmptyClipboard()
            clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
        except Exception:
            # Clipboard remains locked: no other owner can be overwritten by
            # restoring the snapshot when a local SetClipboardData fails.
            clipboard.EmptyClipboard()
            for kind, data in original:
                clipboard.SetClipboardData(kind, data)
            raise AxisError("CLIPBOARD_WRITE_FAILED", "Clipboard write failed; snapshot restored")
        return {"formats": original, "sequence": clipboard.GetClipboardSequenceNumber()}
    finally:
        clipboard.CloseClipboard()


def restore(lease):
    if not lease: return
    clipboard.OpenClipboard()
    try:
        if clipboard.GetClipboardSequenceNumber() != lease["sequence"]:
            return  # A user/application now owns it; never overwrite their value.
        clipboard.EmptyClipboard()
        for kind, data in lease["formats"]:
            clipboard.SetClipboardData(kind, data)
    finally:
        clipboard.CloseClipboard()
