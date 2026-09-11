"""Large-model API calls (OpenAI-compatible and Anthropic protocols) with streaming."""
from __future__ import annotations

import base64
import json
from typing import Any, Dict, List, Optional

import requests
from PySide6.QtCore import QThread, Signal

from . import i18n


def default_system_prompt(language: Optional[str] = None) -> str:
    """Built-in system prompt (follows the UI language)."""
    return i18n.text("llm.system_prompt", language)


# ---------------------------------------------------------------- message building
def build_user_content(context: Dict[str, Any], instruction: str) -> Any:
    """Pack "selected content + user instruction" into a single user message.

    context: {"text": str, "image_png": bytes|None, "source": "selection"|"screenshot"}
    Returns OpenAI-style content (a plain string, or a list of content blocks).
    """
    text = (context.get("text") or "").strip()
    image_png: Optional[bytes] = context.get("image_png")
    source = context.get("source", "selection")

    blocks: List[Dict[str, Any]] = []
    parts: List[str] = []

    if text:
        label = i18n.t("llm.label.selection" if source == "selection" else "llm.label.screenshot")
        parts.append(i18n.t("llm.wrap.text", label=label, text=text))
    if image_png:
        parts.append(i18n.t("llm.wrap.image"))

    ask = (instruction or "").strip()
    parts.append(i18n.t("llm.wrap.ask", ask=ask) if ask else i18n.t("llm.wrap.ask_default"))

    blocks.append({"type": "text", "text": "\n\n".join(parts)})
    if image_png:
        encoded = base64.b64encode(image_png).decode("ascii")
        blocks.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{encoded}"},
            }
        )
    return blocks if image_png else blocks[0]["text"]


def to_anthropic_messages(messages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Convert OpenAI-style messages into Anthropic's system + messages pair."""
    system = ""
    converted: List[Dict[str, Any]] = []
    for message in messages:
        role = message.get("role")
        content = message.get("content")
        if role == "system":
            system = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
            continue
        if isinstance(content, str):
            converted.append({"role": role, "content": [{"type": "text", "text": content}]})
            continue
        blocks: List[Dict[str, Any]] = []
        for block in content or []:
            if block.get("type") == "text":
                blocks.append({"type": "text", "text": block.get("text", "")})
            elif block.get("type") == "image_url":
                url = block.get("image_url", {}).get("url", "")
                if ";base64," in url:
                    media_type, data = url.split(";base64,", 1)
                    media_type = media_type.replace("data:", "") or "image/png"
                    blocks.append(
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": data,
                            },
                        }
                    )
        converted.append({"role": role, "content": blocks})
    return {"system": system, "messages": converted}


