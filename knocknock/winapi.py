"""Low-level Windows API wrappers: synthetic keystrokes, clipboard sequence numbers, hotkey parsing.

Everything goes through ctypes, so pywin32 is not required.
"""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from typing import Optional, Tuple

from . import i18n

user32 = ctypes.WinDLL("user32", use_last_error=True)

# ---------------------------------------------------------------- constants
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_EXTENDEDKEY = 0x0001

VK_CONTROL = 0x11
VK_SHIFT = 0x10
VK_MENU = 0x12  # Alt
VK_LWIN = 0x5B
VK_RWIN = 0x5C
VK_C = 0x43
VK_ESCAPE = 0x1B

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

LLKHF_INJECTED = 0x00000010


# ---------------------------------------------------------------- structs
class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
user32.SendInput.restype = wintypes.UINT


# ---------------------------------------------------------------- synthetic keystrokes
def _key_event(vk: int, up: bool = False) -> INPUT:
    ev = INPUT()
    ev.type = INPUT_KEYBOARD
    ev.ki = KEYBDINPUT(
        wVk=vk,
        wScan=0,
        dwFlags=KEYEVENTF_KEYUP if up else 0,
        time=0,
        dwExtraInfo=None,
    )
    return ev


def send_keys(*vks: int, hold: float = 0.012) -> None:
    """Press several keys in order, then release them in reverse order."""
    events = [_key_event(vk, False) for vk in vks]
    events += [_key_event(vk, True) for vk in reversed(vks)]
    array = (INPUT * len(events))(*events)
    user32.SendInput(len(events), array, ctypes.sizeof(INPUT))
    time.sleep(hold)


def send_ctrl_c() -> None:
    """Send Ctrl+C to the current foreground window."""
    send_keys(VK_CONTROL, VK_C)


def clipboard_sequence() -> int:
    """Clipboard change sequence number, used to tell whether a copy really happened."""
    return int(user32.GetClipboardSequenceNumber())


# ---------------------------------------------------------------- hotkey parsing
_NAMED_KEYS = {
    "ESC": 0x1B, "ESCAPE": 0x1B, "TAB": 0x09, "SPACE": 0x20,
    "ENTER": 0x0D, "RETURN": 0x0D, "BACKSPACE": 0x08, "DELETE": 0x2E,
    "HOME": 0x24, "END": 0x23, "PAGEUP": 0x21, "PAGEDOWN": 0x22,
    "LEFT": 0x25, "UP": 0x26, "RIGHT": 0x27, "DOWN": 0x28,
    "`": 0xC0, "-": 0xBD, "=": 0xBB, "[": 0xDB, "]": 0xDD,
    "\\": 0xDC, ";": 0xBA, "'": 0xDE, ",": 0xBC, ".": 0xBE, "/": 0xBF,
}
for _i in range(1, 25):
    _NAMED_KEYS[f"F{_i}"] = 0x6F + _i  # F1 = 0x70


def parse_hotkey(text: str) -> Optional[Tuple[int, int]]:
    """Parse "ctrl+alt+a" into (modifiers, virtual key code). Returns None if it cannot be parsed."""
    if not text or not text.strip():
        return None
    mods = 0
    vk: Optional[int] = None
    for raw in text.replace(" ", "").split("+"):
        token = raw.strip().lower()
        if not token:
            continue
        if token in ("ctrl", "control"):
            mods |= MOD_CONTROL
        elif token in ("alt", "menu"):
            mods |= MOD_ALT
        elif token in ("shift",):
            mods |= MOD_SHIFT
        elif token in ("win", "super", "meta", "cmd"):
            mods |= MOD_WIN
        elif token.upper() in _NAMED_KEYS:
            vk = _NAMED_KEYS[token.upper()]
        elif len(token) == 1 and token.isalnum():
            vk = ord(token.upper())
        else:
            return None
    if vk is None or mods == 0:
        return None
    return mods, vk


def format_hotkey(text: str) -> str:
    """Format the hotkey string from the config into a presentable label."""
    if not text:
        return i18n.t("hotkey.unset")
    return " + ".join(part.strip().upper() if len(part.strip()) > 1 else part.strip().upper()
                      for part in text.split("+"))
