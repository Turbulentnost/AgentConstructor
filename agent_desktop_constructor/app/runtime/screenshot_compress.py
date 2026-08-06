"""Сжатие screenshot перед отправкой в LLM (чтобы не зависать на огромном image)."""

from __future__ import annotations

import base64
import io
from typing import Any


# Для UI/кликов важна читаемость: 1920 по длинной стороне (было 1280 — слишком мелко).
DEFAULT_MAX_SIDE = 1920
DEFAULT_JPEG_QUALITY = 78
# Если после сжатия всё ещё слишком большой base64 — не прикладываем image.
MAX_BASE64_CHARS_FOR_LLM = 240_000


def compress_screenshot_base64(
    base64_data: str,
    *,
    max_side: int = DEFAULT_MAX_SIDE,
    jpeg_quality: int = DEFAULT_JPEG_QUALITY,
) -> tuple[str, str, dict[str, Any]]:
    """Сжать PNG/JPEG screenshot для vision-запроса к LLM.

    Returns:
        (base64, media_type, meta). При ошибке возвращает исходные данные.
    """
    raw = (base64_data or "").strip()
    meta: dict[str, Any] = {
        "original_chars": len(raw),
        "compressed": False,
        "skipped_for_llm": False,
    }
    if not raw:
        return "", "image/png", meta

    try:
        binary = base64.b64decode(raw, validate=False)
    except Exception:
        return raw, "image/png", meta

    # Адаптивно: уменьшаем side/quality, пока не уложимся в лимит.
    attempts = (
        (max_side, jpeg_quality),
        (max_side, max(40, jpeg_quality - 20)),
        (min(max_side, 1024), 55),
        (min(max_side, 900), 45),
        (min(max_side, 720), 35),
    )
    best: tuple[str, str, dict[str, Any]] | None = None
    for side, quality in attempts:
        compressed = _compress_with_qt(
            binary, max_side=side, jpeg_quality=quality
        )
        if compressed is None:
            compressed = _compress_with_pillow(
                binary, max_side=side, jpeg_quality=quality
            )
        if compressed is None:
            continue
        out_b64, media_type, extra = compressed
        candidate = (out_b64, media_type, extra)
        if best is None or len(out_b64) < len(best[0]):
            best = candidate
        if len(out_b64) <= MAX_BASE64_CHARS_FOR_LLM:
            break

    if best is None:
        if len(raw) > MAX_BASE64_CHARS_FOR_LLM:
            meta["skipped_for_llm"] = True
        return raw, "image/png", meta

    out_b64, media_type, extra = best
    # Берём меньший из исходника и JPEG, если он укладывается в лимит.
    if len(raw) < len(out_b64) and len(raw) <= MAX_BASE64_CHARS_FOR_LLM:
        meta["compressed"] = False
        meta["kept_original"] = True
        return raw, "image/png", meta

    meta.update(extra)
    meta["compressed"] = True
    meta["compressed_chars"] = len(out_b64)
    if len(out_b64) > MAX_BASE64_CHARS_FOR_LLM:
        meta["skipped_for_llm"] = True
    return out_b64, media_type, meta


def prepare_screenshot_for_llm(screenshot: dict | None) -> dict | None:
    """Вернуть копию last_screenshot, готовую для image content LLM."""
    if not isinstance(screenshot, dict):
        return None
    if screenshot.get("attach_to_llm") is False:
        return None
    raw = str(screenshot.get("base64") or "").strip()
    if not raw:
        return None
    existing_meta = screenshot.get("compress_meta")
    if isinstance(existing_meta, dict) and existing_meta.get("skipped_for_llm"):
        return None
    # Уже сжат при stash — не гоняем повторно (JPEG→JPEG ухудшает качество).
    if (
        isinstance(existing_meta, dict)
        and existing_meta.get("compressed")
        and len(raw) <= MAX_BASE64_CHARS_FOR_LLM
    ):
        prepared = dict(screenshot)
        prepared.setdefault(
            "media_type", screenshot.get("media_type") or "image/jpeg"
        )
        return prepared
    compressed_b64, media_type, meta = compress_screenshot_base64(raw)
    if meta.get("skipped_for_llm"):
        return None
    prepared = dict(screenshot)
    prepared["base64"] = compressed_b64
    prepared["media_type"] = media_type
    prepared["compress_meta"] = meta
    return prepared


def _compress_with_qt(
    binary: bytes,
    *,
    max_side: int,
    jpeg_quality: int,
) -> tuple[str, str, dict[str, Any]] | None:
    """Сжать через PySide6.QImage (уже есть в зависимостях проекта)."""
    try:
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice
        from PySide6.QtGui import QImage
    except Exception:
        return None

    image = QImage.fromData(binary)
    if image.isNull():
        return None
    original_w, original_h = image.width(), image.height()
    scale = min(1.0, float(max_side) / float(max(original_w, original_h, 1)))
    if scale < 1.0:
        image = image.scaled(
            max(1, int(original_w * scale)),
            max(1, int(original_h * scale)),
        )
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    ok = image.save(buffer, "JPG", jpeg_quality)
    if not ok:
        return None
    data = bytes(buffer.data())
    if not data:
        return None
    return (
        base64.b64encode(data).decode("ascii"),
        "image/jpeg",
        {
            "engine": "qt",
            "original_size": [original_w, original_h],
            "output_size": [image.width(), image.height()],
            "jpeg_quality": jpeg_quality,
        },
    )


def _compress_with_pillow(
    binary: bytes,
    *,
    max_side: int,
    jpeg_quality: int,
) -> tuple[str, str, dict[str, Any]] | None:
    """Опциональный fallback через Pillow, если установлен."""
    try:
        from PIL import Image
    except Exception:
        return None
    try:
        with Image.open(io.BytesIO(binary)) as image:
            rgb = image.convert("RGB")
            original_w, original_h = rgb.size
            scale = min(1.0, float(max_side) / float(max(original_w, original_h, 1)))
            if scale < 1.0:
                rgb = rgb.resize(
                    (max(1, int(original_w * scale)), max(1, int(original_h * scale)))
                )
            out_w, out_h = rgb.size
            out = io.BytesIO()
            rgb.save(out, format="JPEG", quality=jpeg_quality, optimize=True)
            data = out.getvalue()
    except Exception:
        return None
    if not data:
        return None
    return (
        base64.b64encode(data).decode("ascii"),
        "image/jpeg",
        {
            "engine": "pillow",
            "original_size": [original_w, original_h],
            "output_size": [out_w, out_h],
            "jpeg_quality": jpeg_quality,
        },
    )
