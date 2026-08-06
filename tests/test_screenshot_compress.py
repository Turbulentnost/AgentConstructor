"""Тесты сжатия screenshot перед отправкой в LLM."""

from __future__ import annotations

import base64

from PySide6.QtCore import QBuffer, QIODevice, QRect
from PySide6.QtGui import QColor, QImage, QPainter

from agent_desktop_constructor.app.runtime.screenshot_compress import (
    MAX_BASE64_CHARS_FOR_LLM,
    compress_screenshot_base64,
    prepare_screenshot_for_llm,
)


def _ui_like_png_base64(width: int = 1920, height: int = 1080) -> str:
    """UI-подобный PNG (крупные панели) — как реальный browser screenshot."""
    image = QImage(width, height, QImage.Format.Format_RGB32)
    painter = QPainter(image)
    painter.fillRect(0, 0, width, height, QColor(245, 246, 248))
    painter.fillRect(0, 0, width, 64, QColor(32, 60, 110))
    painter.fillRect(0, 64, 260, height - 64, QColor(255, 255, 255))
    painter.fillRect(280, 90, width - 320, 180, QColor(230, 236, 245))
    for i in range(8):
        painter.fillRect(
            QRect(280, 300 + i * 70, width - 320, 56),
            QColor(255, 255, 255) if i % 2 == 0 else QColor(250, 251, 252),
        )
    painter.end()
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert image.save(buffer, "PNG")
    return base64.b64encode(bytes(buffer.data())).decode("ascii")


def test_compress_screenshot_fits_llm_limit() -> None:
    """Результат сжатия укладывается в лимит LLM (JPEG или исходный PNG)."""
    raw = _ui_like_png_base64()
    assert len(raw) > 5_000
    out_b64, media_type, meta = compress_screenshot_base64(raw)
    assert meta["skipped_for_llm"] is False
    assert len(out_b64) <= MAX_BASE64_CHARS_FOR_LLM
    assert media_type in {"image/jpeg", "image/png"}
    if meta.get("compressed"):
        assert meta["compressed_chars"] == len(out_b64)
        assert meta["output_size"][0] <= 1920
        assert meta["output_size"][1] <= 1920
    else:
        assert meta.get("kept_original") is True
        assert out_b64 == raw


def test_prepare_skips_when_attach_false() -> None:
    """prepare_screenshot_for_llm уважает attach_to_llm=False."""
    prepared = prepare_screenshot_for_llm(
        {
            "base64": "AAAA",
            "attach_to_llm": False,
            "media_type": "image/png",
        }
    )
    assert prepared is None


def test_prepare_reuses_already_compressed() -> None:
    """Уже сжатый screenshot не пережимается повторно."""
    raw = _ui_like_png_base64(1280, 720)
    compressed, media_type, meta = compress_screenshot_base64(raw)
    assert meta["skipped_for_llm"] is False
    prepared = prepare_screenshot_for_llm(
        {
            "base64": compressed,
            "media_type": media_type,
            "compress_meta": meta,
            "attach_to_llm": True,
        }
    )
    assert prepared is not None
    assert prepared["base64"] == compressed
    assert prepared["media_type"] == media_type


def test_compress_skips_when_still_too_large() -> None:
    """Если даже после адаптивного сжатия лимит превышен — skipped_for_llm."""
    # Крошечный max_side и крошечный «лимит» через monkeypatch в том же модуле.
    import agent_desktop_constructor.app.runtime.screenshot_compress as mod

    original = mod.MAX_BASE64_CHARS_FOR_LLM
    mod.MAX_BASE64_CHARS_FOR_LLM = 500
    try:
        raw = _ui_like_png_base64(1600, 900)
        _out, _media, meta = compress_screenshot_base64(
            raw, max_side=400, jpeg_quality=20
        )
        # При лимите 500 символов почти любой image будет skipped.
        assert meta["skipped_for_llm"] is True
    finally:
        mod.MAX_BASE64_CHARS_FOR_LLM = original
