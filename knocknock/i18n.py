"""Chinese/English localisation for every user-facing string.

Usage:
    i18n.set_language("en")        # switch language; rebuilt pages pick it up
    i18n.t("panel.button.send")    # look up a key in the current language
    i18n.text("llm.system_prompt", "zh")   # look up a key in a given language

Design notes:
  * The project is small, so a plain "string table + t()" approach is lighter
    than Qt's .ts/.qm translation pipeline — no lupdate / lrelease required.
  * A missing key falls back to Chinese, then to the key itself, so an
    untranslated string degrades gracefully instead of crashing.
  * This module imports nothing else from the package, which keeps the
    dependency graph acyclic.
"""
from __future__ import annotations

from typing import Dict, Optional

ZH = "zh"
EN = "en"
LANGUAGES = (ZH, EN)
# 语言下拉里显示的名字（本身就是语言自称，不随界面语言变化）
LANGUAGE_LABELS = {ZH: "简体中文", EN: "English"}

_current = ZH

# ---------------------------------------------------------------- Chinese table
_ZH: Dict[str, str] = {
    # app / tray
    "app.name": "Knocknock",
    "app.tray_tooltip": "Knocknock —— 双击 Ctrl 划词问答",
    "tray.menu.screenshot": "截图选区（{hotkey}）",
    "tray.menu.ask": "读取选中文字（{hotkey}）",
    "tray.menu.show": "显示面板（双击 Ctrl）",
    "tray.menu.hide": "关闭面板（双击 Ctrl）",
    "tray.menu.settings": "设置…",
    "tray.menu.quit": "退出 Knocknock",
    # 消息框 / 通知
    "dialog.tray_unavailable": "系统托盘不可用，程序无法运行。",
    "dialog.already_running": "Knocknock 已经在运行中，请查看系统托盘图标。",
    "dialog.settings_title": "Knocknock 设置",
    "dialog.connection_test": "连接测试",
    "dialog.save_failed": "保存失败",
    "notify.started.title": "Knocknock 已启动",
    "notify.started.body": (
        "首次使用请先在「设置」中填写 API Key。\n"
        "双击 Ctrl 唤起面板，Ctrl+Alt+A 截图选区。"
    ),
    # 主题
    "theme.light": "浅色",
    "theme.dark": "深色",
    "theme.auto": "跟随系统",
    "theme.toggle_tooltip": "切换深色 / 浅色",
    "theme.switch_to_light": "切换到浅色模式",
    "theme.switch_to_dark": "切换到深色模式",
    # panel
    "panel.title": "Knocknock",
    "panel.subtitle.long": "双击 Ctrl 唤起 / 收起 · 选中内容后提问",
    "panel.subtitle.short": "双击 Ctrl 唤起 / 收起",
    "panel.tooltip.pin": "窗口置顶",
    "panel.tooltip.crop": "截图选区 (Ctrl+Alt+A)",
    "panel.tooltip.settings": "设置",
    "panel.tooltip.close": "隐藏 (Esc)",
    "panel.placeholder": "输入你的指令，例如：翻译成日语 / 这段代码哪里有问题…",
    "panel.hint.send": "Enter 发送 · Shift+Enter 换行",
    "panel.button.copy": "复制",
    "panel.button.stop": "停止",
    "panel.button.send": "发送",
    "panel.button.sending": "生成中…",
    "panel.badge.text": "选中文字",
    "panel.badge.image": "屏幕截图",
    "panel.meta.chars": "{count} 字",
    "panel.state.no_context.long": "未检测到选中内容，可截图或直接输入",
    "panel.state.no_context.short": "未检测到选中内容",
    "panel.state.image.long": "截图已就绪，输入指令",
    "panel.state.image.short": "截图已就绪",
    "panel.state.text.long": "已读取选中文字，输入指令",
    "panel.state.text.short": "已读取选中文字",
    "panel.msg.need_context": "请先选中屏幕上的内容，或直接输入指令。",
    "panel.msg.no_api_key": (
        "尚未配置 API Key。\n"
        "点击右上角 ⚙ 打开设置，填入 API Key 后即可使用。"
    ),
    "panel.msg.generating": "_正在生成…_",
    "panel.msg.request_failed": "**请求失败**",
    "panel.msg.empty_reply": (
        "模型没有返回任何内容。\n\n"
        "可以依次排查：\n"
        "1. **模型名**是否正确、账号是否有额度；\n"
        "2. **最大输出 tokens** 是否太小（推理型模型会先消耗在思考上）；\n"
        "3. 截图提问走的是「设置 → 模型接口 → **视觉模型**」，确认它已填写且是多模态模型"
        "（gpt-4o / qwen-vl-max / glm-4v 等）；\n"
        "4. 到「设置 → 模型接口」点一下**测试连接**看返回什么。"
    ),
    # 设置窗口
    "settings.tab.api": "模型接口",
    "settings.tab.presets": "预置指令",
    "settings.tab.appearance": "外观",
    "settings.tab.behavior": "行为",
    "settings.button.test": "测试连接",
    "settings.button.cancel": "取消",
    "settings.button.save": "保存",
    "settings.api.provider": "接口协议",
    "settings.api.provider.openai": "OpenAI 兼容接口（OpenAI / DeepSeek / 通义 / Kimi / 本地 Ollama…）",
    "settings.api.provider.anthropic": "Anthropic Claude",
    "settings.api.base_url": "Base URL",
    "settings.api.api_key": "API Key",
    "settings.api.model": "语言模型（文字提问）",
    "settings.api.vision_model": "视觉模型（截图提问）",
    "settings.api.vision_model_tip": (
        "截图会走视觉模型，文字提问走语言模型。视觉模型**留空**表示两者共用一个模型。"
        "点下面的「测试连接」会两个模型都测一遍。"
    ),
    "settings.api.temperature": "Temperature",
    "settings.api.max_tokens": "最大输出 tokens",
    "settings.api.max_tokens_auto": "由服务端决定",
    "settings.api.max_tokens_tip": (
        "太小会把回答从中间截断（推理型模型还会先花 tokens 思考，正文可能一个字都没有）。"
        "默认 4096，够写完整的解释和代码；填 0 则不限制，交给服务端用自己的上限；"
        "填得比模型上限还大，接口会直接报错。"
    ),
    "settings.api.stream": "流式输出（逐字显示）",
    "settings.api.system_prompt": "系统提示词",
    "settings.api.tip": "提示：截图提问需要支持视觉的模型（如 gpt-4o / qwen-vl-max / glm-4v 等），填在「视觉模型」里。",
    "settings.preset.hint": "这些按钮会出现在面板上，点击即用当前选中内容执行对应指令。",
    "settings.preset.col_name": "按钮名称",
    "settings.preset.col_prompt": "发给模型的指令",
    "settings.preset.add": "新增",
    "settings.preset.remove": "删除选中",
    "settings.preset.new_name": "新指令",
    "settings.appearance.theme": "主题",
    "settings.appearance.language": "界面语言",
    "settings.appearance.language_note": "语言切换在保存后生效；预置指令按语言分别保存。",
    "settings.appearance.opacity": "面板不透明度",
    "settings.appearance.font_size": "界面字号",
    "settings.appearance.image_preview": "截图显示尺寸",
    "settings.appearance.image_preview.small": "小（240 px 宽）",
    "settings.appearance.image_preview.medium": "中（320 px 宽，默认）",
    "settings.appearance.image_preview.large": "大（400 px 宽，上限）",
    "settings.appearance.image_preview_tip": (
        "截图只是提问的上下文，所以宽度封顶在 400 px，怎么调都不会更宽；"
        "高度按比例走。换档位后面板会平滑地重新收放一次。"
    ),
    "settings.appearance.reset_size": "恢复默认尺寸",
    "settings.appearance.size_saved": "当前记住的是 {width} × {height}",
    "settings.appearance.size_default": "当前使用默认尺寸",
    "settings.appearance.size_reset": "已标记恢复，保存后生效",
    "settings.appearance.note": (
        "面板大小直接用鼠标拖出来：按住面板的**边缘**或**右下角**拖动即可，"
        "高度不够时结果区会自动扩展。\n"
        "全部预置按钮会随宽度自动换行，永远不会被裁掉；调好的尺寸会被记住，"
        "下次打开沿用。"
    ),
    "settings.behavior.interval": "双击 Ctrl 判定间隔",
    "settings.behavior.screenshot_hotkey": "截图选区热键",
    "settings.behavior.ask_hotkey": "读取选中文字热键",
    "settings.behavior.restore_clipboard": "读取选中文字后还原剪贴板内容",
    "settings.behavior.autosend": "点击预置指令后自动发送",
    "settings.behavior.esc": "按 Esc 隐藏面板",
    "settings.behavior.toggle_double_ctrl": "面板已打开时，再双击 Ctrl 关闭它",
    # 杂项
    "hotkey.unset": "未设置",
    "capture.hint": "拖拽鼠标框选区域   ·   Esc / 右键 取消   ·   Enter 确认",
    # 大模型
    "llm.system_prompt": (
        "你是 Knocknock 助手。用户会给你一段来自屏幕的选中内容（文字或截图），"
        "并按你的指令提问。请直接给出答案，语言与用户提问保持一致，"
        "简洁、准确、条理清晰。涉及代码时使用 Markdown 代码块。"
    ),
    "llm.fallback_system": "你是一个简洁准确的助手。",
    "llm.label.selection": "我选中的屏幕文字",
    "llm.label.screenshot": "我截图中的文字",
    "llm.wrap.text": '以下是我的{label}：\n"""\n{text}\n"""',
    "llm.wrap.image": "以下是我截取的屏幕区域图片，请结合图片内容回答。",
    "llm.wrap.ask": "我的要求：{ask}",
    "llm.wrap.ask_default": "请解释说明以上内容。",
    "llm.error.timeout": "请求超时，请检查网络或调大超时时间。",
    "llm.error.connection": "无法连接到 API 服务：{detail}",
    "llm.error.not_sse": (
        "服务端返回的不是流式（SSE）数据，也无法按 JSON 解析。\n\n"
        "原始内容：\n{body}"
    ),
    "llm.error.no_text": "服务端返回里没有正文内容：\n{body}",
    "llm.error.reasoning_only": (
        "模型只输出了推理过程、没有正文，通常是 **max_tokens 太小** 被截断了。\n"
        "请到「设置 → 模型接口」把「最大输出 tokens」再调大（比如 8000），"
        "或填 0 交给服务端决定后重试。\n\n"
        "推理过程（节选）：\n{reasoning}"
    ),
    "llm.error.unknown": "未知错误",
    "llm.error.anthropic_stream": "服务端没有返回流式数据，原始内容：\n{body}",
    "llm.error.http": "请求失败 {status} {hint}\n模型：{model}\n{detail}",
    "llm.hint.401": "（API Key 无效或未填写，请在设置里检查）",
    "llm.hint.403": "（没有访问权限，请检查模型名或账号权限）",
    "llm.hint.404": "（接口地址或模型名不存在，请检查 Base URL）",
    "llm.hint.429": "（请求过于频繁或额度不足）",
    "llm.test.system": "你是测试助手。",
    "llm.test.user": "回复两个字：连接成功",
    "llm.test.ok": "成功：{text}",
    "llm.test.fail": "失败：{text}",
    "llm.test.empty": "(空回复)",
    "llm.test.line": "{label}：{result}",
    "llm.test.text_label": "语言模型",
    "llm.test.vision_label": "视觉模型",
    "llm.test.vision_same": "{label}：未单独设置，与语言模型相同",
}

