"""Knocknock self-test — offline and non-intrusive; verifies that the modules work together.

    python tests/selftest.py

Covers:
  1. Config loading and merging
  2. Hotkey string parsing
  3. Message construction for the model (text / screenshot / Anthropic conversion)
  4. Stylesheet integrity
  5. UI construction and the question flow
  6. Screen capture and high-DPI cropping
  7. Clipboard / selection fallback paths
  8. Model calls (a local mock server exercises streaming, error handling, interruption)
  9. Tray-icon uniqueness (saving settings must not add tray icons)
 10. Panel resizing (freely resizable, preset buttons never clipped)
 11. Light / dark theme switching
 12. The shadow is not cut by the window edge + tooltips follow the theme
 13. Drag-to-resize (hot zones on the card) + the result area is not clipped after a manual resize
 14. Chinese/English switching (string tables / panel and tray retranslation / per-language presets)
 15. Pinned header and double-Alt close (title bar does not drift / double-tap Alt toggles the panel)
 16. Screenshot growth (a new picture grows the panel into view step by step, and it fits on screen)
 17. Output token budget (the default is large enough; 0 means "let the server decide")
 18. Text / vision model split (screenshots use the vision model; the preview box is respected)

Group 9 briefly creates one tray icon (hidden again when the test ends); no other
case disturbs the desktop. The whole self-test redirects config writes to a
temporary file and never touches the user's config.json.
"""
from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# The screen-capture cases need a real rendering backend, so do not switch to offscreen
os.environ.pop("QT_QPA_PLATFORM", None)

# ---------------------------------------------------------------- safety net
# The self-test must never write the user's config.json (test hotkeys once ended
# up in the real config). Redirect knocknock.config.save_config to a temp file
# before any other import, so modules imported later (main / settings_dialog)
# pick up the replacement via `from .config import save_config`.
import knocknock.config as _config_module  # noqa: E402

_TMP_CONFIG = Path(tempfile.mkdtemp(prefix="knocknock-selftest-")) / "config.json"


def _redirected_save(cfg) -> None:
    _TMP_CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


_config_module.save_config = _redirected_save

from PySide6.QtCore import (  # noqa: E402
    QCoreApplication,
    QEvent,
    QPoint,
    QPointF,
    QRect,
    QSize,
    QTimer,
    Qt,
)
from PySide6.QtGui import QColor, QMouseEvent, QPixmap  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QWidget,
    QDialog,
    QMenu,
    QSystemTrayIcon,
)

PASSED: list[str] = []
FAILED: list[str] = []


def section(title: str) -> None:
    print(f"\n--- {title} " + "-" * max(0, 52 - len(title)))


def case(name: str, fn) -> None:
    try:
        fn()
    except Exception as exc:  # noqa: BLE001
        import traceback

        FAILED.append(name)
        print(f"  [FAIL] {name}: {type(exc).__name__}: {exc}")
        traceback.print_exc()
    else:
        PASSED.append(name)
        print(f"  [PASS] {name}")


# ==================================================================== 1 config
def t_config() -> None:
    from knocknock.config import DEFAULT_CONFIG, get, load_config

    cfg = load_config()
    assert cfg["api"]["model"], "the model name must not be empty"
    assert isinstance(cfg["presets"], list) and cfg["presets"], "presets must not be empty"
    assert cfg["ui"]["width"] == DEFAULT_CONFIG["ui"]["width"]
    assert get(cfg, "api.timeout") == cfg["api"]["timeout"]
    assert get(cfg, "not.exist", "fallback") == "fallback"


def t_config_paths_frozen() -> None:
    """A frozen (PyInstaller) build must store its config next to the executable.

    Regression: ``APP_DIR`` used to be derived from ``__file__`` unconditionally,
    which inside a onefile bundle points at PyInstaller's temporary ``_MEIPASS``
    folder. The config was written there and thrown away when the process
    exited, so the packaged app appeared to forget its API key on every launch.
    """
    import importlib
    import sys
    from pathlib import Path

    import knocknock.config as config_module

    real_executable = sys.executable

    try:
        # Simulate a frozen run: sys.frozen plus a fake executable location.
        sys.frozen = True
        sys.executable = r"C:\Some Folder\Knocknock.exe"
        reloaded = importlib.reload(config_module)

        assert reloaded.APP_DIR == Path(r"C:\Some Folder"), reloaded.APP_DIR
        assert reloaded.CONFIG_PATH == Path(r"C:\Some Folder\config.json")
        assert not str(reloaded.APP_DIR).startswith(str(Path(__file__).parent)), (
            "a frozen build must not resolve to the source tree"
        )
    finally:
        for attribute in ("frozen", "_MEIPASS"):
            if hasattr(sys, attribute):
                delattr(sys, attribute)
        sys.executable = real_executable
        importlib.reload(config_module)

    # Back to source mode: the project root is the package's parent directory.
    source_root = Path(config_module.__file__).resolve().parent.parent
    assert config_module.APP_DIR == source_root, config_module.APP_DIR
    assert config_module.EXAMPLE_PATH == source_root / "config.example.json"


# ==================================================================== 2 hotkeys
def t_hotkey_parse() -> None:
    from knocknock import winapi

    assert winapi.parse_hotkey("ctrl+alt+a") == (0x0001 | 0x0002, 0x41)
    assert winapi.parse_hotkey("ctrl+shift+F5") == (0x0002 | 0x0004, 0x74), "function keys"
    assert winapi.parse_hotkey("win+space") == (0x0008, 0x20)
    assert winapi.parse_hotkey("badkey") is None
    assert winapi.parse_hotkey("a") is None, "a missing modifier must be treated as invalid"
    assert winapi.format_hotkey("ctrl+alt+a") == "CTRL + ALT + A"


# ==================================================================== 3 messages
def t_user_content() -> None:
    from knocknock.llm import build_user_content, to_anthropic_messages

    text_only = build_user_content({"text": "hello", "image_png": None}, "translate this")
    assert isinstance(text_only, str) and "hello" in text_only and "translate this" in text_only

    vision = build_user_content(
        {"text": "", "image_png": b"\x89PNG\r\n\x1a\n", "source": "screenshot"}, "what is this"
    )
    assert isinstance(vision, list) and len(vision) == 2
    assert vision[0]["type"] == "text" and vision[1]["type"] == "image_url"
    assert vision[1]["image_url"]["url"].startswith("data:image/png;base64,")

    packed = to_anthropic_messages(
        [{"role": "system", "content": "sys"}, {"role": "user", "content": vision}]
    )
    assert packed["system"] == "sys"
    assert packed["messages"][0]["content"][1]["type"] == "image"


# ==================================================================== 4 stylesheet
def t_qss() -> None:
    from knocknock import theme

    original = theme.mode()
    try:
        for mode in ("light", "dark"):
            qss = theme.build_qss(13, mode)
            assert "QFrame#Card" in qss, mode
            assert theme.palette().accent in qss, mode
            assert theme.mode() == mode
            assert qss.count("{") == qss.count("}"), f"{mode} stylesheet has unbalanced braces"

        # The two themes must actually differ
        light = theme.build_qss(13, "light")
        dark = theme.build_qss(13, "dark")
        assert light != dark
        theme.set_mode("light")
        assert not theme.is_dark()
        assert theme.palette().text_primary == "#1D1D1F"
        theme.set_mode("dark")
        assert theme.is_dark()
        assert theme.palette().text_primary != "#1D1D1F"
        assert theme.shadow_color().alpha() > 70, "the dark theme shadow should be heavier"

        # Invalid values / auto must both fall back gracefully
        assert theme.resolve_mode("bogus") == "light"
        assert theme.resolve_mode("auto") in ("light", "dark")
        assert theme.resolve_mode(None) == "light"
    finally:
        theme.set_mode(original)


# ==================================================================== 5 UI
def t_panel() -> None:
    from knocknock import widgets as w
    from knocknock.capture import pixmap_to_png_bytes, scale_to_fit
    from knocknock.config import load_config
    from knocknock.panel import KnockPanel
    from knocknock.settings_dialog import SettingsDialog

    cfg = load_config()

    assert not w.app_icon(128).isNull()
    for name in ("close", "pin", "crop", "gear", "copy", "stop", "sparkle"):
        assert not w.glyph_icon(name).isNull(), f"icon {name} failed to render"

    panel = KnockPanel(cfg)
    panel.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    panel.show()

    panel.set_context(text="Selected text used for testing. " * 5)
    assert panel.chip_buttons, "preset buttons were not created"
    assert panel.sizeHint().height() > 120, "panel height looks wrong"

    # No key configured -> a friendly hint rather than a crash or a request
    panel.cfg["api"]["api_key"] = ""
    panel._send(None)
    assert "API Key" in panel.result.toPlainText(), "a hint is expected when the key is missing"

    # Screenshot context
    pixmap = QPixmap(320, 180)
    pixmap.fill(QColor("#3A7BD5"))
    panel.set_context(image=pixmap, source="screenshot")
    assert panel._ctx["image_png"][:4] == b"\x89PNG"

    # Streaming rendering
    panel._on_chunk("Hel")
    panel._on_chunk("lo there")
    panel._flush_stream()
    assert "Hel" in panel.result.toPlainText()
    panel._on_succeeded("Hello there")
    assert panel.copy_btn.isEnabled(), "the copy button should be enabled once an answer arrives"

    assert pixmap_to_png_bytes(pixmap)[:4] == b"\x89PNG"
    assert not scale_to_fit(pixmap, 100, 100).isNull()

    dialog = SettingsDialog(cfg)
    collected = dialog._collect()
    assert collected["api"]["model"] == cfg["api"]["model"]
    assert isinstance(collected["presets"], list)
    dialog.deleteLater()
    panel.deleteLater()


