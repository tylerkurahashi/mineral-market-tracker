"""設定ロード。"""
from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


def load_yaml(name: str) -> dict:
    with open(ROOT / "config" / name, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_stones() -> list[dict]:
    return load_yaml("stones.yaml")["stones"]


def load_sources() -> dict:
    return load_yaml("sources.yaml")


def env(key: str, default: str | None = None) -> str | None:
    return os.environ.get(key, default)


DATA_DIR = ROOT / "data"
REPORTS_DIR = ROOT / "reports"
