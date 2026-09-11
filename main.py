"""Knocknock — screen-selection / screenshot Q&A assistant (entry point).

Usage:
    python main.py

Interaction:
    1. Double-tap Ctrl      read the text selected on screen and open the
                            instruction panel (closes it if already open)
    2. Ctrl + Alt + A       drag-select any region of the screen (screenshot)
    3. Ctrl + Alt + Q       same as "double-tap Ctrl"
    4. Tray icon            entry point for everything, and for quitting

The UI can be switched between Chinese and English from
Settings -> Appearance -> Language.
"""
from __future__ import annotations

import sys
from typing import Any, Dict, Optional

from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtGui import QAction, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from knocknock import i18n
from knocknock import theme
from knocknock import winapi
from knocknock.capture import ScreenOverlay
from knocknock.config import ensure_config_exists, load_config, save_config
from knocknock.hotkey import GlobalInput
from knocknock.panel import KnockPanel
from knocknock.selection import capture_selection
from knocknock.settings_dialog import SettingsDialog
from knocknock.widgets import app_icon

APP_NAME = "Knocknock"


class KnocknockController(QObject):
    """Wires together the hotkeys, capture overlay, floating panel and tray icon."""

    def __init__(self, app: QApplication) -> None:
        super().__init__()
        self.app = app
        self.cfg: Dict[str, Any] = load_config()

        i18n.set_language(self.cfg.get("ui", {}).get("language"))

        # When the panel is open, does double-tapping Ctrl close it or re-read the
        # selection? Default is to close.
        self.toggle_on_double_ctrl = bool(
            self.cfg.get("behavior", {}).get("toggle_on_double_ctrl", True)
        )

        self.panel = KnockPanel(self.cfg)
        self.overlay = ScreenOverlay()

        self.input_listener = GlobalInput(self)
        self.input_listener.double_ctrl.connect(self.on_double_ctrl)
        self.input_listener.hotkey.connect(self.on_hotkey)

        self.tray = self._build_tray()

        self.overlay.captured.connect(self.on_captured)
        self.overlay.cancelled.connect(self.on_capture_cancelled)
        self.panel.screenshot_requested.connect(self.start_screenshot)
        self.panel.settings_requested.connect(self.open_settings)
        self.panel.theme_toggled.connect(self.set_theme)
        self.panel.size_changed.connect(self._remember_panel_size)

        self.start_listener()

    # ================================================================ theme
    def _font_size(self) -> int:
        return int(self.cfg.get("ui", {}).get("font_size", 13))

    def set_theme(self, mode: str, persist: bool = True) -> None:
        """Switch between light and dark and apply it immediately (panel and tray menu included)."""
        applied = theme.set_mode(mode)
        self.cfg.setdefault("ui", {})["theme"] = applied
        self.app.setStyleSheet(theme.build_qss(self._font_size(), applied))
        self.panel.apply_theme()
        self._rebuild_tray_menu()
        if persist:
            self._save()

    # ================================================================ language
    def set_language(self, language: Optional[str], persist: bool = True) -> str:
        """Switch the UI language (Chinese / English) and apply it immediately."""
        applied = i18n.set_language(language)
        self.cfg.setdefault("ui", {})["language"] = applied
        self.panel.retranslate()
        self._rebuild_tray_menu()
        if persist:
            self._save()
        return applied

    def _remember_panel_size(self, width: int, height: int) -> None:
        """Remember the size the user dragged out, so it is restored next launch."""
        self.cfg.setdefault("ui", {})["last_size"] = [int(width), int(height)]
        self._save()

    def _save(self) -> None:
        try:
            save_config(self.cfg)
        except OSError:
            pass

    # ================================================================ tray
    def _build_tray(self) -> QSystemTrayIcon:
        tray = QSystemTrayIcon(app_icon(64), self.app)
        tray.setToolTip(i18n.t("app.tray_tooltip"))
        tray.setContextMenu(self._build_menu())
        tray.activated.connect(self._on_tray_activated)
        tray.show()
        return tray

    def _build_menu(self) -> QMenu:
        # QSystemTrayIcon.setContextMenu() does not take ownership of the menu,
        # so parent it to the panel: that way it is destroyed with the panel and
        # repeated rebuilds cannot leak.
        menu = QMenu(self.panel)
        menu.setStyleSheet(theme.build_qss(self._font_size()))

        shot_hotkey = winapi.format_hotkey(self.cfg.get("hotkeys", {}).get("screenshot", ""))
        ask_hotkey = winapi.format_hotkey(self.cfg.get("hotkeys", {}).get("ask_selection", ""))

        action_shot = QAction(i18n.t("tray.menu.screenshot", hotkey=shot_hotkey), menu)
        action_shot.triggered.connect(self.start_screenshot)
        menu.addAction(action_shot)

        action_ask = QAction(i18n.t("tray.menu.ask", hotkey=ask_hotkey), menu)
        action_ask.triggered.connect(self.on_double_ctrl)
        menu.addAction(action_ask)

        menu.addSeparator()

        action_show = QAction(i18n.t("tray.menu.show"), menu)
        action_show.triggered.connect(lambda: self.panel.show_panel(near_cursor=False))
        menu.addAction(action_show)

        action_hide = QAction(i18n.t("tray.menu.hide"), menu)
        action_hide.triggered.connect(self.close_panel)
        menu.addAction(action_hide)

        action_settings = QAction(i18n.t("tray.menu.settings"), menu)
        action_settings.triggered.connect(self.open_settings)
        menu.addAction(action_settings)

        menu.addSeparator()

        action_quit = QAction(i18n.t("tray.menu.quit"), menu)
        action_quit.triggered.connect(self.quit)
        menu.addAction(action_quit)
        return menu

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            if self.panel.isVisible():
                self.panel.hide_panel()
            else:
                self.panel.show_panel(near_cursor=False)

    # ================================================================ hotkeys
    def start_listener(self) -> None:
        hotkeys = {
            "screenshot": self.cfg.get("hotkeys", {}).get("screenshot", ""),
            "ask_selection": self.cfg.get("hotkeys", {}).get("ask_selection", ""),
        }
        self.input_listener.start(
            interval_ms=int(self.cfg.get("hotkeys", {}).get("double_ctrl_interval_ms", 420)),
            hotkeys={key: value for key, value in hotkeys.items() if value},
        )

    def restart_listener(self) -> None:
        self.input_listener.stop()
        QTimer.singleShot(120, self.start_listener)

    def on_hotkey(self, name: str) -> None:
        if name == "screenshot":
            self.start_screenshot()
        elif name == "ask_selection":
            self.on_double_ctrl()

    # ================================================================ selection
    def on_double_ctrl(self) -> None:
        """Double-tap Ctrl: close the panel if it is open, otherwise grab the selection and open it."""
        if self.overlay.isVisible():
            return

        if self.toggle_on_double_ctrl and self.panel.isVisible():
            self.panel.hide_panel()
            return

        restore = bool(self.cfg.get("behavior", {}).get("restore_clipboard", False))
        # Content must be captured first (while focus is still on the target app),
        # then the panel is shown.
        result = capture_selection(restore_clipboard=restore)

        if result.get("image") is not None and not result.get("text"):
            image = result["image"]
            pixmap = QPixmap.fromImage(image)
            self.panel.set_context(image=pixmap, source="selection")
        else:
            self.panel.set_context(text=result.get("text", ""), source="selection")

        self.panel.show_panel(near_cursor=True)

    def close_panel(self) -> None:
        """Close (hide) the panel — used by the global shortcut and the tray menu."""
        if self.panel.isVisible():
            self.panel.hide_panel()

    # ================================================================ screenshot
    def start_screenshot(self) -> None:
        self.panel.hide()
        # Wait one frame to make sure the panel is off-screen before capturing
        QTimer.singleShot(160, self.overlay.start)

    def on_captured(self, pixmap: QPixmap) -> None:
        self.panel.set_context(image=pixmap, source="screenshot")
        self.panel.show_panel(near_cursor=False)

    def on_capture_cancelled(self) -> None:
        if self.panel.isVisible():
            self.panel.show_panel(near_cursor=False)

    # ================================================================ settings
    def open_settings(self) -> None:
        dialog = SettingsDialog(self.cfg, None)
        if dialog.exec():
            self.cfg = dialog.cfg
            # Switch language first, then theme: both rebuild the tray menu, and
            # the language has to come first.
            i18n.set_language(self.cfg.get("ui", {}).get("language"))
            self.toggle_on_double_ctrl = bool(
                self.cfg.get("behavior", {}).get("toggle_on_double_ctrl", True)
            )
            self.set_theme(self.cfg.get("ui", {}).get("theme", "light"), persist=False)
            self.panel.apply_config(self.cfg)
            self.panel.retranslate()
            if dialog.reset_size_requested:
                self.panel.reset_size()
            self.restart_listener()
            self._save()

    def _rebuild_tray_menu(self) -> None:
        """Refresh the tray menu after settings are saved.

        Note: only the QMenu may be rebuilt here — **never touch the
        QSystemTrayIcon's icon**. The tray icon must be created exactly once per
        process, otherwise every settings save adds another tray icon, and the
        old objects have no reference and cannot be collected. (setToolTip does
        not create an object, so it is safe.)
        """
        self.tray.setToolTip(i18n.t("app.tray_tooltip"))
        old_menu = self.tray.contextMenu()
        self.tray.setContextMenu(self._build_menu())
        if old_menu is not None:
            old_menu.deleteLater()

    # ================================================================ quitting
    def quit(self) -> None:
        try:
            save_config(self.cfg)
        except OSError:
            pass
        self.input_listener.stop()
        self.panel.hide()
        self.tray.hide()
        self.app.quit()


