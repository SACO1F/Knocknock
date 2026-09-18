"""Global input monitoring: double-tap detection plus system-wide hotkey registration.

Implementation: a low-level keyboard hook (WH_KEYBOARD_LL) together with
RegisterHotKey, both running on a dedicated thread's message loop and reporting
back to the main thread through Qt signals. No administrator rights required.

Which modifier is double-tapped is a setting (`hotkeys.double_tap_key`), not a
constant: which key is least disruptive depends on what you do all day. Ctrl and
Alt are both held for things users do constantly — multi-selecting files, menu
mnemonics — so neither is right for everyone, and any single key is accepted.
The parsing and the virtual-key codes live in winapi.
"""
from __future__ import annotations

import ctypes
import threading
import time
from ctypes import wintypes
from typing import Dict, List, Optional, Set

from PySide6.QtCore import QObject, Signal

from . import winapi
from .winapi import DOUBLE_TAP_DEFAULT_KEY, LLKHF_INJECTED

user32 = winapi.user32
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


HOOKPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
)

user32.SetWindowsHookExW.argtypes = (ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD)
user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.CallNextHookEx.argtypes = (wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
user32.CallNextHookEx.restype = ctypes.c_ssize_t
user32.UnhookWindowsHookEx.argtypes = (wintypes.HHOOK,)
user32.UnhookWindowsHookEx.restype = wintypes.BOOL
user32.RegisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT)
user32.RegisterHotKey.restype = wintypes.BOOL
user32.UnregisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int)
user32.UnregisterHotKey.restype = wintypes.BOOL
user32.GetMessageW.argtypes = (ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT)
user32.GetMessageW.restype = ctypes.c_int
user32.PostThreadMessageW.argtypes = (wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
user32.PostThreadMessageW.restype = wintypes.BOOL
kernel32.GetModuleHandleW.argtypes = (wintypes.LPCWSTR,)
kernel32.GetModuleHandleW.restype = wintypes.HMODULE


def vk_group_for(name: str) -> Set[int]:
    """Virtual-key codes that count as `name`, falling back to the default key."""
    return winapi.double_tap_key_codes(name)


class GlobalInput(QObject):
    """Global input listener.

    Signals:
        double_tap()           -- the configured modifier was tapped twice
        hotkey(name: str)      -- a named system hotkey was pressed; `name` is the
                                  name it was registered under
    """

    double_tap = Signal()
    hotkey = Signal(str)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._interval = 0.42
        self._vk_group: Set[int] = vk_group_for(DOUBLE_TAP_DEFAULT_KEY)
        self._hotkeys: List[tuple] = []          # [(id, name, mods, vk)]
        self._thread: Optional[threading.Thread] = None
        self._thread_id: int = 0
        self._hook = None
        self._registered: List[int] = []
        self._hook_proc = HOOKPROC(self._hook_callback)  # must stay referenced, or it gets GC'd
        self._running = False

        # double-tap detection state
        self._pending_tap = False
        self._first_press = 0.0
        self._reset_timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------ lifecycle
    def start(self, interval_ms: int = 420,
              hotkeys: Optional[Dict[str, str]] = None,
              double_tap_key: str = DOUBLE_TAP_DEFAULT_KEY) -> None:
        """Start listening. `hotkeys` looks like {"screenshot": "ctrl+alt+a"}."""
        if self._running:
            return
        self._interval = max(0.15, interval_ms / 1000.0)
        self._vk_group = vk_group_for(double_tap_key)
        self._hotkeys = []
        for index, (name, combo) in enumerate((hotkeys or {}).items()):
            parsed = winapi.parse_hotkey(combo)
            if parsed:
                self._hotkeys.append((0xB000 + index, name, parsed[0], parsed[1]))

        self._running = True
        self.reset_state()
        self._thread = threading.Thread(target=self._run, name="knocknock-input", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._thread_id:
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.5)
        self._thread = None

    # ------------------------------------------------------------ thread body
    def _run(self) -> None:
        self._thread_id = int(kernel32.GetCurrentThreadId())
        hmod = kernel32.GetModuleHandleW(None)
        self._hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._hook_proc, hmod, 0)

        registered = []
        for hk_id, name, mods, vk in self._hotkeys:
            if user32.RegisterHotKey(None, hk_id, mods | winapi.MOD_NOREPEAT, vk):
                registered.append(hk_id)
        self._registered = registered

        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                for hk_id, name, _mods, _vk in self._hotkeys:
                    if hk_id == int(msg.wParam):
                        self.hotkey.emit(name)
                        break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        for hk_id in registered:
            user32.UnregisterHotKey(None, hk_id)
        if self._hook:
            user32.UnhookWindowsHookEx(self._hook)
            self._hook = None

    # ------------------------------------------------------------ hook callback
    def _hook_callback(self, n_code, w_param, l_param):
        try:
            if n_code == 0:
                info = ctypes.cast(l_param, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                injected = bool(info.flags & LLKHF_INJECTED)
                # Alt combinations arrive as WM_SYSKEYDOWN, so both key-down
                # messages have to be accepted here.
                is_down = w_param in (WM_KEYDOWN, WM_SYSKEYDOWN)
                if not injected and is_down:
                    self._on_key_down(int(info.vkCode))
        except Exception:
            pass  # a hook callback must never raise
        return user32.CallNextHookEx(None, n_code, w_param, l_param)

    def _on_key_down(self, vk: int) -> None:
        with self._lock:
            if vk in self._vk_group:
                now = time.monotonic()
                if self._pending_tap and (now - self._first_press) <= self._interval:
                    self._pending_tap = False
                    self._cancel_reset_timer()
                    self.double_tap.emit()
                else:
                    self._pending_tap = True
                    self._first_press = now
                    self._schedule_reset_timer()
            else:
                # Some other key was pressed -> this modifier was part of a combo
                # (Alt+Tab, a Ctrl+C, a Shift-click), so it does not count as a
                # double-tap.
                self._pending_tap = False

    # ------------------------------------------------------------ internal timers
    def _schedule_reset_timer(self) -> None:
        """Arm a timer that clears the pending state once it expires. Caller must hold the lock."""
        self._cancel_reset_timer()
        timer = threading.Timer(self._interval * 1.6, self._on_reset_timeout)
        timer.daemon = True
        self._reset_timer = timer
        timer.start()

    def _cancel_reset_timer(self) -> None:
        """Cancel and release any existing timer, so a stale one cannot clear the state by accident. Caller must hold the lock."""
        if self._reset_timer is not None:
            self._reset_timer.cancel()
            self._reset_timer = None

    def _on_reset_timeout(self) -> None:
        with self._lock:
            self._pending_tap = False
            self._reset_timer = None

    def reset_state(self) -> None:
        """Clear the double-tap detection state (used on hotkey reload or in tests)."""
        with self._lock:
            self._cancel_reset_timer()
            self._pending_tap = False
            self._first_press = 0.0

    # ------------------------------------------------------------ live config updates
    def update_interval(self, interval_ms: int) -> None:
        self._interval = max(0.15, interval_ms / 1000.0)
