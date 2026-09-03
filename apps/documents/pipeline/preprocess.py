"""Preprocesarea imaginii inainte de OCR.

Ordinea pasilor: orientare EXIF → redimensionare → detectia si indreptarea
documentului → tonuri de gri → contrast (CLAHE) → reducerea zgomotului.
Fiecare pas returneaza imaginea si spune daca a schimbat-o, ca sa putem raporta
onest ce s-a intamplat.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

import cv2
import numpy as np
from PIL import Image, ImageOps

#: Sub acest raport, patrulaterul gasit nu este considerat un document.
MIN_QUAD_AREA_RATIO = 0.25
MAX_QUAD_AREA_RATIO = 0.99


@dataclass
class PreprocessResult:
    image: np.ndarray
    deskewed: bool
    resized: bool
    quad: list[list[int]] | None
    width: int
    height: int

    def to_jpeg(self, quality: int = 88) -> bytes:
        ok, buffer = cv2.imencode(".jpg", self.image, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
        if not ok:
            raise ValueError("Imaginea procesată nu a putut fi codificată.")
        return buffer.tobytes()


def load_with_exif(data: bytes) -> np.ndarray:
    """Aplica orientarea EXIF; altfel fotografiile de pe telefon ies rotite."""
    with Image.open(io.BytesIO(data)) as image:
        image = ImageOps.exif_transpose(image)
        image = image.convert("RGB")
        return cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)


def resize_max_side(image: np.ndarray, max_side: int) -> tuple[np.ndarray, bool]:
    height, width = image.shape[:2]
    longest = max(height, width)
    if longest <= max_side:
        return image, False
    scale = max_side / longest
    resized = cv2.resize(
        image, (int(width * scale), int(height * scale)), interpolation=cv2.INTER_AREA
    )
    return resized, True


def find_document_quad(image: np.ndarray) -> np.ndarray | None:
    """Cauta conturul patrulater al documentului in cadru."""
    height, width = image.shape[:2]
    frame_area = float(height * width)

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 60, 180)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)

    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:5]:
        area = cv2.contourArea(contour)
        ratio = area / frame_area
        if ratio < MIN_QUAD_AREA_RATIO or ratio > MAX_QUAD_AREA_RATIO:
            continue
        perimeter = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, 0.02 * perimeter, True)
        if len(approx) == 4 and cv2.isContourConvex(approx):
            return approx.reshape(4, 2).astype("float32")
    return None


def order_corners(quad: np.ndarray) -> np.ndarray:
    """Ordonează colturile: stanga-sus, dreapta-sus, dreapta-jos, stanga-jos."""
    ordered = np.zeros((4, 2), dtype="float32")
    total = quad.sum(axis=1)
    ordered[0] = quad[np.argmin(total)]
    ordered[2] = quad[np.argmax(total)]
    diff = np.diff(quad, axis=1)
    ordered[1] = quad[np.argmin(diff)]
    ordered[3] = quad[np.argmax(diff)]
    return ordered


def warp_perspective(image: np.ndarray, quad: np.ndarray) -> np.ndarray:
    corners = order_corners(quad)
    (top_left, top_right, bottom_right, bottom_left) = corners

    width = int(
        max(np.linalg.norm(bottom_right - bottom_left), np.linalg.norm(top_right - top_left))
    )
    height = int(
        max(np.linalg.norm(top_right - bottom_right), np.linalg.norm(top_left - bottom_left))
    )
    width, height = max(width, 1), max(height, 1)

    destination = np.array(
        [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], dtype="float32"
    )
    matrix = cv2.getPerspectiveTransform(corners, destination)
    return cv2.warpPerspective(image, matrix, (width, height))


def enhance(image: np.ndarray) -> np.ndarray:
    """Tonuri de gri, contrast local si reducerea zgomotului."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    contrasted = clahe.apply(gray)
    denoised = cv2.bilateralFilter(contrasted, d=7, sigmaColor=50, sigmaSpace=50)
    return cv2.cvtColor(denoised, cv2.COLOR_GRAY2BGR)


def run(data: bytes, *, max_side: int = 2000, deskew: bool = True) -> PreprocessResult:
    image = load_with_exif(data)
    image, resized = resize_max_side(image, max_side)

    quad = find_document_quad(image) if deskew else None
    deskewed = False
    if quad is not None:
        image = warp_perspective(image, quad)
        deskewed = True

    image = enhance(image)
    height, width = image.shape[:2]
    return PreprocessResult(
        image=image,
        deskewed=deskewed,
        resized=resized,
        quad=quad.astype(int).tolist() if quad is not None else None,
        width=width,
        height=height,
    )


def detect_only(data: bytes) -> dict:
    """Folosit de ecranul de cameră pentru indicatorul „Document detectat"."""
    image = load_with_exif(data)
    image, _ = resize_max_side(image, 640)
    quad = find_document_quad(image)
    height, width = image.shape[:2]
    return {
        "detected": quad is not None,
        "quad": quad.astype(int).tolist() if quad is not None else None,
        "width": width,
        "height": height,
    }