# ---------------------------------------------------------------- English table
_EN: Dict[str, str] = {
    "app.name": "Knocknock",
    "app.tray_tooltip": "Knocknock — double-tap Ctrl to ask about anything on screen",
    "tray.menu.screenshot": "Capture region ({hotkey})",
    "tray.menu.ask": "Read selected text ({hotkey})",
    "tray.menu.show": "Show panel (double-tap Ctrl)",
    "tray.menu.hide": "Close panel (double-tap Ctrl)",
    "tray.menu.settings": "Settings…",
    "tray.menu.quit": "Quit Knocknock",
    "dialog.tray_unavailable": "The system tray is unavailable, so Knocknock cannot run.",
    "dialog.already_running": "Knocknock is already running — check the system tray.",
    "dialog.settings_title": "Knocknock Settings",
    "dialog.connection_test": "Connection test",
    "dialog.save_failed": "Save failed",
    "notify.started.title": "Knocknock is running",
    "notify.started.body": (
        "Please fill in your API Key under Settings first.\n"
        "Double-tap Ctrl to open the panel; Ctrl+Alt+A to capture a region."
    ),
    "theme.light": "Light",
    "theme.dark": "Dark",
    "theme.auto": "Follow system",
    "theme.toggle_tooltip": "Toggle light / dark theme",
    "theme.switch_to_light": "Switch to light mode",
    "theme.switch_to_dark": "Switch to dark mode",
    "panel.title": "Knocknock",
    "panel.subtitle.long": "Double-tap Ctrl to open / close · then ask about the selection",
    "panel.subtitle.short": "Double-tap Ctrl to open / close",
    "panel.tooltip.pin": "Keep on top",
    "panel.tooltip.crop": "Capture region (Ctrl+Alt+A)",
    "panel.tooltip.settings": "Settings",
    "panel.tooltip.close": "Hide (Esc)",
    "panel.placeholder": "Type your instruction, e.g. translate into Japanese / what's wrong with this code…",
    "panel.hint.send": "Enter to send · Shift+Enter for a new line",
    "panel.button.copy": "Copy",
    "panel.button.stop": "Stop",
    "panel.button.send": "Send",
    "panel.button.sending": "Generating…",
    "panel.badge.text": "Selected text",
    "panel.badge.image": "Screenshot",
    "panel.meta.chars": "{count} chars",
    "panel.state.no_context.long": "No selection detected — capture a region or just type",
    "panel.state.no_context.short": "No selection detected",
    "panel.state.image.long": "Screenshot ready — type your instruction",
    "panel.state.image.short": "Screenshot ready",
    "panel.state.text.long": "Selection captured — type your instruction",
    "panel.state.text.short": "Selection captured",
    "panel.msg.need_context": "Select something on screen first, or just type an instruction.",
    "panel.msg.no_api_key": (
        "No API Key configured yet.\n"
        "Click the ⚙ button at the top right, fill in your API Key and you are ready to go."
    ),
    "panel.msg.generating": "_Generating…_",
    "panel.msg.request_failed": "**Request failed**",
    "panel.msg.empty_reply": (
        "The model returned no content.\n\n"
        "Things worth checking, in order:\n"
        "1. whether the **model name** is correct and your account still has quota;\n"
        "2. whether **max output tokens** is too small (reasoning models spend it on thinking first);\n"
        "3. screenshots go to **Settings → Model API → Vision model** — make sure it is "
        "filled in and is a multimodal model (gpt-4o / qwen-vl-max / glm-4v …);\n"
        "4. open **Settings → Model API** and click **Test connection** to see the raw response."
    ),
    "settings.tab.api": "Model API",
    "settings.tab.presets": "Presets",
    "settings.tab.appearance": "Appearance",
    "settings.tab.behavior": "Behavior",
    "settings.button.test": "Test connection",
    "settings.button.cancel": "Cancel",
    "settings.button.save": "Save",
    "settings.api.provider": "Protocol",
    "settings.api.provider.openai": "OpenAI-compatible (OpenAI / DeepSeek / Qwen / Kimi / local Ollama…)",
    "settings.api.provider.anthropic": "Anthropic Claude",
    "settings.api.base_url": "Base URL",
    "settings.api.api_key": "API Key",
    "settings.api.model": "Text model (text questions)",
    "settings.api.vision_model": "Vision model (screenshots)",
    "settings.api.vision_model_tip": (
        "Screenshots go to the vision model, text questions to the text model. "
        "Leave the vision model **empty** to use one model for both. "
        "**Test connection** below checks both."
    ),
    "settings.api.temperature": "Temperature",
    "settings.api.max_tokens": "Max output tokens",
    "settings.api.max_tokens_auto": "Server default",
    "settings.api.max_tokens_tip": (
        "Too small an answer that gets cut off mid-sentence (and a reasoning model "
        "spends the budget on thinking first, so the answer can come back empty). "
        "The default is 4096 — enough for a full explanation or code block. "
        "Set 0 for no cap of our own and let the server use its own maximum; "
        "setting it above what the model allows makes the API reject the request."
    ),
    "settings.api.stream": "Stream output (typewriter effect)",
    "settings.api.system_prompt": "System prompt",
    "settings.api.tip": "Tip: screenshot Q&A needs a vision-capable model (gpt-4o / qwen-vl-max / glm-4v, etc.) — put it under **Vision model**.",
    "settings.preset.hint": "These buttons appear on the panel; clicking one runs its instruction against the current selection.",
    "settings.preset.col_name": "Button label",
    "settings.preset.col_prompt": "Instruction sent to the model",
    "settings.preset.add": "Add",
    "settings.preset.remove": "Remove selected",
    "settings.preset.new_name": "New preset",
    "settings.appearance.theme": "Theme",
    "settings.appearance.language": "Language",
    "settings.appearance.language_note": "The language change applies after saving; presets are stored per language.",
    "settings.appearance.opacity": "Panel opacity",
    "settings.appearance.font_size": "Font size",
    "settings.appearance.image_preview": "Screenshot size",
    "settings.appearance.image_preview.small": "Small (240 px wide)",
    "settings.appearance.image_preview.medium": "Medium (320 px wide, default)",
    "settings.appearance.image_preview.large": "Large (400 px wide, the ceiling)",
    "settings.appearance.image_preview_tip": (
        "A screenshot is context for the question, so the preview is capped at 400 px "
        "wide — no setting can make it wider — and the height follows the aspect ratio. "
        "Changing this makes the panel settle into its new size once."
    ),
    "settings.appearance.reset_size": "Reset panel size",
    "settings.appearance.size_saved": "Remembered size: {width} × {height}",
    "settings.appearance.size_default": "Using the default size",
    "settings.appearance.size_reset": "Will reset after saving",
    "settings.appearance.note": (
        "Resize the panel with the mouse: drag its **edge** or the **bottom-right corner**. "
        "The result area grows automatically when it needs more room.\n"
        "All preset buttons wrap with the width and are never clipped; your size is "
        "remembered and restored next time."
    ),
    "settings.behavior.interval": "Double-Ctrl detection window",
    "settings.behavior.screenshot_hotkey": "Capture hotkey",
    "settings.behavior.ask_hotkey": "Read-selection hotkey",
    "settings.behavior.restore_clipboard": "Restore clipboard content after reading the selection",
    "settings.behavior.autosend": "Send automatically when a preset is clicked",
    "settings.behavior.esc": "Hide the panel with Esc",
    "settings.behavior.toggle_double_ctrl": "Double-tap Ctrl again to close the panel",
    "hotkey.unset": "Not set",
    "capture.hint": "Drag to select a region   ·   Esc / right-click to cancel   ·   Enter to confirm",
    "llm.system_prompt": (
        "You are the Knocknock assistant. The user gives you something selected on "
        "screen (text or a screenshot) plus an instruction. Answer directly, in the "
        "same language the user writes in — concise, accurate and well structured. "
        "Use Markdown code blocks for code."
    ),
    "llm.fallback_system": "You are a concise and accurate assistant.",
    "llm.label.selection": "the text I selected on screen",
    "llm.label.screenshot": "the text in my screenshot",
    "llm.wrap.text": 'Here is {label}:\n"""\n{text}\n"""',
    "llm.wrap.image": "Here is a screenshot of the screen region I captured; please answer based on the image.",
    "llm.wrap.ask": "My request: {ask}",
    "llm.wrap.ask_default": "Please explain the content above.",
    "llm.error.timeout": "The request timed out. Check your network or increase the timeout.",
    "llm.error.connection": "Could not reach the API service: {detail}",
    "llm.error.not_sse": (
        "The server did not return streaming (SSE) data, and it could not be parsed "
        "as JSON either.\n\nRaw response:\n{body}"
    ),
    "llm.error.no_text": "The server response contains no message body:\n{body}",
    "llm.error.reasoning_only": (
        "The model only produced reasoning and no answer — usually because "
        "**max_tokens is too small** and the output got truncated.\n"
        "Go to Settings → Model API, raise **Max output tokens** (8000, say), or set "
        "it to 0 to let the server decide, and retry.\n\n"
        "Reasoning (excerpt):\n{reasoning}"
    ),
    "llm.error.unknown": "Unknown error",
    "llm.error.anthropic_stream": "The server did not return streaming data. Raw response:\n{body}",
    "llm.error.http": "Request failed {status} {hint}\nModel: {model}\n{detail}",
    "llm.hint.401": "(invalid or missing API Key — check Settings)",
    "llm.hint.403": "(no permission — check the model name or account access)",
    "llm.hint.404": "(endpoint or model not found — check Base URL)",
    "llm.hint.429": "(rate limited or out of quota)",
    "llm.test.system": "You are a test assistant.",
    "llm.test.user": "Reply with exactly two words: connection ok",
    "llm.test.ok": "Success: {text}",
    "llm.test.fail": "Failed: {text}",
    "llm.test.empty": "(empty reply)",
    "llm.test.line": "{label}: {result}",
    "llm.test.text_label": "Text model",
    "llm.test.vision_label": "Vision model",
    "llm.test.vision_same": "{label}: not set separately — the same as the text model",
}

