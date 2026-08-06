"""Обработка аватарок: center-crop + круглая маска PNG."""

from __future__ import annotations

import io


def make_circular_avatar(image_bytes: bytes, size: int = 256) -> bytes:
    """Сделать круглую PNG-аватарку из произвольного изображения."""
    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:
        raise RuntimeError("Установите Pillow: pip install Pillow") from exc

    with Image.open(io.BytesIO(image_bytes)) as image:
        image = image.convert("RGBA")
        width, height = image.size
        side = min(width, height)
        left = (width - side) // 2
        top = (height - side) // 2
        image = image.crop((left, top, left + side, top + side))
        image = image.resize((size, size), Image.Resampling.LANCZOS)

        mask = Image.new("L", (size, size), 0)
        draw = ImageDraw.Draw(mask)
        draw.ellipse((0, 0, size - 1, size - 1), fill=255)

        output = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        output.paste(image, (0, 0), mask=mask)
        buffer = io.BytesIO()
        output.save(buffer, format="PNG")
        return buffer.getvalue()
