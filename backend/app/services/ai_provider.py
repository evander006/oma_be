"""AI provider interface and factory (mock / Gemini / OpenRouter)."""
from __future__ import annotations

import base64
import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

DEFAULT_GEMINI_FALLBACKS = (
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-3.8-flash",
)

# Non-Google free vision models on OpenRouter (may rotate; override via env).
DEFAULT_OPENROUTER_FALLBACKS = (
    "nvidia/nemotron-3.5-super-vl:free",
    "qwen/qwen2.5-vl-3b-instruct:free",
    "nvidia/nemotron-nano-12b-v2-vl:free",
)


@dataclass
class AIImagePart:
    mime_type: str
    data: bytes


@dataclass
class AIResult:
    text: str
    structured: dict[str, Any] | None = None


class AIProviderError(RuntimeError):
    """Raised when the external AI provider fails after retries."""

    def __init__(self, message: str, *, status_code: int = 503) -> None:
        super().__init__(message)
        self.status_code = status_code


class AIProvider(ABC):
    @abstractmethod
    def generate(
        self,
        *,
        system_prompt: str,
        user_text: str,
        images: list[AIImagePart] | None = None,
        expect_json: bool = False,
    ) -> AIResult:
        raise NotImplementedError


class MockAIProvider(AIProvider):
    """Offline provider for local development and unit tests."""

    def generate(
        self,
        *,
        system_prompt: str,
        user_text: str,
        images: list[AIImagePart] | None = None,
        expect_json: bool = False,
    ) -> AIResult:
        has_images = bool(images)
        analysis = {
            "summary": "Макетный анализ комнаты (mock AI). Визуальные детали не извлекались из реального фото-провайдера.",
            "observations": [
                "Пользователь загрузил фото" if has_images else "Фото не приложено",
                f"Запрос: {user_text[:180]}",
            ],
            "assumptions": [
                "Стиль и бюджет интерпретированы из текста запроса",
            ],
            "uncertainties": [
                "Точные размеры комнаты по фото определить нельзя",
            ],
            "missing_info": [
                "Уточните ширину/длину комнаты в метрах, если важна совместимость габаритов",
            ],
            "ranked_product_ids": [],
            "reasons": {},
        }
        if "CATALOG_JSON:" in user_text:
            try:
                blob = user_text.split("CATALOG_JSON:", 1)[1].strip()
                catalog = json.loads(blob.split("\n", 1)[0] if blob.startswith("[") else blob)
                ids = [p["id"] for p in catalog[:5] if isinstance(p, dict) and "id" in p]
                analysis["ranked_product_ids"] = ids
                analysis["reasons"] = {
                    pid: "Подходит по категории и бюджету (mock ranking)." for pid in ids
                }
            except Exception:  # noqa: BLE001
                pass
        text = (
            "Я подобрал варианты из локального каталога OMA (режим mock AI). "
            "Цены и характеристики берутся только из базы."
        )
        if expect_json:
            return AIResult(text=json.dumps(analysis, ensure_ascii=False), structured=analysis)
        return AIResult(text=text, structured=analysis)


def _parse_json_maybe(text: str) -> dict[str, Any] | None:
    text = text.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Some models wrap JSON in ```json ... ```
        if "```" in text:
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                try:
                    return json.loads(text[start : end + 1])
                except json.JSONDecodeError:
                    return None
        return None