# ==================================================================== 6 capture
def t_capture() -> None:
    from knocknock.capture import (ScreenOverlay, crop_device_rect, grab_virtual_desktop,
                               pixmap_to_png_bytes)

    composite, virtual, dpr = grab_virtual_desktop()
    assert composite is not None and not composite.isNull(), "screen capture failed"
    assert composite.width() == int(virtual.width() * dpr), "stitched width does not match dpr"
    assert composite.height() == int(virtual.height() * dpr)

    center = composite.toImage().pixelColor(composite.width() // 2, composite.height() // 2)
    assert center != QColor("#000000"), "the capture is all black; grabWindow caught nothing"

    cropped = crop_device_rect(composite, QRect(100, 80, 300, 200), dpr)
    assert cropped.width() == int(300 * dpr) and cropped.height() == int(200 * dpr)

    # Out-of-bounds crops to the boundary instead of crashing
    edge = crop_device_rect(composite, QRect(virtual.width() - 50, virtual.height() - 50, 400, 400), dpr)
    assert edge.width() == int(50 * dpr)
    # Entirely outside -> None
    assert crop_device_rect(composite, QRect(virtual.width() + 100, 0, 50, 50), dpr) is None

    assert pixmap_to_png_bytes(cropped)[:8] == b"\x89PNG\r\n\x1a\n"

    overlay = ScreenOverlay()
    overlay._composite, overlay._dpr = composite, dpr
    assert overlay._crop(QRect(60, 40, 240, 160)).width() == int(240 * dpr)
    overlay.deleteLater()


# ==================================================================== 7 clipboard
def t_selection() -> None:
    """The selection pipeline.

    Two traps:
    1. `grab_selected_text()` really does send Ctrl+C to the foreground window, so
       its outcome depends on "who has focus and whether anything is selected".
       The algorithm is therefore tested with all external dependencies stubbed.
    2. On Windows, Qt writes to the clipboard using **delayed rendering**, which
       needs the event loop to answer WM_RENDERFORMAT. If you only sleep without
       running the event loop, the second write onward silently fails and can even
       empty the clipboard. Every write here is therefore followed by pumping the
       event loop.
    """
    from PySide6.QtGui import QGuiApplication

    from knocknock import selection, winapi
    from knocknock.selection import clipboard_image, clipboard_text, set_clipboard_text

    app = QApplication.instance()

    def pump() -> None:
        app.processEvents()
        time.sleep(0.05)
        app.processEvents()

    def write_ok(value: str, retries: int = 5) -> bool:
        for _ in range(retries):
            set_clipboard_text(value)
            pump()
            if clipboard_text() == value:
                return True
        return False

    original_text = clipboard_text()
    original_send = winapi.send_ctrl_c
    original_gui_app = selection.QGuiApplication
    original_grab = selection.grab_selected_text
    try:
        # --- 1. Real clipboard round-trip (text)
        assert write_ok("clipboard test text"), "could not read back what was written"

        # --- 2. Real clipboard round-trip (image)
        pixmap = QPixmap(64, 48)
        pixmap.fill(QColor("#FF3B30"))
        QApplication.clipboard().setPixmap(pixmap)
        pump()
        image = clipboard_image()
        assert image is not None and image.width() == 64, "could not read the clipboard image"

        # --- 3. grab_selected_text algorithm (all external dependencies stubbed)
        state = {"seq": 100, "text": "original clipboard"}
        selection.clipboard_text = lambda: state["text"]
        selection.winapi.clipboard_sequence = lambda: state["seq"]
        selection.winapi.send_ctrl_c = lambda: None  # the target app does nothing

        assert selection.grab_selected_text(timeout=0.15) == "", \
            "an empty string is expected when nothing was really copied, otherwise the old clipboard is mistaken for a selection"

        def fake_copy() -> None:
            state["seq"] += 1
            state["text"] = "copied selection"

        selection.winapi.send_ctrl_c = fake_copy
        assert selection.grab_selected_text(timeout=0.5) == "copied selection"

        # restore=True must write the original content back (a fake clipboard records writes)
        written: list[str] = []

        class _FakeClipboard:
            def setText(self, text: str) -> None:
                written.append(text)

        class _FakeGuiApp:
            @staticmethod
            def clipboard():
                return _FakeClipboard()

        state["seq"] = 200
        state["text"] = "original clipboard"
        selection.QGuiApplication = _FakeGuiApp
        selection.winapi.send_ctrl_c = fake_copy
        result = selection.grab_selected_text(timeout=0.5, restore=True)
        assert result == "copied selection", result
        assert written == ["original clipboard"], f"restore=True did not restore the clipboard: {written}"

        # --- 4. capture_selection branches: prefer text, otherwise fall back to a clipboard image
        selection.QGuiApplication = QGuiApplication
        selection.grab_selected_text = lambda **kwargs: "selected text"
        assert selection.capture_selection()["text"] == "selected text"
        selection.grab_selected_text = lambda **kwargs: ""
        assert selection.capture_selection()["image"] is not None, \
            "it should fall back to the clipboard image when there is no text"
    finally:
        selection.grab_selected_text = original_grab
        selection.QGuiApplication = original_gui_app
        selection.winapi.send_ctrl_c = original_send
        set_clipboard_text(original_text)
        pump()


# ==================================================================== 8 model calls
class _MockHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    record: list = []
    mode = "ok"

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        self.record.append({"path": self.path, "headers": dict(self.headers), "body": body})

        if self.mode == "unauthorized":
            payload = json.dumps({"error": {"message": "Incorrect API key provided"}}).encode()
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        if self.mode == "plain":
            # A gateway/proxy ignores the stream flag and returns plain JSON
            payload = json.dumps(
                {"choices": [{"message": {"role": "assistant", "content": "this is the body"}}]},
                ensure_ascii=False,
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        if self.mode == "reasoning":
            # The reasoning model only emits reasoning_content; the body was cut by max_tokens
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for piece in ("let me think", "..."):
                chunk = {"choices": [{"delta": {"reasoning_content": piece}}]}
                self.wfile.write(f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode())
                self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()

        if self.path.endswith("/chat/completions"):
            for piece in ("Quantum", " entanglement", " is a physics phenomenon"):
                if self.mode == "slow":
                    time.sleep(0.15)
                chunk = {"choices": [{"delta": {"content": piece}}]}
                self.wfile.write(f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n".encode())
                self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")
        else:
            for piece in ("Claude", " answers"):
                event = {"type": "content_block_delta", "delta": {"text": piece}}
                self.wfile.write(f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode())
                self.wfile.flush()
        self.wfile.flush()

    def log_message(self, *args):
        pass


def _run_worker(app, cfg, messages, stop_after_ms=None):
    from knocknock.llm import LLMWorker

    box = {"chunks": [], "ok": None, "err": None, "done": False}
    worker = LLMWorker(cfg, messages)
    worker.chunk.connect(lambda s: box["chunks"].append(s))
    worker.succeeded.connect(lambda s: box.update(ok=s, done=True))
    worker.failed.connect(lambda s: box.update(err=s, done=True))

    guard = QTimer()
    guard.setSingleShot(True)
    guard.timeout.connect(lambda: (box.update(done=True), worker.stop()))
    guard.start(8000)

    worker.start()
    if stop_after_ms is not None:
        QTimer.singleShot(stop_after_ms, worker.stop)

    while not box["done"]:
        app.processEvents()
        time.sleep(0.02)
    guard.stop()
    worker.stop()
    worker.wait(1500)
    return box


def t_llm(app) -> None:
    from knocknock.llm import ANTHROPIC_DEFAULT_MAX_TOKENS, build_user_content

    server = HTTPServer(("127.0.0.1", 0), _MockHandler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = {
        "base_url": f"http://127.0.0.1:{port}",
        "api_key": "sk-test",
        "model": "mock-model",
        "stream": True,
        "timeout": 20,
        "max_tokens": 256,
    }
    try:
        # --- OpenAI-compatible streaming
        _MockHandler.mode = "ok"
        box = _run_worker(app, base, [{"role": "user", "content": "explain quantum entanglement"}])
        assert box["err"] is None, box["err"]
        assert box["chunks"] == ["Quantum", " entanglement", " is a physics phenomenon"], box["chunks"]
        assert box["ok"] == "Quantum entanglement is a physics phenomenon"
        request = _MockHandler.record[-1]
        assert request["path"] == "/chat/completions"
        assert request["headers"].get("Authorization") == "Bearer sk-test"
        assert request["body"]["model"] == "mock-model"

        # --- A screenshot message really carries an image block
        content = build_user_content(
            {"text": "", "image_png": b"\x89PNG_fake", "source": "screenshot"}, "what is this"
        )
        _run_worker(app, base, [{"role": "user", "content": content}])
        blocks = _MockHandler.record[-1]["body"]["messages"][0]["content"]
        assert blocks[1]["image_url"]["url"].startswith("data:image/png;base64,")

        # --- Friendly 401 hint
        _MockHandler.mode = "unauthorized"
        box = _run_worker(app, base, [{"role": "user", "content": "hi"}])
        assert box["err"] and "401" in box["err"] and "API Key" in box["err"], box["err"]

        # --- Anthropic protocol
        _MockHandler.mode = "ok"
        anthropic = dict(base, provider="anthropic", model="claude-3-5-sonnet-latest")
        box = _run_worker(app, anthropic, [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
        ])
        assert box["ok"] == "Claude answers", box["ok"]
        request = _MockHandler.record[-1]
        assert request["path"] == "/v1/messages"
        assert request["headers"].get("x-api-key") == "sk-test"
        assert request["body"]["system"] == "sys"

        # --- Stop mid-stream
        _MockHandler.mode = "slow"
        box = _run_worker(app, base, [{"role": "user", "content": "hi"}], stop_after_ms=180)
        assert len(box["chunks"]) < 3, "stopping had no effect"

        # --- The server returns plain JSON (a gateway ignored the stream flag) -> the body must still be found
        #     Historic bug: such responses were skipped entirely and the panel only said
        #     "the model returned no content".
        _MockHandler.mode = "plain"
        box = _run_worker(app, base, [{"role": "user", "content": "hi"}])
        assert box["err"] is None, box["err"]
        assert box["ok"] == "this is the body", f"plain JSON response body was not extracted: {box['ok']!r}"

        # --- Only reasoning_content came back (reasoning model cut off by max_tokens)
        #     -> must produce an actionable hint
        _MockHandler.mode = "reasoning"
        box = _run_worker(app, base, [{"role": "user", "content": "hi"}])
        assert box["err"] and "max_tokens" in box["err"], (
            f"no clear hint was given when only reasoning arrived: {box['err']!r}"
        )

        # --- Output token budget: 0 means "let the server decide" -> send no cap at all
        _MockHandler.mode = "ok"
        _run_worker(app, dict(base, max_tokens=0), [{"role": "user", "content": "hi"}])
        assert "max_tokens" not in _MockHandler.record[-1]["body"], (
            "max_tokens=0 should leave the field out so the provider applies its own maximum"
        )

        _run_worker(app, dict(base, max_tokens=8000), [{"role": "user", "content": "hi"}])
        assert _MockHandler.record[-1]["body"]["max_tokens"] == 8000

        # Anthropic rejects a request without max_tokens, so "auto" has to resolve
        # to a concrete number there.
        _run_worker(app, dict(base, provider="anthropic", max_tokens=0),
                    [{"role": "user", "content": "hi"}])
        assert _MockHandler.record[-1]["body"]["max_tokens"] == ANTHROPIC_DEFAULT_MAX_TOKENS, (
            _MockHandler.record[-1]["body"]["max_tokens"]
        )
    finally:
        server.shutdown()


# ==================================================================== 9 tray
def t_tray() -> None:
    """Regression: saving settings rebuilds the tray menu and must never rebuild the tray icon.

    Historic bug: `_rebuild_tray_menu()` mistakenly called `_build_tray()`, and
    `_build_tray()` creates and shows a QSystemTrayIcon — so every settings save
    added another tray icon, and the old objects had no reference and could never
    be collected.
    """
    import main as entry
    from knocknock import i18n

    def flush() -> None:
        # processEvents() does not handle DeferredDelete by default; dispatch it explicitly
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        QApplication.processEvents()

    controller = entry.KnocknockController(QApplication.instance())
    try:
        flush()
        tray_count = lambda: len(QApplication.instance().findChildren(QSystemTrayIcon))
        menu_count = lambda: len(controller.panel.findChildren(QMenu))

        assert tray_count() == 1, f"there should be exactly 1 tray icon at startup, got {tray_count()}"

        for index in range(1, 6):
            controller._rebuild_tray_menu()
            flush()
            assert tray_count() == 1, (
                f"after settings save #{index} there are {tray_count()} tray icons"
            )
            assert menu_count() == 1, f"the old menu was not released; {menu_count()} still alive"

        menu = controller.tray.contextMenu()
        assert menu is not None, "the tray menu is missing"
        labels = [action.text() for action in menu.actions() if not action.isSeparator()]
        assert len(labels) == 6, labels
        # Match against the active language rather than hard-coding English, so the
        # case stays valid whichever language the config is in.
        assert any(text == i18n.t("tray.menu.settings") for text in labels), labels
        assert any(text == i18n.t("tray.menu.hide") for text in labels), labels

        # The menu content should refresh with the config (a changed hotkey must show up)
        controller.cfg["hotkeys"]["screenshot"] = "ctrl+shift+x"
        controller._rebuild_tray_menu()
        flush()
        refreshed = [a.text() for a in controller.tray.contextMenu().actions()]
        assert any("CTRL + SHIFT + X" in text for text in refreshed), refreshed

        # Exercise the real "Settings -> Save" path by making the modal dialog always accept.
        # Note: save_config must stay intercepted for the whole case, or it would write the
        # user's real config.json.
        from knocknock import settings_dialog as sd
        from knocknock import theme

        saved: list = []
        original_exec = sd.SettingsDialog.exec
        original_save = entry.save_config
        original_dialog_save = sd.save_config
        sd.SettingsDialog.exec = lambda self: QDialog.DialogCode.Accepted
        entry.save_config = lambda cfg: saved.append(copy.deepcopy(cfg))
        sd.save_config = entry.save_config
        try:
            for index in range(1, 4):
                controller.open_settings()
                flush()
                assert tray_count() == 1, (
                    f"after settings save #{index} there are {tray_count()} tray icons"
                )
                assert menu_count() == 1, f"the old menu was not released; {menu_count()} still alive"
            assert saved, "saving settings should persist"

            # --- Theme switch: must land in the config and refresh both the panel and tray menu
            controller.set_theme("dark")
            assert theme.is_dark()
            assert controller.cfg["ui"]["theme"] == "dark"
            assert saved[-1]["ui"]["theme"] == "dark", "the theme was not written back to the config"
            assert controller.panel.theme_btn.toolTip() == i18n.t("theme.switch_to_light")
            menu_qss = controller.tray.contextMenu().styleSheet()
            assert theme.DARK.bg_dialog in menu_qss, "the tray menu did not follow the theme"

            controller.set_theme("light")
            assert not theme.is_dark()
            assert controller.panel.theme_btn.toolTip() == i18n.t("theme.switch_to_dark")

            # --- A manual size must also be remembered
            controller._remember_panel_size(528, 644)
            assert controller.cfg["ui"]["last_size"] == [528, 644]
            assert saved[-1]["ui"]["last_size"] == [528, 644]
        finally:
            sd.SettingsDialog.exec = original_exec
            sd.save_config = original_dialog_save
            entry.save_config = original_save
            controller.set_theme("light", persist=False)
    finally:
        controller.input_listener.stop()
        controller.tray.hide()
        controller.panel.deleteLater()
        controller.overlay.deleteLater()


# ==================================================================== 10 resizing
def _assert_chips_visible(panel) -> None:
    """Every preset button must sit fully inside the chip bar — none may be clipped."""
    bar = panel.chips
    area = bar.rect()
    assert panel.chip_buttons, "preset buttons were not created"
    for button in panel.chip_buttons:
        assert area.contains(button.geometry()), (
            f"button '{button.text()}' is clipped: {button.geometry()} is not inside {area}"
        )


def t_resizable() -> None:
    """The panel resizes freely and frequent controls (presets) are always fully visible."""
    from knocknock.config import load_config
    from knocknock.panel import KnockPanel

    app = QApplication.instance()
    cfg = load_config()
    cfg["ui"]["theme"] = "light"
    cfg["ui"]["width"] = 496
    cfg["ui"]["min_width"] = 400
    cfg["ui"].pop("last_size", None)

    panel = KnockPanel(cfg)
    panel.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    panel.set_context(text="Selected text used for testing. " * 5)
    panel.show()
    app.processEvents()
    assert panel._user_resized is False

    # --- initial width
    _assert_chips_visible(panel)

    # --- shrink to the minimum width: buttons must wrap, never be clipped
    panel.resize(panel._min_width(), panel.height())
    app.processEvents()
    _assert_chips_visible(panel)
    narrow_rows_height = panel.chips.height()
    assert narrow_rows_height > 26, "the chip bar should become multi-row when narrowed"

    # --- widen again: fewer rows, buttons still intact
    panel.resize(860, panel.height())
    app.processEvents()
    _assert_chips_visible(panel)
    assert panel.chips.height() <= narrow_rows_height, "the chip bar should not get taller when widened"

    # --- however it is dragged, it cannot go below the size needed to fit everything
    panel.resize(120, 80)
    app.processEvents()
    assert panel.width() >= panel._min_width(), panel.width()
    assert panel.height() >= panel._min_height(), panel.height()
    assert panel.height() >= panel.layout().minimumSize().height(), "squeezed until content does not fit"
    _assert_chips_visible(panel)

    # --- the result area stretches: the window grows when it expands
    panel._user_resized = False
    panel.result.hide()
    panel._apply_natural_size()
    app.processEvents()
    compact = panel.height()
    panel.result.show()
    panel._apply_natural_size()
    app.processEvents()
    assert panel.height() > compact, f"the window did not grow when the result area expanded: {compact} -> {panel.height()}"
    assert panel.result.height() >= 130, panel.result.height()

    # --- on a narrow panel the subtitle and hint should switch to short copy to make room
    panel.resize(panel._min_width(), panel.height())
    app.processEvents()
    assert panel.hint_label.text() == "", "the hint should be hidden on a narrow panel"
    assert panel.subtitle_label.text() == panel._subtitle_short
    panel.resize(860, panel.height())
    app.processEvents()
    assert panel.hint_label.text() != "", "the hint should come back on a wide panel"

    panel.deleteLater()


def t_theme_toggle() -> None:
    """Light / dark theme switching."""
    from knocknock import i18n
    from knocknock import theme
    from knocknock.config import load_config
    from knocknock.panel import KnockPanel
    from knocknock.settings_dialog import SettingsDialog

    app = QApplication.instance()
    cfg = load_config()
    cfg["ui"]["theme"] = "light"
    cfg["ui"].pop("last_size", None)

    theme.set_mode("light")
    panel = KnockPanel(cfg)
    panel.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    panel.show()
    app.processEvents()

    captured: list = []
    panel.theme_toggled.connect(captured.append)

    assert not theme.is_dark()
    assert panel.theme_btn.toolTip() == i18n.t("theme.switch_to_dark")
    panel._toggle_theme()
    assert captured == ["dark"], captured

    theme.set_mode("dark")
    panel.apply_theme()
    assert theme.is_dark()
    assert panel.theme_btn.toolTip() == i18n.t("theme.switch_to_light")
    assert theme.shadow_color().alpha() == theme.DARK.shadow_alpha

    panel._toggle_theme()
    assert captured[-1] == "light"

    theme.set_mode("light")
    panel.apply_theme()
    assert theme.shadow_color().alpha() == theme.LIGHT.shadow_alpha
    assert panel.theme_btn.toolTip() == i18n.t("theme.switch_to_dark")

    # Settings dialog: the appearance tab reads the theme, previews live, and restores on cancel
    dialog = SettingsDialog(cfg)
    assert dialog._collect()["ui"]["theme"] in ("light", "dark", "auto")
    dialog.theme_box.setCurrentIndex(dialog.theme_box.findData("dark"))
    assert theme.is_dark(), "the appearance tab should preview the theme live"
    dialog.theme_box.setCurrentIndex(dialog.theme_box.findData("light"))
    dialog.reject()
    assert not theme.is_dark(), "cancelling settings should restore the previous theme"

    # The primary button must really be styled with the accent colour
    # (QDialogButtonBox used to swallow the stylesheet; it is no longer used).
    dialog = SettingsDialog(cfg)
    dialog.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    dialog.show()
    app.processEvents()
    image = dialog.save_btn.grab().toImage()
    sampled = image.pixelColor(6, image.height() // 2).name()
    assert sampled == theme.palette().accent.lower(), (
        f"the save button did not get the primary-button style: {sampled} != {theme.palette().accent}"
    )
    dialog.reject()

    panel.deleteLater()
    theme.set_mode("light")


# ==================================================================== 12 shadow / tooltips
def _grab_tooltip(app, anchor, text: str):
    """Show a tooltip and grab it as an image (Qt's tooltip widget is named qtooltip_label)."""
    from PySide6.QtWidgets import QToolTip

    QToolTip.hideText()
    app.processEvents()
    QToolTip.showText(anchor.mapToGlobal(QPoint(20, 20)), text, anchor)
    app.processEvents()
    label = next((w for w in app.allWidgets() if w.objectName() == "qtooltip_label"), None)
    image = label.grab().toImage() if label is not None else None
    QToolTip.hideText()
    app.processEvents()
    return image


def t_shadow_and_tooltip() -> None:
    """The shadow must fall entirely inside the margin (not cut by the window edge); tooltips must match the theme and stay readable."""
    from knocknock import theme
    from knocknock.config import load_config
    from knocknock.panel import KnockPanel

    app = QApplication.instance()
    cfg = load_config()
    cfg["ui"]["theme"] = "light"
    cfg["ui"].pop("last_size", None)

    theme.set_mode("light")
    app.setStyleSheet(theme.build_qss(13, "light"))
    panel = KnockPanel(cfg)
    panel.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    panel.set_context(text="test content")
    panel.show()
    app.processEvents()

    # --- 1. The shadow must not be cut into a hard edge by the window boundary
    image = panel.grab().toImage()
    width, height = image.width(), image.height()
    border_alphas = []
    for x in range(0, width, 5):
        border_alphas.append(image.pixelColor(x, 0).alpha())
        border_alphas.append(image.pixelColor(x, height - 1).alpha())
    for y in range(0, height, 5):
        border_alphas.append(image.pixelColor(0, y).alpha())
        border_alphas.append(image.pixelColor(width - 1, y).alpha())
    worst = max(border_alphas)
    assert worst <= 2, (
        f"the shadow is cut by the window edge: outermost ring has alpha={worst} "
        f"(increase SHADOW_MARGIN or reduce the blur)"
    )

    # --- 2. The shadow must actually exist (do not "fix" it by removing the shadow)
    card = panel.card.geometry()
    below = image.pixelColor(width // 2, min(card.bottom() + 8, height - 1)).alpha()
    assert below > 3, f"no shadow is visible below the card, alpha={below}"
    peak = image.pixelColor(card.right() + 1, card.center().y()).alpha()
    assert peak < 60, f"the shadow is too heavy: alpha={peak} right next to the card"

    # --- 3. Tooltip colours must match the current theme and stay readable
    for mode in ("light", "dark"):
        theme.set_mode(mode)
        app.setStyleSheet(theme.build_qss(13, mode))
        app.processEvents()
        palette = theme.palette()
        tip = _grab_tooltip(app, panel, "Capture region (Ctrl+Alt+A)")
        assert tip is not None, "could not grab the tooltip widget"
        assert tip.width() > 40 and tip.height() > 10, (tip.width(), tip.height())

        bg = tip.pixelColor(3, tip.height() // 2)
        expected = QColor(palette.tooltip_bg)
        assert bg.name().lower() == expected.name().lower(), (
            f"wrong tooltip background in {mode} theme: {bg.name()} != {palette.tooltip_bg}"
        )

        # Text and background must be opposite in lightness
        # (the light theme once had dark text on a dark background, unreadable)
        lightness = [
            tip.pixelColor(x, y).lightness()
            for y in range(0, tip.height(), 2)
            for x in range(0, tip.width(), 2)
        ]
        contrast = max(lightness) - min(lightness)
        assert contrast > 60, f"tooltip text contrast is too low in {mode} theme: {contrast}"

        text_color = QColor(palette.tooltip_text).lightness()
        assert abs(text_color - expected.lightness()) > 100, (
            f"tooltip text colour is too close to the background in {mode} theme"
        )

    theme.set_mode("light")
    app.setStyleSheet(theme.build_qss(13, "light"))
    panel.deleteLater()


# ==================================================================== 13 resize fixes
def t_card_resize() -> None:
    """The resize hot zone must be on the card.

    On Windows the fully transparent area of a layered window
    (WA_TranslucentBackground) is **click-through**, so a hot zone placed in the
    shadow margin never received mouse events — the panel could not be dragged.
    """
    from knocknock.config import load_config
    from knocknock.panel import CARD_PADDING, RESIZE_BORDER, KnockPanel

    app = QApplication.instance()
    cfg = load_config()
    cfg["ui"]["theme"] = "light"
    cfg["ui"].pop("last_size", None)

    panel = KnockPanel(cfg)
    panel.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    panel.set_context(text="test")
    panel.show()
    app.processEvents()

    # The hot zone must be narrower than the card padding, or it would cover content widgets
    assert RESIZE_BORDER < CARD_PADDING, "the resize hot zone would cover the card content"

    card_rect = panel.card.rect()
    right_edge = QPoint(card_rect.width() - 2, card_rect.height() // 2)
    corner = QPoint(card_rect.width() - 2, card_rect.height() - 2)
    center = QPoint(card_rect.width() // 2, card_rect.height() // 2)

    assert panel._edges_for(right_edge, card_rect) & Qt.Edge.RightEdge, "the card's right edge is not a hot zone"
    corner_edges = panel._edges_for(corner, card_rect)
    assert corner_edges & Qt.Edge.RightEdge and corner_edges & Qt.Edge.BottomEdge, "the bottom-right corner is not a two-way hot zone"
    assert panel._edges_for(center, card_rect) == Qt.Edge(0), "the card centre should not be a hot zone"

    # The hot zone must sit in the strip of the card not covered by child widgets,
    # otherwise real mouse clicks get eaten by children (input / result / buttons all hug the edges).
    right_band = QRect(card_rect.width() - RESIZE_BORDER, 0, RESIZE_BORDER, card_rect.height())
    bottom_band = QRect(0, card_rect.height() - RESIZE_BORDER, card_rect.width(), RESIZE_BORDER)
    for child in panel.card.findChildren(QWidget):
        if not child.isVisible() or child.width() == 0:
            continue
        assert not child.geometry().intersects(right_band), (
            f"{type(child).__name__} covers the right-edge resize hot zone: {child.geometry()}"
        )
        assert not child.geometry().intersects(bottom_band), (
            f"{type(child).__name__} covers the bottom-edge resize hot zone: {child.geometry()}"
        )

    # --- Actually perform a drag by sending events to the card (so the event filter must be installed)
    start_geo = panel.geometry()
    local = QPointF(right_edge)
    global_pos = QPointF(
        start_geo.x() + panel.card.x() + local.x(),
        start_geo.y() + panel.card.y() + local.y(),
    )
    press = QMouseEvent(QEvent.Type.MouseButtonPress, local, global_pos,
                        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                        Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(panel.card, press)
    assert panel._resize_edges != Qt.Edge(0), (
        "the card's right edge did not enter resize state (event filter not effective / hot-zone test wrong)"
    )

    moved = QPointF(global_pos.x() + 80, global_pos.y())
    move = QMouseEvent(QEvent.Type.MouseMove, local, moved,
                       Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
                       Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(panel.card, move)

    release = QMouseEvent(QEvent.Type.MouseButtonRelease, local, moved,
                          Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
                          Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(panel.card, release)

    assert panel._resize_edges == Qt.Edge(0), "resizing did not end on mouse release"
    assert panel.width() >= start_geo.width() + 70, (
        f"the drag did not change the width: {start_geo.width()} -> {panel.width()}"
    )
    assert panel._user_resized is True
    _assert_chips_visible(panel)

    panel.deleteLater()


def t_result_not_clipped() -> None:
    """Invariant: however the panel has been resized, the result area must stay fully inside the card.

    Note: `SetDefaultConstraint` grows the window automatically when the layout's
    minimum size increases, so this cannot fail with the current implementation. It
    guards against a future change of layout strategy (e.g. swapping
    SizeConstraint) pushing the result area out of view — one of the causes of the
    user-visible "nothing appears after sending".
    """
    from knocknock.config import load_config
    from knocknock.panel import RESULT_MIN_HEIGHT, KnockPanel

    app = QApplication.instance()
    cfg = load_config()
    cfg["ui"]["theme"] = "light"
    cfg["ui"]["last_size"] = [520, 430]      # simulate a compact height saved before the result area existed

    panel = KnockPanel(cfg)
    panel.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    panel.set_context(text="DeepSeek")
    panel.show()
    app.processEvents()
    assert panel._user_resized is True, "starting with a last_size should mark it as user-resized"

    # Expand the result area (this is the path taken when a question is sent)
    panel._set_busy(True)
    app.processEvents()

    card = panel.card.rect()
    assert card.contains(panel.result.geometry()), (
        f"the result area overflows the card and is clipped: {panel.result.geometry()} is not inside {card}"
    )
    assert panel.result.height() >= RESULT_MIN_HEIGHT, panel.result.height()

    # The content must really be rendered
    panel._on_succeeded("This is the model's answer.")
    app.processEvents()
    assert "This is the model's answer" in panel.result.toPlainText()
    assert panel.card.rect().contains(panel.result.geometry()), "the result area was squeezed out again after rendering"

    # --- "Reset panel size" should clear the remembered size
    panel.reset_size()
    app.processEvents()
    assert panel._user_resized is False
    assert "last_size" not in panel.cfg["ui"]

    panel.deleteLater()


# ==================================================================== 14 i18n
def t_i18n(app) -> None:
    """Chinese/English switching: string tables, panel retranslation, per-language presets."""
    from knocknock import i18n
    from knocknock.config import load_config, presets_for
    from knocknock.panel import KnockPanel
    from knocknock.settings_dialog import SettingsDialog
    from knocknock.llm import build_user_content

    original = i18n.language()
    try:
        # --- 1. String tables: both languages need every key, and translations must differ
        assert set(i18n._ZH) == set(i18n._EN), (
            "the Chinese and English tables have different keys: "
            f"missing {sorted(set(i18n._ZH) - set(i18n._EN))} / extra {sorted(set(i18n._EN) - set(i18n._ZH))}"
        )
        assert len(i18n._ZH) > 80, f"too few strings: {len(i18n._ZH)}"
        for key in i18n._ZH:
            assert i18n.text(key, "zh").strip(), f"{key} is empty in Chinese"
            assert i18n.text(key, "en").strip(), f"{key} is empty in English"

        assert i18n.set_language("en") == "en"
        assert i18n.t("panel.button.send") == "Send"
        assert i18n.set_language("zh") == "zh"
        assert i18n.t("panel.button.send") == "发送"
        # Various spellings are recognised; unrecognised ones fall back to Chinese and never raise
        for value in ("EN", "en-US", "English"):
            assert i18n.set_language(value) == "en", value
        for value in ("zh-CN", "CN", "", None, "bogus", 123):
            assert i18n.set_language(value) == "zh", value
        # Placeholders must be filled; a missing placeholder must not raise either
        assert i18n.t("panel.meta.chars", count=3) == "3 字"
        assert i18n.t("theme.auto")
        assert i18n.theme_label("dark") in ("深色", "Dark")

        # --- 2. English presets must not be the Chinese set (or the buttons stay Chinese)
        cfg = load_config()
        zh_presets = presets_for(cfg, "zh")
        en_presets = presets_for(cfg, "en")
        assert zh_presets and en_presets, "presets for both languages must be non-empty"
        assert [p["name"] for p in zh_presets] != [p["name"] for p in en_presets]

        # --- 3. Panel: buttons / subtitle / hint must follow the language immediately
        cfg["ui"].pop("last_size", None)
        i18n.set_language("zh")
        panel = KnockPanel(cfg)
        panel.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        panel.set_context(text="selected text used for testing")
        app.processEvents()
        assert panel.send_btn.text() == "发送", panel.send_btn.text()
        assert panel.copy_btn.text() == "复制"
        assert panel.subtitle_label.text() == i18n.t("panel.state.text.short")
        zh_chips = [b.text() for b in panel.chip_buttons]

        i18n.set_language("en")
        panel.retranslate()
        app.processEvents()
        assert panel.send_btn.text() == "Send", panel.send_btn.text()
        assert panel.copy_btn.text() == "Copy"
        assert panel.stop_btn.text() == "Stop"
        assert panel.input.placeholderText() == i18n.t("panel.placeholder")
        assert panel.subtitle_label.text() == i18n.t("panel.state.text.short")
        assert panel.windowTitle() == "Knocknock"
        en_chips = [b.text() for b in panel.chip_buttons]
        assert zh_chips != en_chips, f"preset buttons did not change with the language: {en_chips}"
        assert en_chips == [p["name"] for p in presets_for(cfg, "en")]

        # The "generating" button label must follow the language too
        panel._set_busy(True)
        assert panel.send_btn.text() == i18n.t("panel.button.sending")
        panel._set_busy(False)
        panel.deleteLater()

        # --- 4. Settings dialog: the language dropdown reads and writes, presets go back to the right copy
        i18n.set_language("zh")
        dialog = SettingsDialog(cfg)
        assert dialog.language_box.count() == 2
        assert dialog.language_box.currentData() == "zh"
        assert dialog.windowTitle() == i18n.t("dialog.settings_title")
        dialog.language_box.setCurrentIndex(dialog.language_box.findData("en"))
        collected = dialog._collect()
        assert collected["ui"]["language"] == "en"
        # Opened under the Chinese UI -> still edits the Chinese copy; the English one is untouched
        assert len(collected["presets"]) == len(presets_for(cfg, "zh"))
        assert collected["presets_en"] == cfg["presets_en"]
        dialog.deleteLater()

        # --- 5. Messages sent to the model must be in English too
        i18n.set_language("en")
        content = build_user_content({"text": "hello", "image_png": None}, "summarise this")
        assert "selected on screen" in content, content
        i18n.set_language("zh")
        content = build_user_content({"text": "hello", "image_png": None}, "总结一下")
        assert "选中的屏幕文字" in content, content
    finally:
        i18n.set_language(original)


# ==================================================================== 15 pinned header + double-Alt close
def t_header_pinned() -> None:
    """The title bar must always stay at the top of the card and never move with the panel height.

    Historic bug: with the result area hidden there was no stretchable item in the
    card layout, so Qt spread the surplus vertical space across the gaps between
    items — the title bar drifted down whenever the window grew.
    """
    from knocknock.config import load_config
    from knocknock.panel import KnockPanel

    app = QApplication.instance()
    cfg = load_config()
    cfg["ui"]["theme"] = "light"
    cfg["ui"].pop("last_size", None)

    panel = KnockPanel(cfg)
    panel.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    panel.set_context(text="Selected text used for testing.")
    panel.show()
    app.processEvents()

    layout = panel.card.layout()
    top = layout.itemAt(0).widget()
    assert top is not None, "the first item in the card layout should be the top container"
    header = top.layout().itemAt(0).widget()
    assert header is not None
    assert top.layout().stretch(top.layout().count() - 1) == 1, \
        "the top container must end with a stretch, or surplus space squeezes between items"

    # With the result area hidden (the default), the header must stay pinned at the top at any height
    assert panel.result.isHidden()
    for height in (320, 420, 700, 900, 1200):
        panel.resize(520, height)
        app.processEvents()
        assert header.y() == 0, (
            f"at panel height {height} the header moved to y={header.y()} (it must always be 0)"
        )

    # Once the result area is expanded, the top container should shrink to its content height
    # and the surplus space should all go to the result area
    panel._set_busy(True)
    app.processEvents()

    panel.resize(520, 900)
    app.processEvents()
    assert header.y() == 0, "the header must not move once the result area is expanded"
    top_height_tall = top.height()
    result_height_tall = panel.result.height()

    # Shrink back to "just fits the content": the top container height must not budge,
    # and the reduction can only come out of the result area — that is the invariant itself.
    panel.resize(520, panel._min_height())
    app.processEvents()
    assert header.y() == 0, "the header must not move when shrinking either"
    assert panel.result.height() < result_height_tall, (
        f"the result area should be squeezed when the window shrinks: {panel.result.height()} !< {result_height_tall}"
    )
    assert top.height() == top_height_tall, (
        f"the top container height must not vary with the window: {top.height()} != {top_height_tall}"
    )
    assert panel.result.height() >= 130, panel.result.height()
    assert panel.card.rect().contains(panel.result.geometry()), "the result area overflows the card"

    panel.deleteLater()


def t_double_alt_closes() -> None:
    """Double-tap Alt toggles the panel: close it if open, otherwise read the selection and open it."""
    import main as entry

    controller = entry.KnocknockController(QApplication.instance())
    panel = controller.panel
    app = QApplication.instance()
    try:
        # Stub out the real capture (which would send Ctrl+C to the foreground window)
        captured: list = []
        original_capture = entry.capture_selection
        entry.capture_selection = lambda **kwargs: (captured.append(1), {"text": "selection"})[1]
        try:
            # --- closed -> double-tap Alt opens it
            assert not panel.isVisible()
            controller.on_double_alt()
            app.processEvents()
            assert panel.isVisible(), "double-tapping Alt while closed should open the panel"
            assert captured, "opening should read the selection once"

            # --- open -> double-tap Alt closes it, without reading the selection again
            captured.clear()
            controller.on_double_alt()
            app.processEvents()
            assert not panel.isVisible(), "double-tapping Alt while open should close the panel"
            assert not captured, "closing should not read the selection again"

            # --- double-tap again -> opens again (a toggle, not one-shot)
            controller.on_double_alt()
            app.processEvents()
            assert panel.isVisible()
            assert captured, "reopening should still read the selection"

            # --- the tray's "Close panel" entry must work too
            controller.close_panel()
            assert not panel.isVisible(), "close_panel() should hide the panel"

            # --- with the toggle off, restore the old behaviour: double-tap re-reads while open
            controller.toggle_on_double_alt = False
            controller.on_double_alt()
            app.processEvents()
            assert panel.isVisible()
            captured.clear()
            controller.on_double_alt()
            app.processEvents()
            assert panel.isVisible(), "with the toggle off, double-tapping Alt must not close the panel"
            assert captured, "with the toggle off, double-tapping Alt should re-read the selection"

            # --- the config option must persist and be readable/writable from Settings
            from knocknock.config import DEFAULT_CONFIG
            assert DEFAULT_CONFIG["behavior"]["toggle_on_double_alt"] is True
            from knocknock.settings_dialog import SettingsDialog

            dialog = SettingsDialog(controller.cfg)
            assert dialog.toggle_alt_check.isChecked()
            dialog.toggle_alt_check.setChecked(False)
            assert dialog._collect()["behavior"]["toggle_on_double_alt"] is False
            dialog.deleteLater()
        finally:
            entry.capture_selection = original_capture
    finally:
        panel.hide()
        controller.input_listener.stop()
        controller.tray.hide()
        panel.deleteLater()
        controller.overlay.deleteLater()


def t_double_alt_detection() -> None:
    """The hook logic must read two Alt taps as a double-tap, and Alt+key as a combo.

    GlobalInput._on_key_down is driven directly, so no real keyboard hook is ever
    installed and the test cannot leak a global hook onto the desktop.
    """
    from knocknock.hotkey import VK_ALTS, GlobalInput

    # VK_MENU / VK_LMENU / VK_RMENU: both physical Alt keys count.
    assert VK_ALTS == {0x12, 0xA4, 0xA5}, VK_ALTS

    listener = GlobalInput()
    fired: list = []
    listener.double_alt.connect(lambda: fired.append(1))
    listener._interval = 0.42
    try:
        # A single tap is not enough; the second one fires.
        listener._on_key_down(0x12)
        assert not fired, "one Alt tap must not fire"
        listener._on_key_down(0x12)
        assert len(fired) == 1, "two Alt taps within the window should fire once"

        # The pair is consumed: a third tap starts over instead of firing again.
        listener._on_key_down(0x12)
        assert len(fired) == 1, "a third tap must not fire again"

        # Alt + another key is a combination, not a double-tap.
        listener.reset_state()
        listener._on_key_down(0x12)   # Alt down
        listener._on_key_down(0x09)   # Tab down -> Alt+Tab
        listener._on_key_down(0x12)   # Alt again, but the pending state was cancelled
        assert len(fired) == 1, "Alt+Tab must not be mistaken for a double-tap"

        # Ctrl is no longer a trigger at all.
        listener.reset_state()
        listener._on_key_down(0x11)
        listener._on_key_down(0x11)
        assert len(fired) == 1, "Ctrl must no longer trigger the double-tap"

        # Either physical Alt key may be paired with the other.
        listener.reset_state()
        listener._on_key_down(0xA4)   # left Alt
        listener._on_key_down(0xA5)   # right Alt
        assert len(fired) == 2, "left and right Alt should pair up"

        # Two taps further apart than the interval do not count.
        listener.reset_state()
        listener._on_key_down(0x12)
        listener._first_press -= 10.0   # pretend the first tap was long ago
        listener._on_key_down(0x12)
        assert len(fired) == 2, "taps outside the interval must not fire"
    finally:
        listener.reset_state()


def t_config_key_migration() -> None:
    """A config written before the Alt switch must keep the values the user chose.

    The rename has to happen *before* the merge with DEFAULT_CONFIG. Afterwards
    the defaults have already supplied the new keys, and a value the user picked
    is indistinguishable from one the defaults filled in - a legacy
    `double_ctrl_interval_ms: 500` would silently become the default 420 ms.
    """
    import json
    import tempfile
    from pathlib import Path

    import knocknock.config as config_module
    from knocknock.config import DEFAULT_CONFIG, _rename_legacy_keys

    legacy = {
        "hotkeys": {"double_ctrl_interval_ms": 500, "screenshot": "ctrl+alt+a"},
        "behavior": {"toggle_on_double_ctrl": False, "close_on_esc": True},
    }

    migrated = _rename_legacy_keys(legacy)
    assert migrated["hotkeys"]["double_alt_interval_ms"] == 500, migrated["hotkeys"]
    assert "double_ctrl_interval_ms" not in migrated["hotkeys"], "the old key must be dropped"
    assert migrated["behavior"]["toggle_on_double_alt"] is False, migrated["behavior"]
    assert "toggle_on_double_ctrl" not in migrated["behavior"], "the old key must be dropped"

    # Unrelated keys survive, and the input dict is copied rather than mutated.
    assert migrated["hotkeys"]["screenshot"] == "ctrl+alt+a"
    assert migrated["behavior"]["close_on_esc"] is True
    assert "double_ctrl_interval_ms" in legacy["hotkeys"], "the caller's dict must not be modified"

    # If both names are present the explicit new one wins.
    both = {"hotkeys": {"double_alt_interval_ms": 300, "double_ctrl_interval_ms": 500}}
    assert _rename_legacy_keys(both)["hotkeys"]["double_alt_interval_ms"] == 300

    # The shipped defaults only know the new names.
    assert "double_alt_interval_ms" in DEFAULT_CONFIG["hotkeys"]
    assert "double_ctrl_interval_ms" not in DEFAULT_CONFIG["hotkeys"]
    assert "toggle_on_double_alt" in DEFAULT_CONFIG["behavior"]
    assert "toggle_on_double_ctrl" not in DEFAULT_CONFIG["behavior"]

    # End to end: a legacy file on disk loads under the new names.
    with tempfile.TemporaryDirectory() as tmp:
        legacy_file = Path(tmp) / "config.json"
        legacy_file.write_text(json.dumps(legacy), encoding="utf-8")

        original_config = config_module.CONFIG_PATH
        original_example = config_module.EXAMPLE_PATH
        config_module.CONFIG_PATH = legacy_file
        config_module.EXAMPLE_PATH = Path(tmp) / "no-such-example.json"
        try:
            cfg = config_module.load_config()
            assert cfg["hotkeys"]["double_alt_interval_ms"] == 500, cfg["hotkeys"]
            assert cfg["behavior"]["toggle_on_double_alt"] is False, cfg["behavior"]
            assert "double_ctrl_interval_ms" not in cfg["hotkeys"]
            assert "toggle_on_double_ctrl" not in cfg["behavior"]
        finally:
            config_module.CONFIG_PATH = original_config
            config_module.EXAMPLE_PATH = original_example


# ==================================================================== 16 screenshot growth
def t_screenshot_growth() -> None:
    """A new screenshot must grow the panel into view step by step, not in one jump.

    Historic behaviour: the picture was squeezed into a fixed 150px strip and the
    window never changed size at all, so capturing a region produced a thumbnail
    too small to read.
    """
    from knocknock.config import load_config
    from knocknock.panel import CONTEXT_MAX_HEIGHT, IMAGE_PREVIEW_BOXES, KnockPanel

    app = QApplication.instance()
    cfg = load_config()
    cfg["ui"]["theme"] = "light"
    cfg["ui"]["width"] = 520
    cfg["ui"]["min_width"] = 420
    cfg["ui"]["image_preview"] = "large"
    cfg["ui"].pop("last_size", None)

    panel = KnockPanel(cfg)
    panel.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    # The real screen is whatever this machine has; a fixed 1920x1040 makes the
    # expectations (and therefore the failures) reproducible.
    screen = QRect(0, 0, 1920, 1040)
    panel._screen_available = lambda: screen
    panel.show()
    app.processEvents()
    compact = panel.height()

    image = QPixmap(1200, 800)
    image.fill(QColor("#3A7BD5"))
    panel.set_context(image=image, source="screenshot")
    app.processEvents()

    assert panel._animating, "a freshly captured screenshot should start the growth animation"
    target = panel._image_target
    assert not target.isEmpty(), "no display size was worked out for the screenshot"
    box = IMAGE_PREVIEW_BOXES["large"]
    assert target.width() <= box.width() and target.height() <= box.height(), (
        f"the picture ignores the preview box: {target} > {box}"
    )
    opening = panel.height()
    assert opening < compact + target.height(), (
        "the window jumped to its final size instead of growing into it"
    )

    frames: list = []
    deadline = time.time() + 5.0
    while panel._animating and time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)
        frames.append((panel.width(), panel.height(), panel.context_image.height()))

    assert not panel._animating, "the growth animation never finished"
    distinct = {(w, h) for w, h, _ in frames}
    assert len(distinct) >= 5, f"the window did not grow gradually: only {len(distinct)} sizes seen"
    assert panel.height() > opening, (
        f"the window never actually grew for the picture: {opening} -> {panel.height()}"
    )

    heights = [h for _, _, h in frames]
    assert heights == sorted(heights), f"the picture grew in fits and starts: {heights}"
    assert heights[-1] == target.height(), (heights[-1], target.height())

    # The finished panel really does contain the picture...
    assert panel.context_frame.height() >= target.height(), (
        f"the context block is smaller than the picture: {panel.context_frame.height()} < {target.height()}"
    )
    assert panel.context_image.width() == target.width()
    assert panel.height() >= compact, "the panel should be at least as large as it was"
    # ...it still fits the screen...
    assert panel.y() + panel.height() <= screen.bottom() + 1, "the grown panel runs off the screen"
    assert panel.x() + panel.width() <= screen.right() + 1
    # ...and nothing is clipped.
    assert panel.card.rect().contains(panel.context_image.geometry()), (
        f"the picture is clipped by the card: {panel.context_image.geometry()} not inside {panel.card.rect()}"
    )
    assert panel.height() >= panel.layout().minimumSize().height()

    # A second capture re-runs the growth (it must not be a one-shot)
    panel.set_context(image=QPixmap(600, 900), source="screenshot")
    app.processEvents()
    assert panel._animating, "the second screenshot did not animate either"
    panel._cancel_reveal()

    # A text context is not animated and releases the picture block again
    panel.set_context(text="plain selected text")
    app.processEvents()
    assert not panel._animating
    assert panel._image_target.isEmpty(), "the picture block was not released"
    assert panel.context_frame.maximumHeight() == CONTEXT_MAX_HEIGHT
    assert panel.context_frame.isVisible() and panel.context_image.isHidden()
    assert panel.width() >= panel._min_width()

    # A size the panel took by itself (to fit a picture) must never be remembered
    # as the size the user chose — otherwise one capture silently redefines it.
    remembered: list = []
    panel.size_changed.connect(lambda w, h: remembered.append((w, h)))

    panel._user_resized = True
    panel._user_size = QSize(900, 700)
    panel.hide_panel()
    assert not remembered, "the picture-fitted size was saved as if the user had dragged it"

    panel.resize(900, 700)
    panel.show()
    panel.hide_panel()
    assert remembered and remembered[-1] == (900, 700), remembered

    panel.deleteLater()


# ==================================================================== 17 token budget
def t_token_budget() -> None:
    """The output token budget must default high enough, and 0 must mean "server decides"."""
    from knocknock.config import (
        DEFAULT_CONFIG,
        DEFAULT_MAX_TOKENS,
        MAX_TOKENS_LIMIT,
        _normalize,
    )
    from knocknock.llm import LLMWorker, configured_max_tokens

    assert DEFAULT_CONFIG["api"]["max_tokens"] == DEFAULT_MAX_TOKENS == 4096, (
        "the built-in output budget is too small again"
    )

    # A config still sitting on the old default never chose it -> lifted to the new one
    cfg = {"api": {"max_tokens": 1200}, "ui": {"language": "zh"}}
    _normalize(cfg)
    assert cfg["api"]["max_tokens"] == DEFAULT_MAX_TOKENS, cfg["api"]["max_tokens"]

    # A deliberate value survives; nonsense is repaired instead of crashing the request
    for value, expected in ((8000, 8000), (0, 0), ("bad", DEFAULT_MAX_TOKENS),
                            (10 ** 9, MAX_TOKENS_LIMIT), (-5, 0)):
        cfg = {"api": {"max_tokens": value}, "ui": {"language": "zh"}}
        _normalize(cfg)
        assert cfg["api"]["max_tokens"] == expected, (value, cfg["api"]["max_tokens"])

    assert configured_max_tokens({}) == DEFAULT_MAX_TOKENS
    assert configured_max_tokens({"max_tokens": "2048"}) == 2048
    assert "max_tokens" not in LLMWorker({"max_tokens": 0, "model": "m"}, [])._openai_payload()
    assert LLMWorker({"max_tokens": 6000, "model": "m"}, [])._openai_payload()["max_tokens"] == 6000


# ==================================================================== 18 text / vision models
def t_model_split() -> None:
    """Screenshots go to the vision model, everything else to the text model."""
    from knocknock.config import DEFAULT_CONFIG, IMAGE_PREVIEWS, _normalize
    from knocknock.llm import (
        LLMWorker,
        build_user_content,
        messages_have_image,
        resolve_model,
        test_connection,
    )
    from knocknock.panel import IMAGE_PREVIEW_BOXES, KnockPanel

    assert DEFAULT_CONFIG["api"]["vision_model"] == ""
    assert DEFAULT_CONFIG["ui"]["image_preview"] == "medium"

    text_only = [{"role": "user", "content": "just text"}]
    with_image = [{"role": "user", "content": build_user_content(
        {"text": "", "image_png": b"\x89PNG", "source": "screenshot"}, "what is this")}]

    assert not messages_have_image(text_only)
    assert messages_have_image(with_image)

    cfg = {"model": "deepseek-chat", "vision_model": "qwen-vl-max"}
    assert resolve_model(cfg, text_only) == "deepseek-chat"
    assert resolve_model(cfg, with_image) == "qwen-vl-max"

    # An empty vision model keeps the old single-model behaviour
    assert resolve_model({"model": "deepseek-chat"}, with_image) == "deepseek-chat"
    assert resolve_model({"model": "deepseek-chat", "vision_model": "  "}, with_image) == "deepseek-chat"
    # ... and a config with no model at all still gets a usable default
    assert resolve_model({}, with_image) == "gpt-4o-mini"
    assert resolve_model({"provider": "anthropic"}, with_image) == "gpt-4o-mini"

    assert LLMWorker(cfg, text_only)._openai_payload()["model"] == "deepseek-chat"
    assert LLMWorker(cfg, with_image)._openai_payload()["model"] == "qwen-vl-max"

    # A wrong vision model name must be visible in the error, not guessed at
    err = LLMWorker(cfg, with_image)._describe_http_error(_FakeResponse(404, {"error": {"message": "nope"}}))
    assert "qwen-vl-max" in err, f"the failing model is not named in the error: {err!r}"

    # The connection test must cover both models
    lines = test_connection(cfg).splitlines()
    assert len(lines) == 2, lines
    lines = test_connection({"model": "deepseek-chat", "vision_model": ""}).splitlines()
    assert len(lines) == 2 and "deepseek-chat" not in lines[1], lines

    # Preview tiers: the picture must respect the chosen box, and changing the
    # preference re-fits a picture that is already on screen.
    app = QApplication.instance()
    panel_cfg = {"ui": {"image_preview": "medium", "width": 520, "min_width": 420, "language": "zh"},
                 "api": {}, "hotkeys": {}, "behavior": {}, "presets": [], "presets_en": []}
    _normalize(panel_cfg)
    panel = KnockPanel(panel_cfg)
    panel.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    panel._screen_available = lambda: QRect(0, 0, 1920, 1040)
    panel.show()
    app.processEvents()

    # The width ceiling is the point of the whole thing: a screenshot is context, not
    # something that takes over the desktop, and no tier may creep past it.
    from knocknock.panel import IMAGE_MAX_WIDTH

    assert IMAGE_MAX_WIDTH == 400, IMAGE_MAX_WIDTH
    assert all(box.width() <= IMAGE_MAX_WIDTH for box in IMAGE_PREVIEW_BOXES.values())

    image = QPixmap(3840, 2160)          # deliberately huge, both dimensions
    image.fill(QColor("#3A7BD5"))
    sizes = {}
    for tier in IMAGE_PREVIEWS:
        panel_cfg["ui"]["image_preview"] = tier
        panel.apply_config(panel_cfg)
        panel.set_context(image=image, source="screenshot")
        app.processEvents()
        panel._cancel_reveal()
        target = QSize(panel._image_target)
        assert target.width() <= IMAGE_MAX_WIDTH, (tier, target)
        assert target.width() <= IMAGE_PREVIEW_BOXES[tier].width(), (tier, target)
        assert target.height() <= IMAGE_PREVIEW_BOXES[tier].height(), (tier, target)
        assert panel._image_box().width() <= IMAGE_MAX_WIDTH
        sizes[tier] = target

    assert (sizes["small"].width() < sizes["medium"].width() < sizes["large"].width()), sizes
    assert sizes["small"].height() < sizes["large"].height(), sizes

    # Even a hand-edited config cannot push it past the ceiling
    panel_cfg["ui"]["image_preview"] = "large"
    panel.apply_config(panel_cfg)
    assert panel._image_box().width() <= IMAGE_MAX_WIDTH
    panel._cancel_reveal()

    # A nonsense value falls back to the default instead of breaking the layout
    for bad in ("", None, "enormous", 42):
        panel_cfg["ui"]["image_preview"] = bad
        _normalize(panel_cfg)
        assert panel_cfg["ui"]["image_preview"] == "medium", bad
    assert set(IMAGE_PREVIEW_BOXES) == set(IMAGE_PREVIEWS)
    assert IMAGE_PREVIEW_BOXES["small"].height() < IMAGE_PREVIEW_BOXES["large"].height()

    panel.deleteLater()

    # Both fields must be editable and readable back through Settings
    from knocknock.settings_dialog import SettingsDialog

    dialog_cfg = {
        "api": {"model": "text-model", "vision_model": "vision-model"},
        "ui": {"image_preview": "small", "language": "zh"},
        "hotkeys": {}, "behavior": {}, "presets": [], "presets_en": [],
    }
    _normalize(dialog_cfg)
    dialog = SettingsDialog(dialog_cfg)
    assert dialog.vision_model_edit.text() == "vision-model"
    assert dialog.image_preview_box.currentData() == "small"
    assert dialog._collect()["api"]["vision_model"] == "vision-model"
    assert dialog._collect()["ui"]["image_preview"] == "small"

    dialog.vision_model_edit.setText("other-vision")
    dialog.image_preview_box.setCurrentIndex(dialog.image_preview_box.findData("large"))
    collected = dialog._collect()
    assert collected["api"]["vision_model"] == "other-vision", collected["api"]
    assert collected["ui"]["image_preview"] == "large", collected["ui"]
    dialog.deleteLater()


class _FakeResponse:
    """Minimal stand-in for a requests response, for the error-formatting path."""

    def __init__(self, status_code: int, body: dict) -> None:
        self.status_code = status_code
        self._body = body
        self.text = json.dumps(body)

    def json(self) -> dict:
        return self._body


# ==================================================================== main
def main() -> int:
    app = QCoreApplication.instance() or QApplication(sys.argv)
    if isinstance(app, QApplication):
        from knocknock import theme
        from knocknock.config import load_config

        app.setStyleSheet(theme.build_qss(int(load_config()["ui"]["font_size"])))

    section("1. Config loading and merging")
    case("config read / default fill-in / dotted lookup", t_config)
    case("frozen build stores config next to the executable", t_config_paths_frozen)
    case("legacy Ctrl keys migrate to the Alt names", t_config_key_migration)

    section("2. Hotkey parsing")
    case("combo and function key parsing", t_hotkey_parse)

    section("3. Message construction")
    case("text / screenshot / Anthropic message conversion", t_user_content)

    section("4. Stylesheet")
    case("QSS integrity", t_qss)

    section("5. UI and question flow")
    case("panel / icons / settings dialog / streaming rendering", t_panel)

    section("6. Screen capture and cropping")
    case("virtual desktop stitching / high-DPI cropping / bounds protection", t_capture)

    section("7. Clipboard and selection")
    case("clipboard read-write / no-selection fallback / image selection", t_selection)

    section("8. Model calls (local mock)")
    case("streaming / vision request / 401 hint / Anthropic / interruption", lambda: t_llm(app))

    section("9. Tray icon uniqueness")
    case("repeated settings saves do not add tray icons", t_tray)

    section("10. Panel resizing")
    case("freely resizable and presets are never clipped", t_resizable)

    section("11. Light / dark theme")
    case("theme switch / icon refresh / settings preview and restore", t_theme_toggle)

    section("12. Shadow and tooltips")
    case("shadow not cut by the window edge / tooltips follow the theme and stay readable", t_shadow_and_tooltip)

    section("13. Panel resizing (drag path)")
    case("card edge / bottom-right corner drag-to-resize", t_card_resize)
    case("result area stays fully visible after a manual resize", t_result_not_clipped)

    section("14. Chinese / English switching")
    case("string tables / panel retranslation / per-language presets", lambda: t_i18n(app))

    section("15. Pinned header and double-Alt close")
    case("title bar stays pinned (no drift as the window grows)", t_header_pinned)
    case("double-tap Alt toggles the panel + tray close entry", t_double_alt_closes)
    case("Alt pair fires; Alt+key and Ctrl do not", t_double_alt_detection)

    section("16. Screenshot growth")
    case("a new picture grows the panel into view step by step", t_screenshot_growth)

    section("17. Output token budget")
    case("default is generous / 0 means server decides / nonsense is repaired", t_token_budget)

    section("18. Text / vision model split")
    case("screenshots use the vision model / preview tiers are respected", t_model_split)

    print("\n" + "=" * 56)
    print(f"Passed {len(PASSED)}, failed {len(FAILED)}")
    if FAILED:
        for name in FAILED:
            print(f"  FAILED: {name}")
        return 1
    print("All self-tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
