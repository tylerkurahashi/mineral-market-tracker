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


def load_sellers() -> list[dict]:
    """調査対象セラー(config/sellers.yaml)。無ければ空。"""
    path = ROOT / "config" / "sellers.yaml"
    if not path.exists():
        return []
    return load_yaml("sellers.yaml").get("sellers", []) or []


def sellers_by_platform() -> dict[str, list[str]]:
    """platform -> セラーIDリスト。"""
    out: dict[str, list[str]] = {}
    for s in load_sellers():
        if s.get("id") and s.get("platform"):
            out.setdefault(s["platform"], []).append(s["id"])
    return out


def build_species_matcher(stones: list[dict]) -> list[tuple[str, str]]:
    """タイトル→species 分類用の (正規化済み別名, species) リストを構築。

    別名は name_ja・species(英)・aliases・単語キーワード(空白なし)から集める。
    長い別名を優先(specificな名前が先にマッチ)するため長さ降順で返す。"""
    from .normalize import normalize_kana

    pairs: dict[str, str] = {}
    for st in stones:
        sp = st["species"]
        names = [st.get("name_ja", ""), sp, *st.get("aliases", [])]
        for kw in [*st.get("keywords_ja", []), *st.get("keywords_en", [])]:
            if kw and " " not in kw and "　" not in kw:
                names.append(kw)
        for nm in names:
            na = normalize_kana(nm)
            if len(na) >= 2 and na not in pairs:
                pairs[na] = sp
    return sorted(pairs.items(), key=lambda kv: len(kv[0]), reverse=True)


def env(key: str, default: str | None = None) -> str | None:
    return os.environ.get(key, default)


DATA_DIR = ROOT / "data"
REPORTS_DIR = ROOT / "reports"