class OpenAICompatibleVisionProvider(AIProvider):
    """OpenAI-style chat completions with image_url parts (OpenRouter, etc.)."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str,
        fallback_models: list[str] | None = None,
        max_retries: int = 3,
        extra_headers: dict[str, str] | None = None,
        provider_label: str = "OpenAI-compatible",
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.fallback_models = fallback_models or []
        self.max_retries = max_retries
        self.extra_headers = extra_headers or {}
        self.provider_label = provider_label

    def _model_chain(self) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for name in [self.model, *self.fallback_models]:
            if name and name not in seen:
                seen.add(name)
                out.append(name)
        return out

    def _build_user_content(
        self, user_text: str, images: list[AIImagePart] | None
    ) -> list[dict[str, Any]] | str:
        if not images:
            return user_text
        content: list[dict[str, Any]] = [{"type": "text", "text": user_text}]
        for img in images:
            b64 = base64.b64encode(img.data).decode("ascii")
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{img.mime_type};base64,{b64}"},
                }
            )
        return content

    def generate(
        self,
        *,
        system_prompt: str,
        user_text: str,
        images: list[AIImagePart] | None = None,
        expect_json: bool = False,
    ) -> AIResult:
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": self._build_user_content(user_text, images),
            },
        ]
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            **self.extra_headers,
        }
        last_error: Exception | None = None
        with httpx.Client(timeout=90.0) as client:
            for model_name in self._model_chain():
                for attempt in range(1, self.max_retries + 1):
                    body: dict[str, Any] = {
                        "model": model_name,
                        "messages": messages,
                    }
                    # OpenRouter / many hosts honor this; ignore if unsupported.
                    if expect_json:
                        body["response_format"] = {"type": "json_object"}
                    try:
                        resp = client.post(
                            f"{self.base_url}/chat/completions",
                            headers=headers,
                            json=body,
                        )
                        if resp.status_code in {429, 502, 503, 504}:
                            last_error = AIProviderError(
                                f"{self.provider_label} {resp.status_code}: {resp.text[:300]}",
                                status_code=503,
                            )
                            logger.warning(
                                "%s %s attempt %s/%s -> %s",
                                self.provider_label,
                                model_name,
                                attempt,
                                self.max_retries,
                                resp.status_code,
                            )
                            time.sleep(1.5 * attempt)
                            continue
                        if resp.status_code >= 400:
                            last_error = AIProviderError(
                                f"{self.provider_label} error {resp.status_code}: {resp.text[:400]}",
                                status_code=502,
                            )
                            logger.warning("%s model %s failed: %s", self.provider_label, model_name, resp.text[:300])
                            break
                        data = resp.json()
                        text = (
                            data.get("choices", [{}])[0]
                            .get("message", {})
                            .get("content", "")
                            or ""
                        ).strip()
                        structured = _parse_json_maybe(text) if expect_json else None
                        if model_name != self.model:
                            logger.info("%s used fallback model %s", self.provider_label, model_name)
                        return AIResult(text=text, structured=structured)
                    except httpx.HTTPError as exc:
                        last_error = exc
                        logger.warning("%s network error: %s", self.provider_label, exc)
                        time.sleep(1.5 * attempt)

        raise AIProviderError(
            f"{self.provider_label} временно недоступен. Проверьте API-ключ и модель, "
            "либо повторите запрос позже.",
            status_code=503,
        ) from last_error


class GeminiAIProvider(AIProvider):
    def __init__(
        self,
        api_key: str,
        model: str,
        fallback_models: list[str] | None = None,
        max_retries: int = 3,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.fallback_models = fallback_models or list(DEFAULT_GEMINI_FALLBACKS)
        self.max_retries = max_retries

    def _model_chain(self) -> list[str]:
        seen: set[str] = set()
        chain: list[str] = []
        for name in [self.model, *self.fallback_models]:
            if name and name not in seen:
                seen.add(name)
                chain.append(name)
        return chain

    def generate(
        self,
        *,
        system_prompt: str,
        user_text: str,
        images: list[AIImagePart] | None = None,
        expect_json: bool = False,
    ) -> AIResult:
        try:
            from google import genai
            from google.genai import errors as genai_errors
            from google.genai import types
        except ImportError as exc:
            raise RuntimeError("google-genai package is required for Gemini provider") from exc

        client = genai.Client(api_key=self.api_key)
        parts: list[Any] = [types.Part.from_text(text=user_text)]
        for img in images or []:
            parts.append(types.Part.from_bytes(data=img.data, mime_type=img.mime_type))
        contents = [types.Content(role="user", parts=parts)]
        config_kwargs: dict[str, Any] = {"system_instruction": system_prompt}
        if expect_json:
            config_kwargs["response_mime_type"] = "application/json"
        config = types.GenerateContentConfig(**config_kwargs)

        last_error: Exception | None = None
        for model_name in self._model_chain():
            for attempt in range(1, self.max_retries + 1):
                try:
                    response = client.models.generate_content(
                        model=model_name,
                        contents=contents,
                        config=config,
                    )
                    text = (response.text or "").strip()
                    structured = _parse_json_maybe(text) if expect_json else None
                    if model_name != self.model:
                        logger.info("Gemini used fallback model %s", model_name)
                    return AIResult(text=text, structured=structured)
                except genai_errors.ServerError as exc:
                    last_error = exc
                    logger.warning(
                        "Gemini %s attempt %s/%s failed: %s",
                        model_name,
                        attempt,
                        self.max_retries,
                        exc,
                    )
                    if attempt < self.max_retries:
                        time.sleep(1.5 * attempt)
                        continue
                    break
                except genai_errors.ClientError as exc:
                    last_error = exc
                    code = getattr(exc, "code", None) or 400
                    logger.warning("Gemini client error on %s: %s", model_name, exc)
                    if code == 429 and attempt < self.max_retries:
                        time.sleep(2.0 * attempt)
                        continue
                    break
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    logger.exception("Unexpected Gemini error on %s", model_name)
                    break

        raise AIProviderError(
            "Сервис Gemini временно перегружен. Рекомендуется AI_PROVIDER=openrouter.",
            status_code=503,
        ) from last_error


def _split_models(raw: str | None, defaults: tuple[str, ...] | list[str]) -> list[str]:
    if not raw:
        return list(defaults)
    return [m.strip() for m in raw.split(",") if m.strip()]


def get_ai_provider() -> AIProvider:
    settings = get_settings()
    provider = (settings.ai_provider or "openrouter").lower().strip()

    if provider == "mock":
        return MockAIProvider()

    if provider == "openrouter":
        if not settings.openrouter_api_key:
            raise AIProviderError(
                "OPENROUTER_API_KEY не задан. Укажите ключ в Render Environment "
                "(AI_PROVIDER=openrouter). Mock отключён.",
                status_code=503,
            )
        return OpenAICompatibleVisionProvider(
            api_key=settings.openrouter_api_key,
            model=settings.openrouter_model,
            base_url=settings.openrouter_base_url,
            fallback_models=_split_models(
                settings.openrouter_fallback_models, DEFAULT_OPENROUTER_FALLBACKS
            ),
            extra_headers={
                "HTTP-Referer": settings.openrouter_site_url or "https://oma-dom.local",
                "X-Title": settings.openrouter_app_name or "OMA Dom",
            },
            provider_label="OpenRouter",
        )

    if provider == "gemini":
        if not settings.gemini_api_key:
            raise AIProviderError(
                "GEMINI_API_KEY не задан. Укажите ключ или переключитесь на openrouter.",
                status_code=503,
            )
        return GeminiAIProvider(
            settings.gemini_api_key,
            settings.gemini_model,
            fallback_models=_split_models(
                settings.gemini_fallback_models, DEFAULT_GEMINI_FALLBACKS
            ),
        )

    raise AIProviderError(
        f"Неизвестный AI_PROVIDER={provider!r}. Используйте openrouter|gemini|mock.",
        status_code=500,
    )
