import base64
import re
from io import BytesIO
from typing import Any, Dict, Optional

from PIL import Image

from .parse_utils import strip_result_prefix

def _is_image_bytes(b: bytes) -> bool:
    return (
        b.startswith(b"\x89PNG\r\n\x1a\n")
        or b.startswith(b"\xff\xd8\xff")
        or b.startswith(b"GIF87a")
        or b.startswith(b"GIF89a")
        or (b.startswith(b"RIFF") and b[8:12] == b"WEBP")
    )

def _try_b64_to_img_bytes(s: str) -> Optional[bytes]:
    try:
        b = base64.b64decode(re.sub(r"\s+", "", s), validate=False)
        if _is_image_bytes(b):
            return b
    except Exception:
        return None
    return None

def extract_image_bytes(payload: Any) -> Optional[bytes]:
    if payload is None:
        return None

    if isinstance(payload, (bytes, bytearray)):
        b = bytes(payload)
        return b if _is_image_bytes(b) else None

    if isinstance(payload, str):
        t = strip_result_prefix(payload)

        m = re.search(r"data:image/[a-zA-Z0-9.+-]+;base64,([A-Za-z0-9+/=\s]+)", t)
        if m:
            b = _try_b64_to_img_bytes(m.group(1))
            if b:
                return b

        b = _try_b64_to_img_bytes(t)
        if b:
            return b

        chunks = re.findall(r"[A-Za-z0-9+/=\s]{1000,}", t)
        for c in sorted(chunks, key=len, reverse=True)[:3]:
            b = _try_b64_to_img_bytes(c)
            if b:
                return b
        return None

    if isinstance(payload, dict):
        for k in ("data", "image", "base64", "screenshot", "result", "output", "value", "content", "text"):
            if k in payload:
                b = extract_image_bytes(payload[k])
                if b:
                    return b
        return extract_image_bytes(str(payload))

    if isinstance(payload, list):
        for it in payload:
            b = extract_image_bytes(it)
            if b:
                return b
        return None

    return None

def crop_focus_region(
    full_img_bytes: bytes,
    bbox: Dict[str, float],
    dpr: float,
    pad_css_px: Optional[float] = None,
    pad_css: float = 16.0,
    min_w_css: float = 420.0,
    min_h_css: float = 220.0,
    max_w_css: float = 1200.0,
    max_h_css: float = 800.0,
    scale: float = 2.0,
) -> Image.Image:
    if pad_css_px is not None:
        pad_css = float(pad_css_px)

    img = Image.open(BytesIO(full_img_bytes)).convert("RGB")

    x = float(bbox.get("x", 0.0))
    y = float(bbox.get("y", 0.0))
    w = float(bbox.get("w", 0.0))
    h = float(bbox.get("h", 0.0))
    dpr = float(dpr or 1.0)

    if w <= 1 or h <= 1:
        return img

    cx = x + w / 2.0
    cy = y + h / 2.0

    target_w_css = max(min_w_css, min(max_w_css, w * scale + pad_css * 2))
    target_h_css = max(min_h_css, min(max_h_css, h * scale + pad_css * 2))

    target_w_px = int(target_w_css * dpr)
    target_h_px = int(target_h_css * dpr)

    left = int((cx - target_w_css / 2.0) * dpr)
    top = int((cy - target_h_css / 2.0) * dpr)
    right = left + target_w_px
    bottom = top + target_h_px

    if left < 0:
        right += -left
        left = 0
    if top < 0:
        bottom += -top
        top = 0
    if right > img.width:
        shift = right - img.width
        left = max(0, left - shift)
        right = img.width
    if bottom > img.height:
        shift = bottom - img.height
        top = max(0, top - shift)
        bottom = img.height

    if right <= left + 5 or bottom <= top + 5:
        return img

    return img.crop((left, top, right, bottom))

def image_to_low_jpeg_base64(img: Image.Image, max_width: int = 700, quality: int = 70) -> str:
    im = img
    if im.width > max_width:
        nh = int(im.height * (max_width / im.width))
        im = im.resize((max_width, max(1, nh)))

    bio = BytesIO()
    im.save(bio, format="JPEG", quality=quality, optimize=True)
    return base64.b64encode(bio.getvalue()).decode("utf-8")
