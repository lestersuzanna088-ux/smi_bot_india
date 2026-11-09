"""Профиль страны: всё, что отличает бота одной страны от другого.

Файл data/country.yaml — название страны, флаг, регионы, часовой пояс, язык источников,
слова для бесплатной оценки важности, подсказка для Claude и цвета карточек.
Код бота одинаковый для всех стран; другой путь к профилю можно задать в SMI_COUNTRY_FILE.
"""
from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def fold(text: str) -> str:
    """нижний регистр, без диакритики и пунктуации"""
    t = unicodedata.normalize("NFKD", (text or "").lower())
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    t = re.sub(r"[^\w\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def word_regex(words: list[str] | str | None) -> re.Pattern:
    """Список слов/фраз → регулярка по «сложенному» тексту (см. fold)."""
    if isinstance(words, str):
        words = words.split(",")
    parts = sorted({fold(w) for w in (words or []) if fold(w)}, key=len, reverse=True)
    if not parts:
        return re.compile(r"(?!x)x")  # никогда не совпадает
    return re.compile(r"\b(" + "|".join(re.escape(p).replace(r"\ ", r"\s+") for p in parts) + r")\b")


def _rgb(value, default: tuple[int, int, int]) -> tuple[int, int, int]:
    try:
        r, g, b = (int(x) for x in value)
        return (r, g, b)
    except Exception:  # noqa: BLE001
        return default


@dataclass
class Country:
    code: str                      # код «вся страна» в календаре и у новостей (BR, IN, PH)
    flag: str
    name: str                      # Бразилия
    name_gen: str                  # Бразилии («Инфоповоды Бразилии»)
    name_loc: str                  # в Бразилии
    all_country: str               # Вся Бразилия
    timezone: str
    tz_label: str                  # «по Бразилиа»
    source_lang: str               # язык новостей для переводчика: pt, en …
    source_lang_name: str          # «португальском»
    trends_geo: str
    region: dict                   # слова: one, many, gen_many, all, short
    regions: dict[str, tuple[str, str, str]]
    region_buttons: dict[str, str] = field(default_factory=dict)
    buttons_per_row: int = 5
    national_aliases: list[str] = field(default_factory=list)
    detect_prefix: str = ""
    detect_skip: list[str] = field(default_factory=list)
    detect_aliases: dict[str, list[str]] = field(default_factory=dict)
    detect_ignore: list[str] = field(default_factory=list)
    scoring: dict = field(default_factory=dict)
    ai_prompt: str = ""
    add_example: str = ""
    colors: dict = field(default_factory=dict)
    welcome_rows: list[str] = field(default_factory=list)

    # ───────────── регионы ─────────────
    @property
    def region_codes(self) -> list[str]:
        return list(self.regions.keys())

    def button_label(self, code: str) -> str:
        return self.region_buttons.get(code, code)

    # ───────────── цвета карточек ─────────────
    @property
    def stripe(self) -> list[tuple[int, int, int]]:
        return [_rgb(c, (255, 255, 255)) for c in self.colors.get("stripe", [])] or [(0, 156, 59)]

    @property
    def accent(self) -> tuple[int, int, int]:
        return _rgb(self.colors.get("accent"), (255, 223, 0))

    @property
    def glow1(self) -> tuple[int, int, int]:
        return _rgb(self.colors.get("glow1"), (0, 156, 59))

    @property
    def glow2(self) -> tuple[int, int, int]:
        return _rgb(self.colors.get("glow2"), self.accent)


def load_country(path: Path | str | None = None) -> Country:
    path = Path(path or os.environ.get("SMI_COUNTRY_FILE") or ROOT / "data" / "country.yaml")
    d = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    regions = {}
    buttons = {}
    aliases = {}
    for code, val in (d.get("regions") or {}).items():
        code = str(code).upper()
        if isinstance(val, dict):
            regions[code] = (val["ru"], val.get("local", val["ru"]), val.get("group", ""))
            if val.get("button"):
                buttons[code] = str(val["button"])
            if val.get("detect") is not None:
                aliases[code] = [str(a) for a in val["detect"]]
        else:
            ru, local, group = (list(val) + ["", ""])[:3]
            regions[code] = (ru, local or ru, group)
    reserved = {"ALL", "INT", "NONE", "DONE", str(d["code"]).upper()}
    clash = reserved & set(regions)
    if clash:
        raise ValueError(f"Коды регионов совпадают со служебными: {', '.join(sorted(clash))}")
    region_words = {"one": "регион", "many": "регионы", "gen_many": "регионов", "all": "Все регионы",
                    "short": "регион"}
    region_words.update(d.get("region_words") or {})
    return Country(
        code=str(d["code"]).upper(),
        flag=d.get("flag", ""),
        name=d["name"],
        name_gen=d["name_gen"],
        name_loc=d["name_loc"],
        all_country=d.get("all_country", f"Вся страна"),
        timezone=d["timezone"],
        tz_label=d.get("tz_label", ""),
        source_lang=d.get("source_lang", "en"),
        source_lang_name=d.get("source_lang_name", "языке оригинала"),
        trends_geo=d.get("trends_geo", ""),
        region=region_words,
        regions=regions,
        region_buttons=buttons,
        buttons_per_row=int(d.get("buttons_per_row", 5)),
        national_aliases=[str(a).upper() for a in d.get("national_aliases", [])],
        detect_prefix=d.get("detect_prefix", ""),
        detect_skip=[str(c).upper() for c in d.get("detect_skip", [])],
        detect_aliases=aliases,
        detect_ignore=[str(x) for x in d.get("detect_ignore", [])],
        scoring=d.get("scoring") or {},
        ai_prompt=d.get("ai_prompt", ""),
        add_example=d.get("add_example", ""),
        colors=d.get("colors") or {},
        welcome_rows=d.get("welcome_rows") or [],
    )


COUNTRY = load_country()
