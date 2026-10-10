"""The output check (design rule 4): a dose or setting number in a reply must match a tool result.

The assistant never computes a dose, but a model can still invent one. After the model has
written its reply, this module finds every number that is used as a dose or a setting (a
number of insulin units, a carb ratio, a sensitivity factor) and compares it with the values
of the same kind that the tools returned in the same turn: a number of units must match a
units value (``units``, ``meal_units``, ``max_bolus_units``...), a carb ratio an ICR value and
a sensitivity an ISF value. So "12 units" is blocked even when a tool returned 12 grams of
carbs. One number that does not match and the whole reply is blocked. It is a regular
expression, not a model: simple to read, and it cannot be talked out of anything.

It is deliberately strict. A false alarm costs a re-ask; a missed invented dose costs more.
Glucose values and carb amounts are not doses, so they are not checked here.
"""

import re
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

from pydantic import BaseModel


class Kind(StrEnum):
    UNITS = "units"  # an amount of insulin
    ICR = "icr"  # grams of carbs per unit
    ISF = "isf"  # glucose drop per unit


Allowed = Mapping[Kind, set[Decimal]]

_NUMBER = r"\d+(?:[.,]\d+)?"
_WORDS = {
    word: value
    for value, word in enumerate(
        [
            "zero",
            "one",
            "two",
            "three",
            "four",
            "five",
            "six",
            "seven",
            "eight",
            "nine",
            "ten",
            "eleven",
            "twelve",
            "thirteen",
            "fourteen",
            "fifteen",
            "sixteen",
            "seventeen",
            "eighteen",
            "nineteen",
            "twenty",
        ]
    )
}
_WORDS.update({"thirty": 30, "forty": 40, "fifty": 50})
_WORD = "|".join(sorted(_WORDS, key=len, reverse=True))

# 1. A number straight before a dose unit: "4 units", "2U", "10 g per unit", "40 mg/dL per unit".
#    The unit says the kind. The 1 of "1 unit per 12 g" is ratio notation, not a dose.
_UNIT = (
    r"(units?|iu|u|g\s*/\s*u|g\s+per\s+(?:unit|u)|grams?\s+per\s+(?:unit|u)"
    r"|mg\s*/\s*dl\s+per\s+(?:unit|u)|mg\s*/\s*dl\s*/\s*u|mmol\s*/\s*l\s+per\s+(?:unit|u))"
)
_BEFORE_UNIT = re.compile(
    rf"(?<![\w.,:/])({_NUMBER})\s*{_UNIT}\b(?!\s+per\s+{_NUMBER}\s*g\b)", re.IGNORECASE
)
_WORD_BEFORE_UNIT = re.compile(rf"\b({_WORD})\s+(?:units?|iu)\b", re.IGNORECASE)
# 2. "1 unit per 12 g", "1:12" written as a ratio.
_PER_GRAMS = re.compile(rf"\bunits?\s+per\s+({_NUMBER})\s*g\b", re.IGNORECASE)
_RATIO = re.compile(rf"(?<![\d:])1\s*:\s*({_NUMBER})\b(?!\s*(?:am|pm)\b)", re.IGNORECASE)
# The number must stand alone, not be part of a clock time such as 00:00 (never a dose).
_ALONE = r"(?<![\d:])"
_END = r"(?!\d|[.,]\d|\s*:)"
# 3. A setting named, then its value: "ICR of 10", "sensitivity factor is 45", "ISF: 40".
_ISF_WORD = r"ISF|sensitivity(?:\s+factor)?|correction\s+factor"
_ICR_WORD = r"ICR|carb(?:ohydrate)?s?\s+ratio|insulin[- ]to[- ]carb"
_AFTER_SETTING = re.compile(
    rf"\b(?:(?P<isf>{_ISF_WORD})|(?P<icr>{_ICR_WORD}))\b[^.\d\n]{{0,30}}?{_ALONE}"
    rf"(?P<number>{_NUMBER}){_END}",
    re.IGNORECASE,
)
# 4. A dose named, then its value: "dose of 3.5", "bolus is 4", "inject 2". Skips amounts of
# carbs, glucose, time and percentages, which are not doses.
_DOSE_WORD = r"(?:dose|doses|bolus|boluses|inject(?:ion)?|insulin|correction|basal)"
_AFTER_DOSE = re.compile(rf"\b{_DOSE_WORD}\b[^.\d\n]{{0,30}}?{_ALONE}({_NUMBER}){_END}", re.I)
_NOT_A_DOSE_UNIT = re.compile(
    r"\s*(?:g\b|gr\b|grams?\b|carbs?\b|mg\b|mmol\b|hours?\b|hrs?\b|h\b|minutes?\b|mins?\b|days?\b"
    r"|weeks?\b|%|am\b|pm\b|:\d)",
    re.IGNORECASE,
)


