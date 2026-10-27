"""Separate AI capability interfaces: vision, reasoning, image generation/editing.

The configured OpenRouter NVIDIA VL model supports multimodal *input* (room photos)
and text/JSON *output*. It does **not** provide image-editing with product reference
conditioning. Image generation is therefore a pluggable capability that returns an
honest unavailable/pending state unless a real image endpoint is configured.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.ai_provider import (
    AIImagePart,
    AIProvider,
    AIProviderError,
    AIResult,
    MockAIProvider,
    get_ai_provider,
)

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Shared result types
# ---------------------------------------------------------------------------


@dataclass
class VisionAnalysisResult:
    room_type: str | None = None
    room_type_confidence: float | None = None
    visible_furniture: list[str] = field(default_factory=list)
    dominant_colors: list[str] = field(default_factory=list)
    approximate_style: str | None = None
    lighting: list[str] = field(default_factory=list)
    furnishing_opportunities: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    uncertainties: list[str] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    summary: str = ""
    raw: dict[str, Any] = field(default_factory=dict)
    provider: str | None = None
    model_id: str | None = None


@dataclass
class RankingResult:
    ranked_product_ids: list[str] = field(default_factory=list)
    reasons: dict[str, str] = field(default_factory=dict)
    explanation: str = ""
    raw: dict[str, Any] = field(default_factory=dict)
    provider: str | None = None
    model_id: str | None = None


@dataclass
class ImageGenerationResult:
    status: str  # completed | pending | failed | unavailable
    image_bytes: bytes | None = None
    mime_type: str | None = None
    provider: str | None = None
    model_id: str | None = None
    error_message: str | None = None
    limitations: list[str] = field(default_factory=list)
    prompt_used: str | None = None


# ---------------------------------------------------------------------------
# Capability interfaces
# ---------------------------------------------------------------------------


class VisionLanguageCapability(ABC):
    """Room-photo analysis → structured observations."""

    @abstractmethod
    def analyze_room(
        self,
        *,
        images: list[AIImagePart],
        user_prompt: str,
        context: dict[str, Any],
    ) -> VisionAnalysisResult:
        raise NotImplementedError


class TextReasoningCapability(ABC):
    """Catalog-grounded ranking / explanations (text only or with context)."""

    @abstractmethod
    def rank_products(
        self,
        *,
        user_prompt: str,
        catalog: list[dict[str, Any]],
        analysis: dict[str, Any] | None = None,
        preferences: dict[str, Any] | None = None,
    ) -> RankingResult:
        raise NotImplementedError


class ImageGenerationCapability(ABC):
    """Room visualization / editing with optional product reference images."""

    @abstractmethod
    def generate_visualization(
        self,
        *,
        room_image: AIImagePart,
        product_references: list[AIImagePart],
        prompt: str,
        product_meta: list[dict[str, Any]],
    ) -> ImageGenerationResult:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Implementations reusing chat/vision provider
# ---------------------------------------------------------------------------

VISION_SYSTEM = """Ты — визуальный аналитик интерьеров OMA. Дом. Отвечай ТОЛЬКО JSON.
Не вычисляй точные размеры комнаты по фото. Если пользователь указал тип комнаты
и фото выглядит иначе — отметь uncertainty, не выбирай молча одну версию.
Схема:
{
  "room_type": "kitchen|living|bedroom|bathroom|hallway|other|null",
  "room_type_confidence": 0.0,
  "visible_furniture": ["..."],
  "dominant_colors": ["..."],
  "approximate_style": "...",
  "lighting": ["..."],
  "furnishing_opportunities": ["..."],
  "constraints": ["..."],
  "uncertainties": ["..."],
  "questions": ["..."],
  "summary": "краткое описание на русском"
}
"""

RANK_SYSTEM = """Ты — ассистент подбора товаров OMA. Дом. Используй ТОЛЬКО id из CATALOG_JSON.
Не выдумывай товары, цены, SKU, URL. Верни ТОЛЬКО JSON:
{
  "ranked_product_ids": ["id1", "id2"],
  "reasons": {"id1": "почему подходит"},
  "explanation": "краткое объяснение на русском"
}
"""


class ChatVisionCapability(VisionLanguageCapability):
    def __init__(self, provider: AIProvider, provider_label: str, model_id: str) -> None:
        self._provider = provider
        self._label = provider_label
        self._model = model_id

    def analyze_room(
        self,
        *,
        images: list[AIImagePart],
        user_prompt: str,
        context: dict[str, Any],
    ) -> VisionAnalysisResult:
        user_text = (
            f"Инструкции пользователя: {user_prompt}\n"
            f"Контекст: {json.dumps(context, ensure_ascii=False)}\n"
            "Проанализируй фото комнаты и верни JSON по схеме."
        )
        last_err: Exception | None = None
        structured: dict[str, Any] | None = None
        text = ""
        for attempt in range(2):
            try:
                result = self._provider.generate(
                    system_prompt=VISION_SYSTEM,
                    user_text=user_text
                    + ("" if attempt == 0 else "\nОтвет должен быть валидным JSON без markdown."),
                    images=images,
                    expect_json=True,
                )
                text = result.text
                structured = result.structured
                if structured:
                    break
            except AIProviderError as exc:
                last_err = exc
                if attempt == 1:
                    raise
        if not structured:
            if last_err:
                raise last_err
            structured = {
                "summary": text[:500] or "Не удалось разобрать ответ модели.",
                "uncertainties": ["Ответ модели не прошёл валидацию JSON"],
                "questions": ["Уточните тип комнаты и размеры"],
            }
        return VisionAnalysisResult(
            room_type=structured.get("room_type"),
            room_type_confidence=_as_float(structured.get("room_type_confidence")),
            visible_furniture=_as_str_list(structured.get("visible_furniture")),
            dominant_colors=_as_str_list(structured.get("dominant_colors")),
            approximate_style=structured.get("approximate_style"),
            lighting=_as_str_list(structured.get("lighting")),
            furnishing_opportunities=_as_str_list(structured.get("furnishing_opportunities")),
            constraints=_as_str_list(structured.get("constraints")),
            uncertainties=_as_str_list(structured.get("uncertainties")),
            questions=_as_str_list(structured.get("questions")),
            summary=str(structured.get("summary") or ""),
            raw=structured,
            provider=self._label,
            model_id=self._model,
        )


class ChatReasoningCapability(TextReasoningCapability):
    def __init__(self, provider: AIProvider, provider_label: str, model_id: str) -> None:
        self._provider = provider
        self._label = provider_label
        self._model = model_id

    def rank_products(
        self,
        *,
        user_prompt: str,
        catalog: list[dict[str, Any]],
        analysis: dict[str, Any] | None = None,
        preferences: dict[str, Any] | None = None,
    ) -> RankingResult:
        user_text = (
            f"Запрос: {user_prompt}\n"
            f"Анализ комнаты: {json.dumps(analysis or {}, ensure_ascii=False)}\n"
            f"Предпочтения: {json.dumps(preferences or {}, ensure_ascii=False)}\n"
            f"CATALOG_JSON:{json.dumps(catalog, ensure_ascii=False)}"
        )
        result = self._provider.generate(
            system_prompt=RANK_SYSTEM,
            user_text=user_text,
            images=None,
            expect_json=True,
        )
        structured = result.structured or {}
        ids = [str(x) for x in (structured.get("ranked_product_ids") or [])]
        reasons_raw = structured.get("reasons") or {}
        reasons = {str(k): str(v) for k, v in reasons_raw.items()}
        return RankingResult(
            ranked_product_ids=ids,
            reasons=reasons,
            explanation=str(structured.get("explanation") or structured.get("summary") or ""),
            raw=structured,
            provider=self._label,
            model_id=self._model,
        )


class UnavailableImageGenerationCapability(ImageGenerationCapability):
    """Honest stub: VL chat models cannot edit rooms with product references."""

    def __init__(self, reason: str | None = None) -> None:
        self.reason = reason or (
            "Image editing with catalog product reference images is not available "
            "for the configured vision-language model. Configure IMAGE_GEN_PROVIDER "
            "when a supported NVIDIA / NIM image-edit endpoint is available."
        )

    def generate_visualization(
        self,
        *,
        room_image: AIImagePart,
        product_references: list[AIImagePart],
        prompt: str,
        product_meta: list[dict[str, Any]],
    ) -> ImageGenerationResult:
        return ImageGenerationResult(
            status="unavailable",
            provider="none",
            model_id=None,
            error_message=self.reason,
            limitations=[
                "Текущая модель (vision-language) принимает изображения на вход, "
                "но не генерирует отредактированное фото комнаты.",
                "Не отправляйте только названия товаров — без image-edit endpoint "
                "точное воспроизведение OMA-изделий невозможно.",
            ],
            prompt_used=prompt,
        )


class MockImageGenerationCapability(ImageGenerationCapability):
    """Test-only: marks generation completed with a tiny placeholder JPEG copy of room."""

    def generate_visualization(
        self,
        *,
        room_image: AIImagePart,
        product_references: list[AIImagePart],
        prompt: str,
        product_meta: list[dict[str, Any]],
    ) -> ImageGenerationResult:
        return ImageGenerationResult(
            status="completed",
            image_bytes=room_image.data,
            mime_type=room_image.mime_type or "image/jpeg",
            provider="mock-image-gen",
            model_id="mock",
            limitations=[
                "Mock image generation returns the original room photo unchanged. "
                "Not a product-conditioned edit.",
            ],
            prompt_used=prompt,
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


@dataclass
class AICapabilities:
    vision: VisionLanguageCapability
    reasoning: TextReasoningCapability
    image_gen: ImageGenerationCapability
    provider_label: str
    model_id: str
    supports_image_input: bool = True
    supports_image_output: bool = False


def get_ai_capabilities() -> AICapabilities:
    settings = get_settings()
    provider = get_ai_provider()
    label, model = _provider_meta(settings, provider)

    vision = ChatVisionCapability(provider, label, model)
    reasoning = ChatReasoningCapability(provider, label, model)

    img_provider = (settings.image_gen_provider or "none").lower().strip()
    if img_provider == "mock":
        image_gen: ImageGenerationCapability = MockImageGenerationCapability()
        supports_out = True
    elif img_provider in {"none", "", "unavailable"}:
        image_gen = UnavailableImageGenerationCapability()
        supports_out = False
    else:
        # Future: nvidia-nim / dedicated edit endpoint. Until wired, stay honest.
        image_gen = UnavailableImageGenerationCapability(
            f"IMAGE_GEN_PROVIDER={img_provider!r} is configured but no client is "
            "implemented yet. Design selections are preserved for retry."
        )
        supports_out = False

    return AICapabilities(
        vision=vision,
        reasoning=reasoning,
        image_gen=image_gen,
        provider_label=label,
        model_id=model,
        supports_image_input=True,
        supports_image_output=supports_out,
    )


def _provider_meta(settings: Any, provider: AIProvider) -> tuple[str, str]:
    if isinstance(provider, MockAIProvider):
        return "mock", "mock"
    name = (settings.ai_provider or "").lower()
    if name == "openrouter":
        return "openrouter", settings.openrouter_model
    if name == "gemini":
        return "gemini", settings.gemini_model
    if name == "nvidia":
        return "nvidia", getattr(settings, "nvidia_model", "unknown")
    return name or "unknown", "unknown"


def _as_str_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(x) for x in value if x is not None]
    return [str(value)]


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_generation_prompt(
    *,
    instructions: str,
    style: str | None,
    products: list[dict[str, Any]],
    keep_objects: list[str] | None = None,
) -> str:
    lines = [
        "Edit the room photograph to incorporate the selected catalog products.",
        "Preserve camera perspective and overall room geometry.",
        f"User instructions: {instructions}",
    ]
    if style:
        lines.append(f"Desired style: {style}")
    if keep_objects:
        lines.append("Must remain: " + ", ".join(keep_objects))
    lines.append("Selected products (use reference images; do not invent appearance):")
    for p in products:
        dims = []
        for k in ("width_mm", "height_mm", "depth_mm"):
            if p.get(k) is not None:
                dims.append(f"{k}={p[k]}")
        dim_s = f" ({', '.join(dims)})" if dims else " (dimensions unknown)"
        lines.append(f"- id={p.get('id')} name={p.get('name')}{dim_s}")
    lines.append(
        "Disclaimer: visualization is conceptual; not proof of exact fit or installation."
    )
    return "\n".join(lines)


def load_product_reference_image(relative_or_abs: str | Path) -> AIImagePart | None:
    """Load a local product image for reference conditioning (never log bytes)."""
    from app.services.image_service import load_resized_image_bytes

    settings = get_settings()
    path = Path(relative_or_abs)
    if not path.is_file():
        # Try under images_dir
        candidate = settings.images_dir / path.name
        if candidate.is_file():
            path = candidate
        else:
            # relative like images/products/{id}/00.jpg
            rel = str(relative_or_abs).replace("\\", "/")
            if rel.startswith("images/products/"):
                parts = rel.split("/")
                if len(parts) >= 4:
                    candidate = settings.images_dir / parts[2] / parts[3]
                    if candidate.is_file():
                        path = candidate
    if not path.is_file():
        return None
    data, mime = load_resized_image_bytes(path, max_side=768)
    return AIImagePart(mime_type=mime, data=data)
