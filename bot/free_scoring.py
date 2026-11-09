"""Бесплатный режим: важность новостей без ИИ.

Идея: громкую новость пишут сразу многие издания и её ищут в Google.
1. Похожие заголовки из разных лент склеиваются в одну «историю».
2. Важность = сколько разных изданий её подхватили
   + бонус, если тема в трендах Google по стране
   + бонус за сильные слова («умер», «трагедия», «чемпион»… — списки в data/country.yaml) и громкие имена
   − штраф за рецепты, гороскопы, промо.
"""
from __future__ import annotations

import math
import re
from collections import Counter

from .country import COUNTRY, fold, word_regex
from .states import NATIONAL, STATES

_SC = COUNTRY.scoring
STOPWORDS = set(fold(_SC.get("stopwords", "")).split())
STRONG = word_regex(_SC.get("strong"))
FAMOUS = word_regex(_SC.get("famous"))
LOW = word_regex(_SC.get("low"))
SPORT_WORDS = word_regex(_SC.get("sport"))
POLITICS_WORDS = word_regex(_SC.get("politics"))
ECONOMY_WORDS = word_regex(_SC.get("economy"))
INCIDENT_WORDS = word_regex(_SC.get("incident"))
WEATHER_WORDS = word_regex(_SC.get("weather"))
SHOWBIZ_WORDS = word_regex(_SC.get("showbiz"))


def _state_patterns() -> dict[str, re.Pattern]:
    """Регион по названию в тексте. Названия и предлоги — из профиля страны.

    Регионы из detect_skip не размечаем: новости оттуда почти всегда общенациональные
    (для Бразилии это SP и RJ — «São Paulo», «Bahia» и т. п. ещё и названия клубов).
    """
    prefix = COUNTRY.detect_prefix
    names: list[tuple[str, str]] = []
    for uf, (_, local, _) in STATES.items():
        if uf in COUNTRY.detect_skip:
            continue
        for name in COUNTRY.detect_aliases.get(uf, [local]):
            if fold(name):
                names.append((uf, fold(name)))
    names.sort(key=lambda kv: -len(kv[1]))  # длинные названия первыми
    out: dict[str, re.Pattern] = {}
    for uf, name in names:
        body = re.escape(name).replace(r"\ ", r"\s+")
        pat = (r"\b(?:" + prefix + r")\s+" if prefix else r"\b") + body + r"\b"
        out[f"{uf}|{name}"] = re.compile(pat)
    return out


STATE_PATTERNS = _state_patterns()
IGNORE_PHRASES = sorted({fold(p) for p in COUNTRY.detect_ignore if fold(p)}, key=len, reverse=True)


def tokens(title: str) -> set[str]:
    return {w for w in fold(title).split() if len(w) >= 3 and w not in STOPWORDS and not w.isdigit()}


def detect_state(text: str, topic: str) -> str:
    if topic == "sport":
        return NATIONAL
    t = fold(text)
    for phrase in IGNORE_PHRASES:  # «Cebu Pacific», «Punjab Kings» — не про регион
        t = t.replace(phrase, " ")
    for key, pat in STATE_PATTERNS.items():
        if pat.search(t):
            return key.split("|", 1)[0]
    return NATIONAL


def detect_category(text: str, topic: str) -> str:
    t = fold(text)
    if topic == "sport" or SPORT_WORDS.search(t) and not POLITICS_WORDS.search(t):
        return "sport"
    if WEATHER_WORDS.search(t):
        return "weather"
    if INCIDENT_WORDS.search(t):
        return "incident"
    if POLITICS_WORDS.search(t):
        return "politics"
    if ECONOMY_WORDS.search(t):
        return "economy"
    if topic == "entertainment" or SHOWBIZ_WORDS.search(t):
        return "showbiz"
    return "society"


def cluster(items: list[dict]) -> list[list[dict]]:
    """Склеивает новости об одном и том же (по редким общим словам в заголовках)."""
    toks = [tokens(it["title"]) for it in items]
    df = Counter(w for ts in toks for w in ts)
    n = max(1, len(items))
    idf = {w: math.log(1 + n / c) for w, c in df.items()}
    parent = list(range(len(items)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(items)):
        if not toks[i]:
            continue
        for j in range(i + 1, len(items)):
            if not toks[j]:
                continue
            shared = toks[i] & toks[j]
            if len(shared) < 2:
                continue
            small = toks[i] if len(toks[i]) <= len(toks[j]) else toks[j]
            w_shared = sum(idf[w] for w in shared)
            w_small = sum(idf[w] for w in small) or 1
            if w_shared / w_small >= 0.45:
                parent[find(i)] = find(j)
    groups: dict[int, list[dict]] = {}
    for i, it in enumerate(items):
        groups.setdefault(find(i), []).append(it)
    return list(groups.values())


def trend_hit(text: str, trends: list[dict]) -> int:
    """Трафик самого популярного тренда Google, совпавшего с новостью (0 — нет совпадений)."""
    t = " " + fold(text) + " "
    best = 0
    for tr in trends:
        term = fold(tr["term"])
        if not term:
            continue
        words = term.split()
        if len(words) == 1 and len(term) < 4:
            continue
        if all(f" {w} " in t for w in words):
            best = max(best, int(tr.get("traffic") or 1))
    return best


def score_cluster(group: list[dict], trends: list[dict]) -> dict:
    # «INQUIRER.net · Sports» и «INQUIRER.net» — одно издание
    outlets = {(it.get("source") or "").split(" · ")[0].strip().lower() for it in group}
    text = " ".join(f"{it['title']} {it.get('summary') or ''}" for it in group)
    t = fold(text)
    score = 2 + min(len(outlets), 6)  # 1 издание → 3 … 6+ изданий → 8
    traffic = trend_hit(" ".join(it["title"] for it in group), trends)
    if traffic >= 100_000:
        score += 3
    elif traffic >= 20_000:
        score += 2
    elif traffic > 0:
        score += 1
    if STRONG.search(t):
        score += 2
    if FAMOUS.search(t):
        score += 1
    if LOW.search(t):
        score -= 4
    topic = Counter(it.get("topic") or "general" for it in group).most_common(1)[0][0]
    return {
        "importance": max(1, min(10, score)),
        "category": detect_category(text, topic),
        "state": detect_state(" ".join(it["title"] for it in group), topic),
        "outlets": len(outlets),
        "trend_traffic": traffic,
    }


def pick_representative(group: list[dict]) -> dict:
    """Какую из новостей истории показывать: уже отправленную, иначе с описанием/фото, иначе самую раннюю."""
    sent = [it for it in group if it.get("breaking_sent")]
    if sent:
        return sent[0]
    return sorted(
        group,
        key=lambda it: (
            "news.google." in (it.get("url") or ""),  # прямые ссылки на издание лучше
            not it.get("summary"),
            not it.get("image_url"),
            it.get("published_at") or "",
        ),
    )[0]