class CheckResult(BaseModel):
    ok: bool
    unverified: tuple[str, ...] = ()


def _decimal(raw: str) -> Decimal | None:
    try:
        return Decimal(raw.replace(",", "."))
    except InvalidOperation:
        return None


def _key_kind(key: str) -> Kind | None:
    key = key.lower()
    if "icr" in key:
        return Kind.ICR
    if "isf" in key:
        return Kind.ISF
    if key == "units" or key.endswith("_units"):
        return Kind.UNITS
    return None


def _number(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float | Decimal):
        return Decimal(str(value)).normalize()
    if isinstance(value, str):
        parsed = _decimal(value.strip())
        return parsed.normalize() if parsed is not None and parsed.is_finite() else None
    return None


def allowed_numbers(data: Any) -> dict[Kind, set[Decimal]]:
    """The dose and setting values in a tool result, by kind, read from the field names.

    A suggestion (``{"setting": "isf", "current": 40, "proposed": 44}``) counts its current
    and proposed values as that setting.
    """
    found: dict[Kind, set[Decimal]] = {kind: set() for kind in Kind}

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            setting = _key_kind(str(node.get("setting", "")))
            for key, value in node.items():
                kind = _key_kind(str(key))
                if kind is None and setting is not None and key in ("current", "proposed"):
                    kind = setting
                number = _number(value) if kind is not None else None
                if kind is not None and number is not None:
                    found[kind].add(number)
                else:
                    walk(value)
        elif isinstance(node, list | tuple):
            for value in node:
                walk(value)

    walk(data)
    return found


def merge(into: dict[Kind, set[Decimal]], more: Allowed) -> None:
    for kind, values in more.items():
        into.setdefault(kind, set()).update(values)


def _unit_kind(unit: str) -> Kind:
    unit = unit.lower()
    if unit.startswith(("mg", "mmol")):
        return Kind.ISF
    if unit.startswith("g"):
        return Kind.ICR
    return Kind.UNITS


def dose_numbers(text: str) -> list[tuple[Decimal, str, Kind]]:
    """The numbers in ``text`` that are used as a dose or a setting, with the text as written
    and their kind, in the order they appear."""
    hits: dict[int, tuple[Decimal, str, Kind]] = {}

    def add(start: int, end: int, raw: str, kind: Kind, *, skip_units: bool = False) -> None:
        value = _decimal(raw)
        if value is None:
            return
        if skip_units and _NOT_A_DOSE_UNIT.match(text, end):
            return
        hits.setdefault(start, (value, raw, kind))

    for m in _BEFORE_UNIT.finditer(text):
        add(m.start(1), m.end(1), m.group(1), _unit_kind(m.group(2)))
    for m in _PER_GRAMS.finditer(text):
        add(m.start(1), m.end(1), m.group(1), Kind.ICR)
    for m in _RATIO.finditer(text):
        add(m.start(1), m.end(1), m.group(1), Kind.ICR)
    for m in _AFTER_SETTING.finditer(text):
        kind = Kind.ISF if m.group("isf") else Kind.ICR
        add(m.start("number"), m.end("number"), m.group("number"), kind)
    for m in _AFTER_DOSE.finditer(text):
        add(m.start(1), m.end(1), m.group(1), Kind.UNITS, skip_units=True)
    for m in _WORD_BEFORE_UNIT.finditer(text):
        word = m.group(1)
        hits.setdefault(m.start(1), (Decimal(_WORDS[word.lower()]), word, Kind.UNITS))
    return [hits[position] for position in sorted(hits)]


def check_reply(text: str, allowed: Allowed) -> CheckResult:
    """Pass when every dose or setting number in ``text`` is a value of the same kind in
    ``allowed``."""
    bad = tuple(
        raw
        for value, raw, kind in dose_numbers(text)
        if value.normalize() not in {v.normalize() for v in allowed.get(kind, set())}
    )
    return CheckResult(ok=not bad, unverified=bad)