def _already_running() -> bool:
    """Use a named mutex to prevent a second instance from starting."""
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p)
    kernel32.CreateMutexW(None, False, "Local\\KnocknockSingleInstance")
    return ctypes.get_last_error() == 183  # ERROR_ALREADY_EXISTS


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)

    created = ensure_config_exists()
    cfg = load_config()
    # The language has to be decided before any UI object exists, otherwise the
    # first frame is drawn with the wrong language.
    i18n.set_language(cfg.get("ui", {}).get("language"))
    theme.set_mode(cfg.get("ui", {}).get("theme", "light"))
    app.setStyleSheet(theme.build_qss(int(cfg.get("ui", {}).get("font_size", 13))))
    app.setWindowIcon(app_icon(128))

    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(None, APP_NAME, i18n.t("dialog.tray_unavailable"))
        return 1

    if _already_running():
        QMessageBox.information(None, APP_NAME, i18n.t("dialog.already_running"))
        return 0

    controller = KnocknockController(app)
    app.aboutToQuit.connect(controller.input_listener.stop)

    if created or not str(cfg.get("api", {}).get("api_key", "")).strip():
        controller.tray.showMessage(
            i18n.t("notify.started.title"),
            i18n.t("notify.started.body"),
            app_icon(64),
            6000,
        )

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
