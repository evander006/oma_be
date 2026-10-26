"""AI provider interface and factory."""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class AIImagePart:
    mime_type: str
    data: bytes


@dataclass
class AIResult:
    text: str
    structured: dict[str, Any] | None = None


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
        # Extract product ids mentioned after CATALOG: marker if present.
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
    def __init__(self, api_key: str, model: str) -> None:
        self.api_key = api_key
        self.model = model

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

        response = client.models.generate_content(
            model=self.model,
            contents=contents,
            config=types.GenerateContentConfig(**config_kwargs),
        )
        text = (response.text or "").strip()
        structured = None
        if expect_json:
            try:
                structured = json.loads(text)
            except json.JSONDecodeError:
                logger.warning("Gemini returned non-JSON despite expect_json")
        return AIResult(text=text, structured=structured)


def get_ai_provider() -> AIProvider:
    settings = get_settings()
    if settings.ai_provider.lower() == "gemini":
        if not settings.gemini_api_key:
            logger.warning("GEMINI_API_KEY missing; falling back to mock AI provider")
            return MockAIProvider()
        return GeminiAIProvider(settings.gemini_api_key, settings.gemini_model)
    return MockAIProvider()