_TABLES: Dict[str, Dict[str, str]] = {ZH: _ZH, EN: _EN}


# ---------------------------------------------------------------- language state
def normalize_language(value: Optional[str]) -> str:
    """Coerce whatever the config file holds into "zh" or "en"; default to Chinese."""
    text = str(value or "").strip().lower()
    if text.startswith("en"):
        return EN
    if text.startswith("zh") or text in ("cn", "chs", "cht"):
        return ZH
    return ZH


def set_language(value: Optional[str]) -> str:
    """Set the current language and return the code that actually took effect."""
    global _current
    _current = normalize_language(value)
    return _current


def language() -> str:
    return _current


def is_english() -> bool:
    return _current == EN


def text(key: str, lang: Optional[str] = None, **kwargs) -> str:
    """Look up a key in the given language (default: current), expanding {name} placeholders."""
    table = _TABLES.get(normalize_language(lang) if lang else _current, _ZH)
    value = table.get(key) or _ZH.get(key) or key
    if kwargs:
        try:
            return value.format(**kwargs)
        except (KeyError, IndexError):
            return value
    return value


def t(key: str, **kwargs) -> str:
    """Look up a key in the current language."""
    return text(key, _current, **kwargs)


# ---------------------------------------------------------------- theme names
def theme_label(value: str) -> str:
    """Translate "light" / "dark" / "auto" into a display name in the current language."""
    key = f"theme.{value}"
    label = t(key)
    return value if label == key else label


def theme_labels() -> Dict[str, str]:
    """{"light": "Light", "dark": "Dark", "auto": "Follow system"} in the current language."""
    return {value: theme_label(value) for value in ("light", "dark", "auto")}