# ---------------------------------------------------------------- worker thread
class LLMWorker(QThread):
    """Requests the model on a background thread and emits content chunk by chunk."""

    chunk = Signal(str)       # incremental text
    succeeded = Signal(str)   # complete answer
    failed = Signal(str)      # error message

    def __init__(self, api_cfg: Dict[str, Any], messages: List[Dict[str, Any]], parent=None) -> None:
        super().__init__(parent)
        self.api_cfg = dict(api_cfg or {})
        self.messages = list(messages)
        self._stop_flag = False

    def stop(self) -> None:
        self._stop_flag = True

    # -------------------------------------------------------- entry point
    def run(self) -> None:  # noqa: D102
        try:
            provider = str(self.api_cfg.get("provider", "openai")).lower()
            if provider == "anthropic":
                self._run_anthropic()
            else:
                self._run_openai()
        except requests.exceptions.Timeout:
            self.failed.emit(i18n.t("llm.error.timeout"))
        except requests.exceptions.ConnectionError as exc:
            self.failed.emit(i18n.t("llm.error.connection", detail=exc))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(f"{type(exc).__name__}: {exc}")

    # -------------------------------------------------------- OpenAI-compatible
    def _openai_payload(self) -> Dict[str, Any]:
        return {
            "model": self.api_cfg.get("model", "gpt-4o-mini"),
            "messages": self.messages,
            "temperature": float(self.api_cfg.get("temperature", 0.3)),
            "max_tokens": int(self.api_cfg.get("max_tokens", 1200)),
            "stream": bool(self.api_cfg.get("stream", True)),
        }

    def _run_openai(self) -> None:
        base_url = str(self.api_cfg.get("base_url") or "https://api.openai.com/v1").rstrip("/")
        url = f"{base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_cfg.get('api_key', '')}",
        }
        timeout = (10, int(self.api_cfg.get("timeout", 60)))
        streaming = bool(self.api_cfg.get("stream", True))

        response = requests.post(
            url, headers=headers, json=self._openai_payload(),
            stream=streaming, timeout=timeout,
        )
        if response.status_code >= 400:
            self.failed.emit(self._describe_http_error(response))
            return

        if not streaming:
            data = response.json()
            content = self._extract_openai_text(data)
            if content:
                self.chunk.emit(content)
            self.succeeded.emit(content)
            return

        collected = ""
        reasoning = ""
        plain_lines: List[str] = []   # lines not starting with "data:" (i.e. the server skipped SSE)
        saw_sse = False

        for raw in response.iter_lines(decode_unicode=False):
            if self._stop_flag:
                break
            if not raw:
                continue
            line = raw.decode("utf-8", "ignore").strip()
            if not line:
                continue
            if not line.startswith("data:"):
                plain_lines.append(line)
                continue

            saw_sse = True
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            if not payload:
                continue
            try:
                obj = json.loads(payload)
            except json.JSONDecodeError:
                continue
            delta = (obj.get("choices") or [{}])[0].get("delta") or {}
            piece = delta.get("content")
            if piece:
                collected += piece
                self.chunk.emit(piece)
            else:
                # Reasoning models emit their thinking first; if max_tokens runs
                # out, the answer itself may end up completely empty.
                thinking = delta.get("reasoning_content") or delta.get("reasoning")
                if thinking:
                    reasoning += thinking

        if collected:
            self.succeeded.emit(collected)
            return

        # The answer is empty — we have to explain the real cause instead of
        # just saying "the model returned no content".
        if not saw_sse and plain_lines:
            # The server never spoke SSE (some gateways/proxies ignore the stream
            # flag and return plain JSON instead).
            body = "".join(plain_lines)
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                self.failed.emit(i18n.t("llm.error.not_sse", body=body[:600]))
                return
            text = self._extract_openai_text(data)
            if text:
                self.chunk.emit(text)
                self.succeeded.emit(text)
                return
            self.failed.emit(i18n.t("llm.error.no_text", body=body[:600]))
            return

        if reasoning:
            self.failed.emit(i18n.t("llm.error.reasoning_only", reasoning=reasoning[:500]))
            return

        self.succeeded.emit("")

    @staticmethod
    def _extract_openai_text(data: Dict[str, Any]) -> str:
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            return ""

    # -------------------------------------------------------- Anthropic
    def _run_anthropic(self) -> None:
        base_url = str(self.api_cfg.get("base_url") or "https://api.anthropic.com").rstrip("/")
        url = f"{base_url}/v1/messages"
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_cfg.get("api_key", ""),
            "anthropic-version": "2023-06-01",
        }
        packed = to_anthropic_messages(self.messages)
        payload: Dict[str, Any] = {
            "model": self.api_cfg.get("model", "claude-3-5-sonnet-latest"),
            "max_tokens": int(self.api_cfg.get("max_tokens", 1200)),
            "temperature": float(self.api_cfg.get("temperature", 0.3)),
            "messages": packed["messages"],
            "stream": bool(self.api_cfg.get("stream", True)),
        }
        if packed["system"]:
            payload["system"] = packed["system"]

        timeout = (10, int(self.api_cfg.get("timeout", 60)))
        streaming = bool(self.api_cfg.get("stream", True))
        response = requests.post(url, headers=headers, json=payload, stream=streaming, timeout=timeout)
        if response.status_code >= 400:
            self.failed.emit(self._describe_http_error(response))
            return

        if not streaming:
            data = response.json()
            text = "".join(
                block.get("text", "")
                for block in data.get("content", [])
                if block.get("type") == "text"
            )
            if text:
                self.chunk.emit(text)
            self.succeeded.emit(text)
            return

        collected = ""
        plain_lines: List[str] = []
        saw_sse = False
        for raw in response.iter_lines(decode_unicode=False):
            if self._stop_flag:
                break
            if not raw:
                continue
            line = raw.decode("utf-8", "ignore").strip()
            if not line:
                continue
            if not line.startswith("data:"):
                plain_lines.append(line)
                continue
            saw_sse = True
            try:
                obj = json.loads(line[5:].strip())
            except json.JSONDecodeError:
                continue
            if obj.get("type") == "content_block_delta":
                delta = obj.get("delta", {}).get("text", "")
                if delta:
                    collected += delta
                    self.chunk.emit(delta)
            elif obj.get("type") == "error":
                self.failed.emit(
                    str(obj.get("error", {}).get("message", i18n.t("llm.error.unknown")))
                )
                return

        if collected or saw_sse:
            self.succeeded.emit(collected)
            return

        # Did not speak SSE: report exactly what the server sent back.
        body = "".join(plain_lines)
        if body:
            self.failed.emit(i18n.t("llm.error.anthropic_stream", body=body[:600]))
            return
        self.succeeded.emit("")

    # -------------------------------------------------------- error reporting
    @staticmethod
    def _describe_http_error(response) -> str:
        detail = ""
        try:
            body = response.json()
            detail = (
                body.get("error", {}).get("message")
                or body.get("message")
                or json.dumps(body, ensure_ascii=False)[:400]
            )
        except Exception:  # noqa: BLE001
            detail = (response.text or "")[:400]
        hints = {
            401: i18n.t("llm.hint.401"),
            403: i18n.t("llm.hint.403"),
            404: i18n.t("llm.hint.404"),
            429: i18n.t("llm.hint.429"),
        }
        return i18n.t(
            "llm.error.http",
            status=response.status_code,
            hint=hints.get(response.status_code, ""),
            detail=detail,
        ).strip()


# ---------------------------------------------------------------- connectivity test
def test_connection(api_cfg: Dict[str, Any]) -> str:
    """Run one call synchronously and return the result or an error string (used by Settings)."""
    messages = [
        {"role": "system", "content": i18n.t("llm.test.system")},
        {"role": "user", "content": i18n.t("llm.test.user")},
    ]
    cfg = dict(api_cfg)
    cfg["stream"] = False
    cfg["max_tokens"] = 32
    worker = LLMWorker(cfg, messages)
    result: Dict[str, str] = {}

    def on_ok(text: str) -> None:
        result["ok"] = text

    def on_fail(text: str) -> None:
        result["err"] = text

    worker.succeeded.connect(on_ok)
    worker.failed.connect(on_fail)
    worker.run()  # run synchronously on purpose
    if "err" in result:
        return i18n.t("llm.test.fail", text=result["err"])
    reply = result.get("ok", "").strip() or i18n.t("llm.test.empty")
    return i18n.t("llm.test.ok", text=reply)
