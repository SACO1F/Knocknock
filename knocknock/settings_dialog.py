"""Settings dialog: model API, presets, appearance (theme / language / size) and behaviour."""
from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from . import i18n
from . import theme
from .config import (
    DEFAULT_IMAGE_PREVIEW,
    DEFAULT_MAX_TOKENS,
    IMAGE_PREVIEWS,
    MAX_TOKENS_LIMIT,
    presets_for,
    presets_key,
    save_config,
)


class SettingsDialog(QDialog):
    """Settings dialog. When exec() returns Accepted, self.cfg holds the latest configuration."""

    def __init__(self, cfg: Dict[str, Any], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.cfg = copy.deepcopy(cfg)
        self.setObjectName("Settings")
        self.setWindowTitle(i18n.t("dialog.settings_title"))
        self.setMinimumWidth(580)
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)

        # Remember the theme we entered with so Cancel can restore it (the
        # appearance tab previews changes live).
        self._original_theme = theme.mode()
        self._original_font = int(self.cfg["ui"].get("font_size", 13))
        self.reset_size_requested = False
        # Presets are stored per language: what gets edited here is the copy for
        # the language active when the window opened, so switching language later
        # cannot overwrite the other copy.
        self._preset_lang = i18n.normalize_language(self.cfg["ui"].get("language"))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 14)
        layout.setSpacing(12)

        tabs = QTabWidget(self)
        tabs.addTab(self._build_api_tab(), i18n.t("settings.tab.api"))
        tabs.addTab(self._build_preset_tab(), i18n.t("settings.tab.presets"))
        tabs.addTab(self._build_appearance_tab(), i18n.t("settings.tab.appearance"))
        tabs.addTab(self._build_behavior_tab(), i18n.t("settings.tab.behavior"))
        layout.addWidget(tabs)

        # Deliberately not a QDialogButtonBox — it overrides the buttons'
        # stylesheets (#Primary / #Ghost would stop applying). We lay out our own
        # row instead, so the styling stays fully under control.
        row = QHBoxLayout()
        row.setSpacing(8)
        self.test_btn = QPushButton(i18n.t("settings.button.test"), self)
        self.test_btn.setObjectName("Ghost")
        self.test_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.test_btn.clicked.connect(self._test_connection)
        row.addWidget(self.test_btn)
        row.addStretch(1)

        self.cancel_btn = QPushButton(i18n.t("settings.button.cancel"), self)
        self.cancel_btn.setObjectName("Ghost")
        self.cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_btn.clicked.connect(self.reject)
        row.addWidget(self.cancel_btn)

        self.save_btn = QPushButton(i18n.t("settings.button.save"), self)
        self.save_btn.setObjectName("Primary")
        self.save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_btn.setDefault(True)
        self.save_btn.clicked.connect(self._on_accept)
        row.addWidget(self.save_btn)

        layout.addLayout(row)

    # ---------------------------------------------------------------- model API
    def _build_api_tab(self) -> QWidget:
        page = QWidget(self)
        form = QFormLayout(page)
        form.setContentsMargins(12, 14, 12, 12)
        form.setSpacing(10)
        api = self.cfg["api"]

        self.provider_box = QComboBox(page)
        self.provider_box.addItem(i18n.t("settings.api.provider.openai"), "openai")
        self.provider_box.addItem(i18n.t("settings.api.provider.anthropic"), "anthropic")
        index = self.provider_box.findData(api.get("provider", "openai"))
        self.provider_box.setCurrentIndex(max(0, index))
        form.addRow(self._label(i18n.t("settings.api.provider")), self.provider_box)

        self.base_url_edit = QLineEdit(str(api.get("base_url", "")), page)
        self.base_url_edit.setPlaceholderText("https://api.openai.com/v1")
        form.addRow(self._label(i18n.t("settings.api.base_url")), self.base_url_edit)

        self.api_key_edit = QLineEdit(str(api.get("api_key", "")), page)
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText("sk-...")
        form.addRow(self._label(i18n.t("settings.api.api_key")), self.api_key_edit)

        self.model_edit = QLineEdit(str(api.get("model", "")), page)
        self.model_edit.setPlaceholderText("gpt-4o-mini / deepseek-chat / qwen-plus …")
        form.addRow(self._label(i18n.t("settings.api.model")), self.model_edit)

        self.vision_model_edit = QLineEdit(str(api.get("vision_model", "")), page)
        self.vision_model_edit.setPlaceholderText("gpt-4o / qwen-vl-max / glm-4v …")
        form.addRow(self._label(i18n.t("settings.api.vision_model")), self.vision_model_edit)

        vision_tip = QLabel(i18n.t("settings.api.vision_model_tip"), page)
        vision_tip.setObjectName("Hint")
        vision_tip.setWordWrap(True)
        form.addRow("", vision_tip)

        self.temperature_spin = QDoubleSpinBox(page)
        self.temperature_spin.setRange(0.0, 2.0)
        self.temperature_spin.setSingleStep(0.1)
        self.temperature_spin.setValue(float(api.get("temperature", 0.3)))
        form.addRow(self._label(i18n.t("settings.api.temperature")), self.temperature_spin)

        self.max_tokens_spin = QSpinBox(page)
        self.max_tokens_spin.setRange(0, MAX_TOKENS_LIMIT)
        self.max_tokens_spin.setSingleStep(256)
        # 0 is a real choice, not a mistake: it means "let the server decide".
        self.max_tokens_spin.setSpecialValueText(i18n.t("settings.api.max_tokens_auto"))
        self.max_tokens_spin.setValue(int(api.get("max_tokens", DEFAULT_MAX_TOKENS)))
        form.addRow(self._label(i18n.t("settings.api.max_tokens")), self.max_tokens_spin)

        tokens_tip = QLabel(i18n.t("settings.api.max_tokens_tip"), page)
        tokens_tip.setObjectName("Hint")
        tokens_tip.setWordWrap(True)
        form.addRow("", tokens_tip)

        self.stream_check = QCheckBox(i18n.t("settings.api.stream"), page)
        self.stream_check.setChecked(bool(api.get("stream", True)))
        form.addRow("", self.stream_check)

        self.system_prompt_edit = QTextEdit(page)
        self.system_prompt_edit.setObjectName("SystemPrompt")
        self.system_prompt_edit.setFixedHeight(96)
        self.system_prompt_edit.setPlainText(str(api.get("system_prompt", "")))
        form.addRow(self._label(i18n.t("settings.api.system_prompt")), self.system_prompt_edit)

        tip = QLabel(i18n.t("settings.api.tip"), page)
        tip.setObjectName("Hint")
        tip.setWordWrap(True)
        form.addRow("", tip)
        return page

    # ---------------------------------------------------------------- presets
    def _build_preset_tab(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 14, 12, 12)
        layout.setSpacing(8)

        hint = QLabel(i18n.t("settings.preset.hint"), page)
        hint.setObjectName("Hint")
        layout.addWidget(hint)

        self.preset_table = QTableWidget(0, 2, page)
        self.preset_table.setHorizontalHeaderLabels(
            [i18n.t("settings.preset.col_name"), i18n.t("settings.preset.col_prompt")]
        )
        self.preset_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.preset_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.preset_table.verticalHeader().setVisible(False)
        self.preset_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        for preset in presets_for(self.cfg, self._preset_lang):
            self._append_preset_row(str(preset.get("name", "")), str(preset.get("prompt", "")))
        layout.addWidget(self.preset_table, 1)

        row = QHBoxLayout()
        add_btn = QPushButton(i18n.t("settings.preset.add"), page)
        add_btn.setObjectName("Ghost")
        add_btn.clicked.connect(
            lambda: self._append_preset_row(i18n.t("settings.preset.new_name"), "")
        )
        remove_btn = QPushButton(i18n.t("settings.preset.remove"), page)
        remove_btn.setObjectName("Ghost")
        remove_btn.clicked.connect(self._remove_preset_row)
        row.addWidget(add_btn)
        row.addWidget(remove_btn)
        row.addStretch(1)
        layout.addLayout(row)
        return page

    def _append_preset_row(self, name: str, prompt: str) -> None:
        row = self.preset_table.rowCount()
        self.preset_table.insertRow(row)
        self.preset_table.setItem(row, 0, QTableWidgetItem(name))
        self.preset_table.setItem(row, 1, QTableWidgetItem(prompt))

    def _remove_preset_row(self) -> None:
        rows = sorted({index.row() for index in self.preset_table.selectedIndexes()}, reverse=True)
        for row in rows:
            self.preset_table.removeRow(row)

    # ---------------------------------------------------------------- appearance
    def _build_appearance_tab(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 14, 12, 12)
        layout.setSpacing(12)

        ui = self.cfg["ui"]
        form = QFormLayout()
        form.setSpacing(10)

        self.theme_box = QComboBox(page)
        labels = theme.mode_labels()
        for value in ("light", "dark", "auto"):
            self.theme_box.addItem(labels[value], value)
        index = self.theme_box.findData(str(ui.get("theme", "light")))
        self.theme_box.setCurrentIndex(max(0, index))
        self.theme_box.currentIndexChanged.connect(self._preview_theme)
        form.addRow(self._label(i18n.t("settings.appearance.theme")), self.theme_box)

        language_row = QHBoxLayout()
        language_row.setSpacing(8)
        self.language_box = QComboBox(page)
        for value in i18n.LANGUAGES:
            self.language_box.addItem(i18n.LANGUAGE_LABELS[value], value)
        index = self.language_box.findData(i18n.normalize_language(ui.get("language")))
        self.language_box.setCurrentIndex(max(0, index))
        language_row.addWidget(self.language_box)
        language_note = QLabel(i18n.t("settings.appearance.language_note"), page)
        language_note.setObjectName("Hint")
        language_row.addWidget(language_note, 1)
        form.addRow(self._label(i18n.t("settings.appearance.language")), language_row)

        self.opacity_spin = QDoubleSpinBox(page)
        self.opacity_spin.setRange(0.6, 1.0)
        self.opacity_spin.setSingleStep(0.01)
        self.opacity_spin.setValue(float(ui.get("opacity", 0.99)))
        form.addRow(self._label(i18n.t("settings.appearance.opacity")), self.opacity_spin)

        self.font_size_spin = QSpinBox(page)
        self.font_size_spin.setRange(11, 18)
        self.font_size_spin.setSuffix(" px")
        self.font_size_spin.setValue(int(ui.get("font_size", 13)))
        self.font_size_spin.valueChanged.connect(self._preview_theme)
        form.addRow(self._label(i18n.t("settings.appearance.font_size")), self.font_size_spin)

        self.image_preview_box = QComboBox(page)
        for value in IMAGE_PREVIEWS:
            self.image_preview_box.addItem(i18n.t(f"settings.appearance.image_preview.{value}"), value)
        index = self.image_preview_box.findData(
            str(ui.get("image_preview", DEFAULT_IMAGE_PREVIEW)).lower()
        )
        self.image_preview_box.setCurrentIndex(max(0, index))
        form.addRow(self._label(i18n.t("settings.appearance.image_preview")), self.image_preview_box)

        preview_tip = QLabel(i18n.t("settings.appearance.image_preview_tip"), page)
        preview_tip.setObjectName("Hint")
        preview_tip.setWordWrap(True)
        form.addRow("", preview_tip)

        layout.addLayout(form)

        size_row = QHBoxLayout()
        size_row.setSpacing(8)
        self.reset_size_btn = QPushButton(i18n.t("settings.appearance.reset_size"), page)
        self.reset_size_btn.setObjectName("Ghost")
        self.reset_size_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reset_size_btn.clicked.connect(self._request_reset_size)
        size_row.addWidget(self.reset_size_btn)
        self.size_state = QLabel("", page)
        self.size_state.setObjectName("Hint")
        size_row.addWidget(self.size_state)
        size_row.addStretch(1)
        layout.addLayout(size_row)

        note = QLabel(i18n.t("settings.appearance.note"), page)
        note.setObjectName("Hint")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)
        self._refresh_size_state()
        return page

    def _request_reset_size(self) -> None:
        self.reset_size_requested = True
        self._refresh_size_state()

    def _refresh_size_state(self) -> None:
        saved = self.cfg.get("ui", {}).get("last_size")
        if self.reset_size_requested:
            self.size_state.setText(i18n.t("settings.appearance.size_reset"))
        elif isinstance(saved, (list, tuple)) and len(saved) == 2:
            self.size_state.setText(
                i18n.t("settings.appearance.size_saved", width=int(saved[0]), height=int(saved[1]))
            )
        else:
            self.size_state.setText(i18n.t("settings.appearance.size_default"))

    def _preview_theme(self) -> None:
        """Preview the effect immediately when theme / font size changes on the appearance tab."""
        app = QApplication.instance()
        if app is None:
            return
        app.setStyleSheet(
            theme.build_qss(int(self.font_size_spin.value()), self.theme_box.currentData())
        )

    def _restore_original_theme(self) -> None:
        app = QApplication.instance()
        theme.set_mode(self._original_theme)
        if app is not None:
            app.setStyleSheet(theme.build_qss(self._original_font, self._original_theme))

    def reject(self) -> None:  # noqa: D102
        self._restore_original_theme()
        super().reject()

    # ---------------------------------------------------------------- behaviour
    def _build_behavior_tab(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 14, 12, 12)
        layout.setSpacing(10)

        behavior = self.cfg["behavior"]
        hotkeys = self.cfg["hotkeys"]

        self.double_alt_spin = QSpinBox(page)
        self.double_alt_spin.setRange(150, 1000)
        self.double_alt_spin.setSingleStep(10)
        self.double_alt_spin.setSuffix(" ms")
        self.double_alt_spin.setValue(int(hotkeys.get("double_alt_interval_ms", 420)))

        self.screenshot_edit = QLineEdit(str(hotkeys.get("screenshot", "ctrl+alt+a")), page)
        self.ask_edit = QLineEdit(str(hotkeys.get("ask_selection", "ctrl+alt+q")), page)

        form = QFormLayout()
        form.setSpacing(10)
        form.addRow(self._label(i18n.t("settings.behavior.interval")), self.double_alt_spin)
        form.addRow(self._label(i18n.t("settings.behavior.screenshot_hotkey")), self.screenshot_edit)
        form.addRow(self._label(i18n.t("settings.behavior.ask_hotkey")), self.ask_edit)
        layout.addLayout(form)

        self.restore_check = QCheckBox(i18n.t("settings.behavior.restore_clipboard"), page)
        self.restore_check.setChecked(bool(behavior.get("restore_clipboard", False)))
        layout.addWidget(self.restore_check)

        self.autosend_check = QCheckBox(i18n.t("settings.behavior.autosend"), page)
        self.autosend_check.setChecked(bool(behavior.get("auto_send_on_preset", True)))
        layout.addWidget(self.autosend_check)

        self.esc_check = QCheckBox(i18n.t("settings.behavior.esc"), page)
        self.esc_check.setChecked(bool(behavior.get("close_on_esc", True)))
        layout.addWidget(self.esc_check)

        self.toggle_alt_check = QCheckBox(i18n.t("settings.behavior.toggle_double_alt"), page)
        self.toggle_alt_check.setChecked(bool(behavior.get("toggle_on_double_alt", True)))
        layout.addWidget(self.toggle_alt_check)

        layout.addStretch(1)
        return page

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def _label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("FieldLabel")
        return label

    def _collect(self) -> Dict[str, Any]:
        cfg = copy.deepcopy(self.cfg)
        api = cfg["api"]
        api["provider"] = self.provider_box.currentData()
        api["base_url"] = self.base_url_edit.text().strip()
        api["api_key"] = self.api_key_edit.text().strip()
        api["model"] = self.model_edit.text().strip()
        api["vision_model"] = self.vision_model_edit.text().strip()
        api["temperature"] = float(self.temperature_spin.value())
        api["max_tokens"] = int(self.max_tokens_spin.value())
        api["stream"] = bool(self.stream_check.isChecked())
        api["system_prompt"] = self.system_prompt_edit.toPlainText().strip()

        presets: List[Dict[str, str]] = []
        for row in range(self.preset_table.rowCount()):
            name_item = self.preset_table.item(row, 0)
            prompt_item = self.preset_table.item(row, 1)
            name = (name_item.text() if name_item else "").strip()
            prompt = (prompt_item.text() if prompt_item else "").strip()
            if name and prompt:
                presets.append({"name": name, "prompt": prompt})
        # Write back into the copy for the language active when the window
        # opened; the other copy is left untouched.
        cfg[presets_key(self._preset_lang)] = presets

        ui = cfg["ui"]
        ui["theme"] = self.theme_box.currentData()
        ui["language"] = i18n.normalize_language(self.language_box.currentData())
        ui["opacity"] = float(self.opacity_spin.value())
        ui["font_size"] = int(self.font_size_spin.value())
        ui["image_preview"] = str(self.image_preview_box.currentData())
        # width / min_width are kept as internal parameters only; they are no
        # longer exposed in the UI (you resize the panel by dragging it).
        if self.reset_size_requested:
            ui.pop("last_size", None)

        behavior = cfg["behavior"]
        behavior["restore_clipboard"] = bool(self.restore_check.isChecked())
        behavior["auto_send_on_preset"] = bool(self.autosend_check.isChecked())
        behavior["close_on_esc"] = bool(self.esc_check.isChecked())
        behavior["toggle_on_double_alt"] = bool(self.toggle_alt_check.isChecked())

        hotkeys = cfg["hotkeys"]
        hotkeys["double_alt_interval_ms"] = int(self.double_alt_spin.value())
        hotkeys["screenshot"] = self.screenshot_edit.text().strip()
        hotkeys["ask_selection"] = self.ask_edit.text().strip()
        return cfg

    def _test_connection(self) -> None:
        from .llm import test_connection

        cfg = self._collect()
        QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            message = test_connection(cfg["api"])
        finally:
            QGuiApplication.restoreOverrideCursor()
        QMessageBox.information(self, i18n.t("dialog.connection_test"), message)

    def _on_accept(self) -> None:
        self.cfg = self._collect()
        try:
            save_config(self.cfg)
        except OSError as exc:
            QMessageBox.warning(self, i18n.t("dialog.save_failed"), str(exc))
            return
        self.accept()
