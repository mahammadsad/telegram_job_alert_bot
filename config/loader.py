from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]


def load_yaml(name: str) -> dict[str, Any]:
    path = ROOT / "config" / name
    with path.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def load_sources() -> list[dict[str, Any]]:
    return list(load_yaml("sources.yaml").get("sources", []))


def load_trusted_domains() -> set[str]:
    values = load_yaml("trusted_domains.yaml").get("trusted_domains", [])
    return {str(value).strip().lower().rstrip(".") for value in values if value}

