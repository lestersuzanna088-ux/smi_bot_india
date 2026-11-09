"""Отбор, перевод и краткий пересказ новостей через Claude.

Если ключа ANTHROPIC_API_KEY нет — работает простой резервный режим
по ключевым словам (без перевода).
"""
from __future__ import annotations

import datetime as dt
import json
import logging

from .country import COUNTRY, fold, word_regex
from .states import ALL_UF, NATIONAL, STATES

log = logging.getLogger(__name__)

NEWS_CATEGORIES = {
    "politics": ("Политика", "🏛"),
    "economy": ("Экономика", "💰"),
    "sport": ("Спорт", "⚽"),
    "showbiz": ("Шоу-бизнес", "🎬"),
    "incident": ("Происшествия", "🚨"),
    "weather": ("Погода и стихия", "🌧"),
    "society": ("Общество", "👥"),
    "tech": ("Технологии", "📱"),
    "world": ("В мире", "🌎"),
    "other": ("Разное", "📰"),
}

SYSTEM_PROMPT = COUNTRY.ai_prompt  # текст — в data/country.yaml, {today} и {regions} подставляются


def _system_prompt(today: dt.date) -> str:
    regions = ", ".join(f"{c} — {STATES[c][0]}" for c in ALL_UF)
    return SYSTEM_PROMPT.replace("{today}", today.strftime("%d.%m.%Y")).replace("{regions}", regions)


REPORT_TOOL = {
    "name": "report_news",
    "description": "Сохранить оценку новостей",
    "input_schema": {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "n": {"type": "integer", "description": "номер новости из списка"},
                        "importance": {"type": "integer", "minimum": 1, "maximum": 10},
                        "category": {"type": "string", "enum": list(NEWS_CATEGORIES)},
                        "state": {"type": "string", "description": f"код региона, {NATIONAL} (вся страна) или INT (другая страна)"},
                        "title_ru": {"type": "string"},
                        "summary_ru": {"type": "string"},
                        "duplicate": {"type": "boolean"},
                    },
                    "required": ["n", "importance", "category", "state", "title_ru", "summary_ru", "duplicate"],
                },
            },
            "events": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "n": {"type": "integer", "description": "номер новости-источника"},
                        "name_ru": {"type": "string"},
                        "name_pt": {"type": "string", "description": "название на языке оригинала"},
                        "start": {"type": "string", "description": "YYYY-MM-DD"},
                        "end": {"type": "string", "description": "YYYY-MM-DD или пусто"},
                        "category": {"type": "string", "enum": ["festival", "sport", "holiday", "culture", "commercial"]},
                        "scope": {"type": "string", "description": f"код региона или {NATIONAL}"},
                        "place": {"type": "string"},
                        "about": {"type": "string", "description": "1 предложение по-русски"},
                    },
                    "required": ["n", "name_ru", "start", "category", "scope", "about"],
                },
            },
        },
        "required": ["items", "events"],
    },
}


