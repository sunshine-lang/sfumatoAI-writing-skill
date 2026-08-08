#!/usr/bin/env python3
"""Validate deterministic parts of a Xiaohongshu knowledge-post delivery."""

from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
JPEG_SOF_MARKERS = {
    0xC0,
    0xC1,
    0xC2,
    0xC3,
    0xC5,
    0xC6,
    0xC7,
    0xC9,
    0xCA,
    0xCB,
    0xCD,
    0xCE,
    0xCF,
}


class ValidationError(Exception):
    """Raised when a manifest or delivery artifact is invalid."""


def image_size(path: Path) -> tuple[int, int]:
    """Read PNG or JPEG dimensions using only the Python standard library."""
    with path.open("rb") as handle:
        header = handle.read(24)
        if header.startswith(PNG_SIGNATURE):
            if len(header) < 24:
                raise ValidationError(f"PNG header is incomplete: {path}")
            width, height = struct.unpack(">II", header[16:24])
            return width, height

        if header[:2] != b"\xff\xd8":
            raise ValidationError(f"Unsupported image format (use PNG or JPEG): {path}")

        handle.seek(2)
        while True:
            marker_prefix = handle.read(1)
            if not marker_prefix:
                break
            if marker_prefix != b"\xff":
                continue

            marker = handle.read(1)
            while marker == b"\xff":
                marker = handle.read(1)
            if not marker:
                break

            marker_value = marker[0]
            if marker_value in {0xD8, 0xD9}:
                continue

            length_bytes = handle.read(2)
            if len(length_bytes) != 2:
                break
            segment_length = struct.unpack(">H", length_bytes)[0]
            if segment_length < 2:
                raise ValidationError(f"Invalid JPEG segment: {path}")

            if marker_value in JPEG_SOF_MARKERS:
                payload = handle.read(5)
                if len(payload) != 5:
                    break
                height, width = struct.unpack(">HH", payload[1:5])
                return width, height

            handle.seek(segment_length - 2, 1)

    raise ValidationError(f"Cannot read image dimensions: {path}")


def non_newline_length(value: str) -> int:
    return len(value.replace("\r", "").replace("\n", ""))


def valid_http_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def validate_manifest(manifest_path: Path) -> list[str]:
    errors: list[str] = []
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValidationError(f"Manifest not found: {manifest_path}") from exc
    except json.JSONDecodeError as exc:
        raise ValidationError(f"Invalid JSON in {manifest_path}: {exc}") from exc

    require(isinstance(data, dict), "Manifest root must be an object.", errors)
    if not isinstance(data, dict):
        return errors

    recommended = data.get("recommended_title")
    alternatives = data.get("alternative_titles")
    body = data.get("body")
    images = data.get("images")
    sources = data.get("sources")

    require(isinstance(recommended, str) and bool(recommended.strip()), "Recommended title is required.", errors)
    require(isinstance(alternatives, list) and len(alternatives) == 2, "Exactly two alternative titles are required.", errors)
    if isinstance(alternatives, list):
        require(all(isinstance(item, str) and item.strip() for item in alternatives), "Alternative titles must be non-empty strings.", errors)
        titles = [recommended, *alternatives] if isinstance(recommended, str) else alternatives
        require(len(set(titles)) == len(titles), "Recommended and alternative titles must be unique.", errors)

    require(isinstance(body, str) and bool(body.strip()), "Body is required.", errors)
    if isinstance(body, str):
        require(non_newline_length(body) <= 200, f"Body exceeds 200 characters: {non_newline_length(body)}.", errors)

    require(isinstance(images, list) and len(images) >= 4, "At least four images are required.", errors)
    if isinstance(images, list) and images:
        roles = [item.get("role") if isinstance(item, dict) else None for item in images]
        require(roles[0] == "cover", "The first image must have role 'cover'.", errors)
        require(roles.count("cover") == 1, "Exactly one image must have role 'cover'.", errors)

        for index, item in enumerate(images, start=1):
            if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                errors.append(f"Image {index} must contain a string path.")
                continue
            image_path = Path(item["path"])
            if not image_path.is_absolute():
                image_path = manifest_path.parent / image_path
            if not image_path.is_file():
                errors.append(f"Image {index} does not exist: {image_path}")
                continue
            try:
                width, height = image_size(image_path)
            except ValidationError as exc:
                errors.append(str(exc))
                continue
            if width * 4 != height * 3:
                errors.append(f"Image {index} is not exact 3:4: {image_path} ({width}x{height}).")

    require(isinstance(sources, list) and len(sources) >= 2, "At least two sources are required.", errors)
    if isinstance(sources, list):
        valid_sources = [
            item
            for item in sources
            if isinstance(item, dict)
            and isinstance(item.get("title"), str)
            and item["title"].strip()
            and valid_http_url(item.get("url"))
        ]
        require(len(valid_sources) >= 2, "At least two sources must have a title and valid HTTP(S) URL.", errors)

    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="Path to the delivery manifest JSON file.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest_path = args.manifest.expanduser().resolve()
    try:
        errors = validate_manifest(manifest_path)
    except ValidationError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1

    if errors:
        print("[FAIL] Delivery validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print(f"[PASS] Delivery manifest is valid: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
