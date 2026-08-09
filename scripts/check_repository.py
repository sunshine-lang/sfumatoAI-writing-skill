#!/usr/bin/env python3
"""Run dependency-free checks for the sfumatoAI Writing Skill repository."""

from __future__ import annotations

import json
import py_compile
import re
import struct
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_NAME = "sfumatoai-writing-skill"
SKILL_ROOT = REPO_ROOT / "skills" / SKILL_NAME
BRAND_ASSET_ROOT = SKILL_ROOT / "assets" / "ip"
BRAND_ASSETS = {
    "sfumato-ip-walking.png": (1086, 1448),
    "sfumato-ip-standing.png": (1086, 1448),
    "sfumato-ip-profile-walking.png": (1086, 1448),
}

REQUIRED_FILES = (
    REPO_ROOT / "README.md",
    REPO_ROOT / "LICENSE",
    REPO_ROOT / "ASSET_LICENSE.md",
    REPO_ROOT / "CONTRIBUTING.md",
    SKILL_ROOT / "SKILL.md",
    SKILL_ROOT / "agents" / "openai.yaml",
    SKILL_ROOT / "assets" / "delivery-manifest.template.json",
    SKILL_ROOT / "references" / "content-standards.md",
    SKILL_ROOT / "references" / "delivery-contract.md",
    SKILL_ROOT / "references" / "xiaohongshu-operations.md",
    SKILL_ROOT / "references" / "pilot-agent-example.md",
    SKILL_ROOT / "references" / "brand-ip.md",
    SKILL_ROOT / "references" / "visual-system.md",
    SKILL_ROOT / "scripts" / "validate_delivery.py",
    BRAND_ASSET_ROOT / "brand-ip.manifest.json",
    BRAND_ASSET_ROOT / "LICENSE.txt",
    *(BRAND_ASSET_ROOT / filename for filename in BRAND_ASSETS),
)

FORBIDDEN_SKILL_FILES = {
    "README.md",
    "INSTALLATION_GUIDE.md",
    "QUICK_REFERENCE.md",
    "CHANGELOG.md",
}


def fail(message: str, errors: list[str]) -> None:
    errors.append(message)


def parse_frontmatter(skill_file: Path, errors: list[str]) -> dict[str, str]:
    text = skill_file.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    if not match:
        fail("SKILL.md has invalid YAML frontmatter delimiters.", errors)
        return {}

    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if not line.strip():
            continue
        key, separator, value = line.partition(":")
        if not separator:
            fail(f"Cannot parse frontmatter line: {line}", errors)
            continue
        fields[key.strip()] = value.strip().strip('"').strip("'")
    return fields


def png_dimensions(path: Path) -> tuple[int, int]:
    header = path.read_bytes()[:24]
    signature = b"\x89PNG\r\n\x1a\n"
    if len(header) != 24 or header[:8] != signature or header[12:16] != b"IHDR":
        raise ValueError("invalid PNG header")
    return struct.unpack(">II", header[16:24])


def main() -> int:
    errors: list[str] = []

    for path in REQUIRED_FILES:
        if not path.is_file():
            fail(f"Missing required file: {path.relative_to(REPO_ROOT)}", errors)

    if errors:
        for error in errors:
            print(f"[FAIL] {error}", file=sys.stderr)
        return 1

    if SKILL_ROOT.name != SKILL_NAME:
        fail("Skill folder name does not match the internal Skill name.", errors)

    frontmatter = parse_frontmatter(SKILL_ROOT / "SKILL.md", errors)
    name = frontmatter.get("name", "")
    description = frontmatter.get("description", "")

    if name != SKILL_NAME:
        fail(f"Expected Skill name '{SKILL_NAME}', got '{name}'.", errors)
    if not re.fullmatch(r"[a-z0-9-]+", name):
        fail("Skill name must contain only lowercase letters, digits, and hyphens.", errors)
    if not description:
        fail("Skill description is required.", errors)
    if len(description) > 1024:
        fail("Skill description exceeds 1024 characters.", errors)
    if "<" in description or ">" in description:
        fail("Skill description cannot contain angle brackets.", errors)

    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    if "[ASSET_LICENSE.md](ASSET_LICENSE.md)" not in readme:
        fail("README.md must link to ASSET_LICENSE.md.", errors)

    unexpected_frontmatter = set(frontmatter) - {"name", "description"}
    if unexpected_frontmatter:
        fail(f"Unexpected SKILL.md frontmatter fields: {sorted(unexpected_frontmatter)}", errors)

    skill_files = {path.name for path in SKILL_ROOT.iterdir() if path.is_file()}
    forbidden = sorted(skill_files & FORBIDDEN_SKILL_FILES)
    if forbidden:
        fail(f"Human-facing repository docs must not live inside the Skill folder: {forbidden}", errors)

    openai_yaml = (SKILL_ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
    if 'display_name: "sfumatoAI Writing Skill"' not in openai_yaml:
        fail("agents/openai.yaml has a stale display_name.", errors)
    if f"${SKILL_NAME}" not in openai_yaml:
        fail("agents/openai.yaml default_prompt must mention the internal Skill name.", errors)

    for path in SKILL_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".md", ".yaml", ".json", ".py"}:
            continue
        text = path.read_text(encoding="utf-8")
        if "[TODO" in text or "TODO:" in text:
            fail(f"Unresolved TODO in {path.relative_to(REPO_ROOT)}", errors)

    template_path = SKILL_ROOT / "assets" / "delivery-manifest.template.json"
    try:
        json.loads(template_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"Invalid delivery manifest template: {exc}", errors)

    brand_manifest_path = BRAND_ASSET_ROOT / "brand-ip.manifest.json"
    try:
        brand_manifest = json.loads(brand_manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"Invalid brand IP manifest: {exc}", errors)
        brand_manifest = {}

    manifest_files = {
        item.get("file")
        for item in brand_manifest.get("assets", [])
        if isinstance(item, dict)
    }
    if manifest_files != set(BRAND_ASSETS):
        fail("Brand IP manifest does not match the required image set.", errors)
    if brand_manifest.get("license") != "LICENSE.txt":
        fail("Brand IP manifest must carry the portable LICENSE.txt reference.", errors)

    for filename, expected_dimensions in BRAND_ASSETS.items():
        path = BRAND_ASSET_ROOT / filename
        try:
            dimensions = png_dimensions(path)
        except ValueError as exc:
            fail(f"Invalid brand image {filename}: {exc}", errors)
            continue
        if dimensions != expected_dimensions:
            fail(
                f"Unexpected dimensions for {filename}: {dimensions}, "
                f"expected {expected_dimensions}",
                errors,
            )
        width, height = dimensions
        if width * 4 != height * 3:
            fail(f"Brand image is not strict 3:4: {filename}", errors)

    try:
        py_compile.compile(
            str(SKILL_ROOT / "scripts" / "validate_delivery.py"),
            doraise=True,
        )
    except py_compile.PyCompileError as exc:
        fail(f"validate_delivery.py does not compile: {exc}", errors)

    if errors:
        print("[FAIL] Repository validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print(f"[PASS] Repository and Skill package are valid: {SKILL_ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
