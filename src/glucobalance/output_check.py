"""The output check (design rule 4): a dose or setting number in a reply must match a tool result.

The assistant never computes a dose, but a model can still invent one. After the model has
written its reply, this module finds every number that is used as a dose or a setting (a
number of insulin units, a carb ratio, a sensitivity factor) and compares it with the numbers
the tools returned in the same turn. One number that no tool returned and the whole reply is
blocked. It is a regular expression, not a model: simple to read, and it cannot be talked out
of anything.

It is deliberately strict. A false alarm costs a re-ask; a missed invented dose costs more.
Glucose values and carb amounts are not doses, so they are not checked here.
"""

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import BaseModel

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
_UNIT = (
    r"(?:units?|iu|u|g\s*/\s*u|g\s+per\s+(?:unit|u)|grams?\s+per\s+(?:unit|u)"
    r"|mg\s*/\s*dl\s+per\s+(?:unit|u)|mg\s*/\s*dl\s*/\s*u|mmol\s*/\s*l\s+per\s+(?:unit|u))"
)
_BEFORE_UNIT = re.compile(rf"(?<![\w.,:/])({_NUMBER})\s*{_UNIT}\b", re.IGNORECASE)
_WORD_BEFORE_UNIT = re.compile(rf"\b({_WORD})\s+(?:units?|iu)\b", re.IGNORECASE)
# 2. "1 unit per 12 g", "1:12" written as a ratio.
_PER_GRAMS = re.compile(rf"\bunits?\s+per\s+({_NUMBER})\s*g\b", re.IGNORECASE)
_RATIO = re.compile(rf"(?<![\d:])1\s*:\s*({_NUMBER})\b(?!\s*(?:am|pm)\b)", re.IGNORECASE)
# The number must stand alone, not be part of a clock time such as 00:00 (never a dose).
_ALONE = r"(?<![\d:])"
_END = r"(?!\d|[.,]\d|\s*:)"
# 3. A setting named, then its value: "ICR of 10", "sensitivity factor is 45", "ISF: 40".
_SETTING_WORD = (
    r"(?:ICR|ISF|carb(?:ohydrate)?s?\s+ratio|insulin[- ]to[- ]carb|sensitivity(?:\s+factor)?"
    r"|correction\s+factor)"
)
_AFTER_SETTING = re.compile(rf"\b{_SETTING_WORD}\b[^.\d\n]{{0,30}}?{_ALONE}({_NUMBER}){_END}", re.I)
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


def numbers_in(data: Any) -> set[Decimal]:
    """Every number in a tool result: numeric values and numbers inside strings."""
    found: set[Decimal] = set()
    if isinstance(data, bool) or data is None:
        return found
    if isinstance(data, int | float | Decimal):
        found.add(Decimal(str(data)).normalize())
    elif isinstance(data, str):
        for raw in re.findall(_NUMBER, data):
            value = _decimal(raw)
            if value is not None:
                found.add(value.normalize())
    elif isinstance(data, dict):
        for value in data.values():
            found |= numbers_in(value)
    elif isinstance(data, list | tuple | set):
        for value in data:
            found |= numbers_in(value)
    return found


def dose_numbers(text: str) -> list[tuple[Decimal, str]]:
    """The numbers in ``text`` that are used as a dose or a setting, with the text as written,
    in the order they appear."""
    hits: dict[int, tuple[Decimal, str]] = {}

    def add(match: re.Match[str], raw: str, *, skip_units: bool = False) -> None:
        value = _decimal(raw)
        if value is None:
            return
        if skip_units and _NOT_A_DOSE_UNIT.match(text, match.end(1)):
            return
        hits.setdefault(match.start(1), (value, raw))

    for m in _BEFORE_UNIT.finditer(text):
        add(m, m.group(1))
    for m in _PER_GRAMS.finditer(text):
        add(m, m.group(1))
    for m in _RATIO.finditer(text):
        add(m, m.group(1))
    for m in _AFTER_SETTING.finditer(text):
        add(m, m.group(1))
    for m in _AFTER_DOSE.finditer(text):
        add(m, m.group(1), skip_units=True)
    for m in _WORD_BEFORE_UNIT.finditer(text):
        hits.setdefault(m.start(1), (Decimal(_WORDS[m.group(1).lower()]), m.group(1)))
    # "1 unit per 12 g" also names the 1 as a number of units; the 1 is found by _BEFORE_UNIT.
    return [hits[position] for position in sorted(hits)]


def check_reply(text: str, allowed: set[Decimal]) -> CheckResult:
    """Pass when every dose or setting number in ``text`` is in ``allowed``."""
    normalised = {value.normalize() for value in allowed}
    bad = tuple(raw for value, raw in dose_numbers(text) if value.normalize() not in normalised)
    return CheckResult(ok=not bad, unverified=bad)
