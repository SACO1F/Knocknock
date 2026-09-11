"""Retrieve whatever is "selected" on screen: text via clipboard copy, images via the clipboard image."""
from __future__ import annotations

import time
from typing import Optional

from PySide6.QtGui import QGuiApplication, QImage

from . import winapi


def clipboard_text() -> str:
    cb = QGuiApplication.clipboard()
    return (cb.text() or "").strip()


def clipboard_image() -> Optional[QImage]:
    cb = QGuiApplication.clipboard()
    image = cb.image()
    return image if image is not None and not image.isNull() else None


def set_clipboard_text(text: str) -> None:
    QGuiApplication.clipboard().setText(text)


def grab_selected_text(timeout: float = 0.45, restore: bool = False) -> str:
    """Grab the text selected in the foreground app by synthesising Ctrl+C.

    How it works: record the clipboard sequence number -> send Ctrl+C -> wait for
    the number to change -> read the text. If it never changes, the user had
    nothing selected, so we fall back to the text already on the clipboard.
    """
    previous_text = clipboard_text()
    sequence = winapi.clipboard_sequence()

    winapi.send_ctrl_c()

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if winapi.clipboard_sequence() != sequence:
            break
        time.sleep(0.015)

    # Give the target app a moment to actually write the data to the clipboard
    time.sleep(0.04)
    text = clipboard_text()

    if text and text != previous_text:
        if restore and previous_text:
            # Restore after a delay so the user can still paste immediately
            QGuiApplication.clipboard().setText(previous_text)
        return text
    return ""


def capture_selection(restore_clipboard: bool = False) -> dict:
    """Unified "read the selection" entry point; returns {"text": str, "image": QImage|None}."""
    text = grab_selected_text(restore=restore_clipboard)
    if text:
        return {"text": text, "image": None}

    image = clipboard_image()
    if image is not None:
        return {"text": "", "image": image}

    return {"text": "", "image": None}
