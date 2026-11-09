"""Регионы страны (штаты, провинции…) — берутся из профиля страны data/country.yaml."""
from __future__ import annotations

from .country import COUNTRY

# код -> (название по-русски, местное название, макрорегион)
STATES: dict[str, tuple[str, str, str]] = COUNTRY.regions

ALL_UF = list(STATES.keys())
NATIONAL = COUNTRY.code
NATIONAL_CODES = {NATIONAL, "INT"}  # новости «про всю страну» и «из-за рубежа» — всем


def state_name(uf: str) -> str:
    if uf == NATIONAL:
        return COUNTRY.all_country
    return STATES.get(uf, (uf, uf, ""))[0]


def scope_label(scope: list[str], short: bool = False) -> str:
    """Подпись «где»: «Вся Бразилия», «Сан-Паулу», «SP · RJ · MG»."""
    if not scope or NATIONAL in scope:
        return COUNTRY.all_country
    if len(scope) == 1:
        return f"{state_name(scope[0])} ({scope[0]})" if not short else state_name(scope[0])
    if len(scope) > 6:
        return " · ".join(scope[:6]) + f" +{len(scope) - 6}"
    return " · ".join(scope)


def normalize_scope(value) -> list[str]:
    if value is None:
        return [NATIONAL]
    if isinstance(value, str):
        value = [v for v in value.replace(";", ",").replace(" ", ",").split(",") if v]
    out = []
    for v in value:
        v = str(v).strip().upper()
        if v in {NATIONAL, "ALL", "ВСЕ", *COUNTRY.national_aliases}:
            return [NATIONAL]
        if v in STATES:
            out.append(v)
    return out or [NATIONAL]
