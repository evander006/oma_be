"""AI provider interface and factory."""
from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Tried in order when primary model returns 503 / high demand.
DEFAULT_FALLBACK_MODELS = (
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-3.8-flash",
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
            "Цены и характеристики берутся только из базы; фото при необходимости "
            "отправляются внешнему провайдеру только при AI_PROVIDER=gemini."
        )
        if expect_json:
            return AIResult(text=json.dumps(analysis, ensure_ascii=False), structured=analysis)
        return AIResult(text=text, structured=analysis)


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
        self.fallback_models = fallback_models or list(DEFAULT_FALLBACK_MODELS)
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
            from google.genai import types
            from google.genai import errors as genai_errors
        except ImportError as exc:
            raise RuntimeError("google-genai package is required for Gemini provider") from exc

        client = genai.Client(api_key=self.api_key)
        parts: list[Any] = [types.Part.from_text(text=user_text)]
        for img in images or []:
            parts.append(types.Part.from_bytes(data=img.data, mime_type=img.mime_type))
        contents = [types.Content(role="user", parts=parts)]

        config_kwargs: dict[str, Any] = {
            "system_instruction": system_prompt,
        }
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
                    structured = None
                    if expect_json:
                        try:
                            structured = json.loads(text)
                        except json.JSONDecodeError:
                            logger.warning("Gemini returned non-JSON despite expect_json")
                    if model_name != self.model:
                        logger.info("Gemini used fallback model %s", model_name)
                    return AIResult(text=text, structured=structured)
                except genai_errors.ServerError as exc:
                    last_error = exc
                    code = getattr(exc, "code", None) or 503
                    logger.warning(
                        "Gemini %s attempt %s/%s failed (%s): %s",
                        model_name,
                        attempt,
                        self.max_retries,
                        code,
                        exc,
                    )
                    if attempt < self.max_retries:
                        time.sleep(1.5 * attempt)
                        continue
                    # try next model
                    break
                except genai_errors.ClientError as exc:
                    # 429 rate limit — retry; other 4xx — fail fast / try next model
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
            "Сервис Gemini временно перегружен. Повторите запрос через минуту "
            "или смените GEMINI_MODEL (например gemini-2.5-flash) в настройках Render.",
            status_code=503,
        ) from last_error


def get_ai_provider() -> AIProvider:
    settings = get_settings()
    if settings.ai_provider.lower() == "gemini":
        if not settings.gemini_api_key:
            logger.warning("GEMINI_API_KEY missing; falling back to mock AI provider")
            return MockAIProvider()
        fallbacks = [
            m.strip()
            for m in (settings.gemini_fallback_models or "").split(",")
            if m.strip()
        ] or list(DEFAULT_FALLBACK_MODELS)
        return GeminiAIProvider(
            settings.gemini_api_key,
            settings.gemini_model,
            fallback_models=fallbacks,
        )
    return MockAIProvider()
