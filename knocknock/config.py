"""Reading, merging and saving the configuration file.

Precedence: config.json  >  config.example.json  >  built-in DEFAULT_CONFIG

Preset instructions are stored once per language: `presets` for the Chinese UI
and `presets_en` for the English UI. The panel reads the matching set when the
language changes, so the two never overwrite each other.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import i18n


def _app_dir() -> Path:
    """Return the directory that holds the user's config.

    Running from source this is the project root (the parent of the package).
    Running as a PyInstaller bundle it must be the directory of the executable
    itself, not the ``_MEIPASS`` extraction folder: that temporary directory is
    deleted when the process exits, so a config written there would be lost and
    the app would forget the API key on every launch.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _resource_dir() -> Path:
    """Return the directory that holds bundled read-only resources.

    For a frozen executable this is PyInstaller's ``_MEIPASS`` extraction folder
    (where the spec file places config.example.json); otherwise it is the
    project root, so running from source keeps working unchanged.
    """
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        return Path(bundled)
    return Path(__file__).resolve().parent.parent


APP_DIR = _app_dir()
CONFIG_PATH = APP_DIR / "config.json"
EXAMPLE_PATH = _resource_dir() / "config.example.json"

# ---------------------------------------------------------------- model defaults
# Answers used to be cut off mid-sentence: 1200 tokens is not enough for anything
# that explains a screenshot or a code block (and a reasoning model spends its
# budget on thinking first). 4096 is the largest cap every mainstream provider
# accepts, so it is a safe default; setting it to 0 means "let the server decide".
DEFAULT_MAX_TOKENS = 4096
MAX_TOKENS_LIMIT = 131072
_LEGACY_MAX_TOKENS = 1200   # the previous built-in default, too small to be useful

# How much room a captured picture may take on screen ("image_preview"). The
# pixel sizes behind these names live in panel.py, next to the layout they have
# to fit into; config only validates the name.
IMAGE_PREVIEWS = ("small", "medium", "large")
DEFAULT_IMAGE_PREVIEW = "medium"

# ---------------------------------------------------------------- presets
PRESETS_ZH: List[Dict[str, str]] = [
    {"name": "翻译成中文", "prompt": "把选中的内容翻译成简体中文，只输出译文，不要任何解释。"},
    {"name": "翻译成英文", "prompt": "Translate the selected content into natural English. Output the translation only."},
    {"name": "解释一下", "prompt": "用通俗易懂的语言解释这段内容，指出其中最关键的概念或结论。"},
    {"name": "总结要点", "prompt": "用要点列表总结这段内容的核心信息，控制在 5 条以内。"},
    {"name": "润色改写", "prompt": "润色这段文字，让它更通顺、更专业，但必须保持原意不变，只输出改写后的结果。"},
    {"name": "代码解释", "prompt": "解释这段代码的功能、关键实现逻辑，并指出潜在的问题或可优化点。"},
]

PRESETS_EN: List[Dict[str, str]] = [
    {"name": "Translate to Chinese", "prompt": "把选中的内容翻译成简体中文，只输出译文，不要任何解释。"},
    {"name": "Translate to English", "prompt": "Translate the selected content into natural English. Output the translation only."},
    {"name": "Explain", "prompt": "Explain this content in plain language and point out the key concepts or conclusions."},
    {"name": "Summarise", "prompt": "Summarise the core message as a bullet list of at most 5 points."},
    {"name": "Polish", "prompt": "Polish this text so it reads more smoothly and professionally, but keep the meaning unchanged. Output only the rewritten text."},
    {"name": "Explain code", "prompt": "Explain what this code does and how it works, and point out potential problems or improvements."},
]

# Built-in default system prompts. If the config still holds one of these, the
# user never customised it, so it is safe to re-translate when the UI language
# changes. The last two are the defaults left over from 1.0 (when the project was
# still called "Knock") and are listed here so they can be migrated too.
_KNOWN_SYSTEM_PROMPTS = {
    i18n.text("llm.system_prompt", i18n.ZH),
    i18n.text("llm.system_prompt", i18n.EN),
    "你是一个简洁、准确的助手。",
    (
        "你是 Knock 助手。用户会给你一段来自屏幕的选中内容（文字或截图），"
        "并按你的指令提问。请直接给出答案，语言与用户提问保持一致，"
        "简洁、准确、条理清晰。涉及代码时使用 Markdown 代码块。"
    ),
}

