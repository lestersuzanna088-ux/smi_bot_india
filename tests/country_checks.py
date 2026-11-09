"""Проверка данных страны этого бота: data/country.yaml, data/events.yaml, data/sources.yaml.

Запускается из test_country.py отдельным процессом (у движка в test_core.py — свой эталонный профиль).
Вручную: python -m unittest tests.country_checks
"""
from __future__ import annotations

import datetime as dt
import os
import sys
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("SMI_DATA_DIR") or ROOT / "data")
os.environ["SMI_COUNTRY_FILE"] = str(DATA / "country.yaml")
sys.path.insert(0, str(ROOT))

from bot import cards, free_scoring  # noqa: E402
from bot.calendar_engine import CATEGORIES, load_events, occurrences  # noqa: E402
from bot.country import COUNTRY  # noqa: E402
from bot.formatting import event_caption, news_caption  # noqa: E402
from bot.news import load_sources  # noqa: E402
from bot.states import ALL_UF, NATIONAL  # noqa: E402

RAW_COUNTRY = yaml.safe_load((DATA / "country.yaml").read_text(encoding="utf-8"))
RAW_EVENTS = yaml.safe_load((DATA / "events.yaml").read_text(encoding="utf-8"))
EVENTS = load_events(DATA / "events.yaml")
TODAY = dt.date(2026, 11, 9)


class CountryDataTests(unittest.TestCase):
    def test_profile(self):
        self.assertTrue(COUNTRY.regions)
        self.assertIn("{today}", COUNTRY.ai_prompt)
        self.assertIn("{regions}", COUNTRY.ai_prompt)
        from zoneinfo import ZoneInfo
        ZoneInfo(COUNTRY.timezone)
        for c in ALL_UF:
            self.assertRegex(c, r"^[A-Z0-9]{2,6}$", "код региона уходит в кнопку Telegram")
            self.assertLessEqual(len(f"st:{c}".encode()), 64)

    def test_event_scopes_are_known(self):
        valid = set(ALL_UF) | {NATIONAL}
        for item in RAW_EVENTS:
            scope = item.get("scope", NATIONAL)
            scope = [scope] if isinstance(scope, str) else scope
            for code in scope:
                self.assertIn(str(code).upper(), valid, f"{item['id']}: неизвестный регион {code}")
            self.assertIn(item.get("category", "holiday"), CATEGORIES, item["id"])

    def test_every_event_has_a_date(self):
        occs = occurrences(EVENTS, dt.date(2026, 1, 1), dt.date(2028, 12, 31))
        seen = {o.event.id for o in occs}
        missing = [e.id for e in EVENTS if e.id not in seen]
        self.assertEqual(missing, [], "у события нет даты в 2026–2028 годах (опечатка в правиле даты?)")

    def test_captions_and_cards(self):
        occs = occurrences(EVENTS, TODAY, TODAY + dt.timedelta(days=420))
        done = set()
        for o in occs:
            cap = event_caption(o, TODAY)
            self.assertLessEqual(len(cap), 1024, o.event.id)
            if o.event.id not in done:
                done.add(o.event.id)
                self.assertTrue(cards.event_card(o, TODAY).startswith(b"\x89PNG"), o.event.id)
        self.assertTrue(cards.agenda_card(occs[:7], TODAY, f"Скоро {COUNTRY.name_loc}").startswith(b"\x89PNG"))
        self.assertTrue(cards.welcome_card().startswith(b"\x89PNG"))

    def test_sources(self):
        srcs = load_sources(DATA / "sources.yaml")
        self.assertGreaterEqual(len(srcs), 5)
        for s in srcs:
            self.assertTrue(s["url"].startswith("https://"), s["name"])
            self.assertIn(s.get("topic", "general"), {"general", "sport", "entertainment"})
        self.assertEqual(len({s["name"] for s in srcs}), len(srcs), "названия лент должны различаться")

    def test_free_mode_examples(self):
        for ex in RAW_COUNTRY.get("self_test") or []:
            item = {"id": "x", "source": "s", "title": ex["title"], "topic": "general"}
            sc = free_scoring.score_cluster([item], [])
            if ex.get("low"):
                self.assertLessEqual(sc["importance"], 2, ex["title"])
                continue
            self.assertEqual(sc["state"], ex["state"], ex["title"])
            self.assertEqual(sc["category"], ex["category"], ex["title"])

    def test_news_caption_flag(self):
        item = {"category": "other", "state": NATIONAL, "title_ru": "Перевод", "title": "Original",
                "translated": 1, "source": "x", "url": "https://x", "published_at": "2026-11-09T10:00:00+00:00"}
        from zoneinfo import ZoneInfo
        self.assertIn(COUNTRY.flag, news_caption(item, ZoneInfo(COUNTRY.timezone), False))


if __name__ == "__main__":
    unittest.main()