class NewsAnalyzer:
    def __init__(self, api_key: str, model: str, db=None):
        self.model = model
        self.db = db
        self.client = None
        if api_key:
            from anthropic import AsyncAnthropic

            self.client = AsyncAnthropic(api_key=api_key)

    @property
    def enabled(self) -> bool:
        return self.client is not None

    async def analyze(self, items: list[dict], already_sent: list[str], today: dt.date) -> tuple[list[dict], list[dict]]:
        """Возвращает (оценки по новостям, найденные будущие события)."""
        if not items:
            return [], []
        if not self.enabled:
            return heuristic(items), []

        lines = []
        for i, it in enumerate(items, 1):
            desc = (it.get("summary") or "")[:300]
            lines.append(f"[{i}] ({it['source']}, тема ленты: {it.get('topic')}) {it['title']}" + (f" — {desc}" if desc else ""))
        sent_block = "\n".join(f"- {t}" for t in already_sent[:60]) or "—"
        user = f"Уже отправлено за последние сутки:\n{sent_block}\n\nНовые новости:\n" + "\n".join(lines)

        resp = await self.client.messages.create(
            model=self.model,
            max_tokens=8000,
            system=_system_prompt(today),
            tools=[REPORT_TOOL],
            tool_choice={"type": "tool", "name": "report_news"},
            messages=[{"role": "user", "content": user}],
        )
        if self.db is not None and getattr(resp, "usage", None):
            self.db.kv_add("ai_input_tokens", int(resp.usage.input_tokens or 0))
            self.db.kv_add("ai_output_tokens", int(resp.usage.output_tokens or 0))
        data = next((b.input for b in resp.content if getattr(b, "type", "") == "tool_use"), None)
        if not data:
            log.warning("Claude не вернул оценку — используется резервный режим")
            return heuristic(items), []
        if isinstance(data, str):
            data = json.loads(data)

        results: list[dict] = []
        by_n = {int(x.get("n", 0)): x for x in data.get("items", []) if isinstance(x, dict)}
        for i, it in enumerate(items, 1):
            x = by_n.get(i)
            if not x:
                results.append({"id": it["id"], "importance": 0, "category": "other", "state": NATIONAL,
                                "title_ru": None, "summary_ru": None, "is_duplicate": 0})
                continue
            state = str(x.get("state", NATIONAL)).upper()
            if state not in ALL_UF and state not in (NATIONAL, "INT"):
                state = NATIONAL
            cat = x.get("category") if x.get("category") in NEWS_CATEGORIES else "other"
            results.append({
                "id": it["id"],
                "importance": max(0, min(10, int(x.get("importance", 0)))),
                "category": cat,
                "state": state,
                "title_ru": (x.get("title_ru") or it["title"]).strip()[:200],
                "summary_ru": (x.get("summary_ru") or "").strip()[:500],
                "is_duplicate": int(bool(x.get("duplicate"))),
            })

        events = []
        for ev in data.get("events", []) or []:
            try:
                start = dt.date.fromisoformat(str(ev["start"])[:10])
                end = dt.date.fromisoformat(str(ev["end"])[:10]) if ev.get("end") else start
            except (KeyError, ValueError):
                continue
            if start < today or start > today + dt.timedelta(days=370) or end < start:
                continue
            n = int(ev.get("n", 0))
            src = items[n - 1] if 0 < n <= len(items) else None
            events.append({
                "name_ru": str(ev.get("name_ru", "")).strip()[:150],
                "name_pt": str(ev.get("name_pt", "")).strip()[:150],
                "start": start.isoformat(),
                "end": end.isoformat(),
                "category": ev.get("category", "festival"),
                "scope": ev.get("scope", NATIONAL),
                "place": str(ev.get("place", "")).strip()[:120],
                "about": str(ev.get("about", "")).strip()[:300],
                "importance": 2,
                "source": "news",
                "news_url": src["url"] if src else None,
            })
        return results, [e for e in events if e["name_ru"]]


# ───────────── резервный режим без ИИ ─────────────

_SC = COUNTRY.scoring
_STRONG = word_regex(_SC.get("strong"))
_MEDIUM = word_regex(_SC.get("famous"))
_LOW = word_regex(_SC.get("low"))


def heuristic(items: list[dict]) -> list[dict]:
    out = []
    for it in items:
        text = fold(f"{it['title']} {it.get('summary', '')}")
        score = 3
        if _MEDIUM.search(text):
            score += 2
        if _STRONG.search(text):
            score += 3
        if _LOW.search(text):
            score = 2
        cat = "sport" if it.get("topic") == "sport" else ("showbiz" if it.get("topic") == "entertainment" else "other")
        out.append({
            "id": it["id"], "importance": min(score, 8), "category": cat, "state": NATIONAL,
            "title_ru": it["title"], "summary_ru": (it.get("summary") or "")[:300], "is_duplicate": 0,
        })
    return out