DEFAULT_CONFIG: Dict[str, Any] = {
    "api": {
        "provider": "openai",
        "base_url": "https://api.openai.com/v1",
        "api_key": "",
        # Text questions use `model`, anything carrying a screenshot uses
        # `vision_model`; an empty vision model means "same as the text one".
        "model": "gpt-4o-mini",
        "vision_model": "",
        "temperature": 0.3,
        "max_tokens": DEFAULT_MAX_TOKENS,
        "timeout": 60,
        "stream": True,
        "system_prompt": i18n.text("llm.system_prompt", i18n.ZH),
    },
    "ui": {
        "width": 520,          # initial panel width (includes the shadow margin)
        "min_width": 420,      # minimum panel width
        "theme": "light",      # light / dark / auto (follow the system)
        "language": "zh",      # zh / en
        "always_on_top": True,
        "opacity": 0.99,
        "font_size": 13,
        "image_preview": DEFAULT_IMAGE_PREVIEW,  # small / medium / large
        "last_size": None,     # size the user dragged out, reused on next launch
    },
    "hotkeys": {
        "double_ctrl_interval_ms": 420,
        "screenshot": "ctrl+alt+a",
        "ask_selection": "ctrl+alt+q",
    },
    "behavior": {
        "auto_copy_selection": True,
        "restore_clipboard": False,
        "auto_send_on_preset": True,
        "close_on_esc": True,
        "toggle_on_double_ctrl": True,   # double Ctrl closes the panel while it is open
        "max_history_turns": 6,
    },
    "presets": PRESETS_ZH,
    "presets_en": PRESETS_EN,
}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge `override` into a copy of `base`.

    Keys missing from `override` keep the value from `base`.
    """
    result = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as fp:
            data = json.load(fp)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _normalize(cfg: Dict[str, Any]) -> None:
    """Fill in / correct the config in place so downstream code can rely on the shape."""
    ui = cfg.setdefault("ui", {})
    language = i18n.normalize_language(ui.get("language"))
    ui["language"] = language
    if str(ui.get("image_preview", "")).lower() not in IMAGE_PREVIEWS:
        ui["image_preview"] = DEFAULT_IMAGE_PREVIEW

    # Older configs have no presets_en; fill it with the defaults. An empty list
    # is kept as-is, because clearing it was the user's own choice.
    for key, defaults in (("presets", PRESETS_ZH), ("presets_en", PRESETS_EN)):
        if not isinstance(cfg.get(key), list):
            cfg[key] = copy.deepcopy(defaults)

    # System prompt: follow the UI language when it is blank or still one of the
    # built-in defaults (i.e. the user never edited it).
    api = cfg.setdefault("api", {})
    api["vision_model"] = str(api.get("vision_model") or "").strip()
    prompt = str(api.get("system_prompt") or "").strip()
    if not prompt or prompt in _KNOWN_SYSTEM_PROMPTS:
        api["system_prompt"] = i18n.text("llm.system_prompt", language)

    # Output tokens: 1200 used to be the built-in default, and answers were being
    # cut off mid-sentence because of it. Configs still sitting on that value
    # never chose it, so they are lifted to the new default.
    try:
        tokens = int(api.get("max_tokens", DEFAULT_MAX_TOKENS))
    except (TypeError, ValueError):
        tokens = DEFAULT_MAX_TOKENS
    if tokens == _LEGACY_MAX_TOKENS:
        tokens = DEFAULT_MAX_TOKENS
    api["max_tokens"] = max(0, min(tokens, MAX_TOKENS_LIMIT))


def load_config() -> Dict[str, Any]:
    """Load the config, filling in anything missing."""
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    if EXAMPLE_PATH.exists():
        cfg = _deep_merge(cfg, _read_json(EXAMPLE_PATH))
    if CONFIG_PATH.exists():
        cfg = _deep_merge(cfg, _read_json(CONFIG_PATH))
    _normalize(cfg)
    return cfg


def save_config(cfg: Dict[str, Any]) -> None:
    """Save the user configuration (never the example template)."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CONFIG_PATH.open("w", encoding="utf-8") as fp:
        json.dump(cfg, fp, ensure_ascii=False, indent=2)


def ensure_config_exists() -> bool:
    """Create config.json on first run; returns whether the file was newly created."""
    if CONFIG_PATH.exists():
        return False
    save_config(load_config())
    return True


def presets_key(language: Optional[str] = None) -> str:
    """The preset key that belongs to a given language."""
    return "presets_en" if i18n.normalize_language(language) == i18n.EN else "presets"


def presets_for(cfg: Dict[str, Any], language: Optional[str] = None) -> List[Dict[str, str]]:
    """Return the preset list for a language (default: the current UI language).

    The i18n module is the single source of truth for "what language the UI is
    speaking right now"; cfg["ui"]["language"] is only the persisted copy, and
    set_language() keeps the two in sync.
    """
    lang = i18n.normalize_language(language) if language else i18n.language()
    value = cfg.get(presets_key(lang))
    if not isinstance(value, list):
        value = cfg.get("presets") or []
    return [item for item in value if isinstance(item, dict)]


def get(cfg: Dict[str, Any], path: str, default: Any = None) -> Any:
    """Read a value by dotted path, e.g. "api.model"."""
    node: Any = cfg
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node
