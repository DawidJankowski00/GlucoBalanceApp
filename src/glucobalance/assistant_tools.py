"""The tools the assistant may call. They are its only way to the user's data.

Each tool is a thin read of existing, tested code: the readings, ``build_analytics``,
the settings, ``advise_bolus`` (Stage 8) and ``suggestions_for`` (Stage 8). The model picks a
tool and its arguments; the numbers always come from here. Results are plain JSON so they can
go back to the model and to the output check (``output_check.numbers_in``).

Glucose values are given in the user's display unit, and ``_mgdl`` fields are added where a
value is stored in mg/dL, so the model can quote either without converting anything itself.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from glucobalance.adjustment_service import suggestions_for
from glucobalance.analytics_service import PERIOD_CHOICES, build_analytics
from glucobalance.dosing_safety import Refusal
from glucobalance.dosing_service import MAX_CARBS_G, advise_bolus
from glucobalance.llm import ToolSpec
from glucobalance.models import DisplayUnit, User, UserSettings
from glucobalance.patterns import PatternKind
from glucobalance.repositories import GlucoseRepository
from glucobalance.units import mgdl_to_mmoll
from glucobalance.weekly_review import save_suggestions

MAX_HOURS = 24
MAX_READINGS = 36
MAX_EXAMPLES = 5
REVIEW_PAGE = "/assistant/review"


class ToolError(ValueError):
    """The call was wrong (unknown tool, bad argument). The message goes back to the model."""


TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        "get_recent_glucose",
        "The user's latest glucose reading (with its age in minutes and trend) and the readings "
        "of the last few hours, newest first, in the user's unit.",
        {
            "type": "object",
            "properties": {
                "hours": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": MAX_HOURS,
                    "description": "How many hours back to look (default 3).",
                }
            },
        },
    ),
    ToolSpec(
        "get_patterns",
        "Statistics (time in range, mean, variability) and rule-based patterns (night lows, "
        "highs after breakfast, high fasting values) for the last 14 or 30 days, each with "
        "example readings.",
        {
            "type": "object",
            "properties": {"days": {"type": "integer", "enum": list(PERIOD_CHOICES)}},
        },
    ),
    ToolSpec(
        "get_settings",
        "The user's treatment settings: target range, carb ratio (ICR) and sensitivity (ISF) "
        "per time block, insulin action time, max bolus, dose step and clinic contact.",
        {"type": "object", "properties": {}},
    ),
    ToolSpec(
        "calculate_bolus",
        "Run the app's tested bolus calculator for a meal now. It checks safety first (no "
        "recent reading, a stale reading or a low glucose means no dose). This is the ONLY "
        "source of a dose number.",
        {
            "type": "object",
            "properties": {
                "carbs_g": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": float(MAX_CARBS_G),
                    "description": "Grams of carbohydrate the user says they will eat (0 for a "
                    "correction only).",
                }
            },
            "required": ["carbs_g"],
        },
    ),
    ToolSpec(
        "propose_adjustment",
        "Ask the app's capped suggester for setting changes based on the last 14 days of "
        "patterns. Suggestions are saved for the user to accept or reject on the review page; "
        "nothing changes until they do. The size of a change is decided by the app.",
        {
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "enum": [kind.value for kind in PatternKind],
                    "description": "Only suggestions for this pattern (optional).",
                }
            },
        },
    ),
)


def _number(value: Decimal) -> float | int:
    """A Decimal as a JSON number, without trailing zeros (4.50 -> 4.5, 10.0 -> 10)."""
    normal = value.normalize()
    return int(normal) if normal == normal.to_integral_value() else float(normal)


def _int_arg(arguments: dict[str, Any], name: str, default: int) -> int:
    raw = arguments.get(name, default)
    if raw is None:
        return default
    if isinstance(raw, bool) or not isinstance(raw, int | float | str):
        raise ToolError(f"{name} must be a whole number.")
    try:
        value = int(float(raw))
    except ValueError as error:
        raise ToolError(f"{name} must be a whole number.") from error
    return value


@dataclass
class Toolbox:
    """The tools bound to one user, one database session and one moment."""

    session: Session
    user: User
    now: datetime

    @property
    def settings(self) -> UserSettings:
        settings = self.user.settings
        if settings is None:
            raise ToolError("The user has not set up their treatment settings yet.")
        return settings

    def _glucose(self, mgdl: float) -> float | int:
        if self.settings.display_unit is DisplayUnit.MMOLL:
            return mgdl_to_mmoll(mgdl)
        return round(mgdl)

    def local_time(self, moment: datetime) -> str:
        zone = ZoneInfo(self.settings.timezone)
        return moment.astimezone(zone).strftime("%a %d %b %H:%M")

    def run(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
            "get_recent_glucose": self.get_recent_glucose,
            "get_patterns": self.get_patterns,
            "get_settings": self.get_settings,
            "calculate_bolus": self.calculate_bolus,
            "propose_adjustment": self.propose_adjustment,
        }
        handler = handlers.get(name)
        if handler is None:
            raise ToolError(f"There is no tool called {name!r}.")
        return handler(arguments)

    def get_recent_glucose(self, arguments: dict[str, Any]) -> dict[str, Any]:
        hours = _int_arg(arguments, "hours", 3)
        if not 1 <= hours <= MAX_HOURS:
            raise ToolError(f"hours must be between 1 and {MAX_HOURS}.")
        repo = GlucoseRepository(self.session)
        unit = self.settings.display_unit.value
        latest = repo.latest(self.user.id)
        if latest is None:
            return {"unit": unit, "latest": None, "readings": [], "note": "No readings yet."}
        window = repo.between(
            self.user.id, self.now - timedelta(hours=hours), self.now + timedelta(seconds=1)
        )
        readings = sorted(window, key=lambda r: r.measured_at, reverse=True)[:MAX_READINGS]
        return {
            "unit": unit,
            "target_range": [
                self._glucose(self.settings.target_low_mgdl),
                self._glucose(self.settings.target_high_mgdl),
            ],
            "latest": {
                "value": self._glucose(latest.value_mgdl),
                "value_mgdl": latest.value_mgdl,
                "at": self.local_time(latest.measured_at),
                "minutes_ago": int((self.now - latest.measured_at).total_seconds() // 60),
                "trend": latest.trend.value if latest.trend else None,
            },
            "readings": [
                {"at": self.local_time(r.measured_at), "value": self._glucose(r.value_mgdl)}
                for r in readings
            ],
        }

    def get_patterns(self, arguments: dict[str, Any]) -> dict[str, Any]:
        days = _int_arg(arguments, "days", PERIOD_CHOICES[0])
        if days not in PERIOD_CHOICES:
            raise ToolError("days must be 14 or 30.")
        data = build_analytics(self.session, self.user, days=days, now=self.now)
        stats = data.stats
        return {
            "unit": data.unit.value,
            "days": days,
            "statistics": None
            if stats is None
            else {
                "readings": stats.count,
                "mean": self._glucose(stats.mean),
                "time_in_range_percent": round(stats.in_range, 1),
                "time_below_percent": round(stats.below, 1),
                "time_above_percent": round(stats.above, 1),
                "cv_percent": round(stats.cv, 1),
                "gmi_percent": round(stats.gmi, 1),
                "warning": stats.warning,
            },
            "low_episodes": data.low_episodes,
            "patterns": [
                {
                    "kind": f.kind.value,
                    "title": f.title,
                    "detail": f.detail,
                    "typical_value": self._glucose(f.headline_mgdl),
                    "supporting_readings": len(f.evidence),
                    "examples": [
                        {"at": self.local_time(e.measured_at), "value": self._glucose(e.value_mgdl)}
                        for e in f.evidence[:MAX_EXAMPLES]
                    ],
                }
                for f in data.findings
            ],
        }

    def get_settings(self, arguments: dict[str, Any]) -> dict[str, Any]:
        s = self.settings
        mmol = s.display_unit is DisplayUnit.MMOLL
        return {
            "unit": s.display_unit.value,
            "delivery": s.delivery_mode.value,
            "monitoring": s.monitoring_mode.value,
            "target_range": [self._glucose(s.target_low_mgdl), self._glucose(s.target_high_mgdl)],
            "insulin_action_hours": round(s.insulin_action_minutes / 60, 2),
            "max_bolus_units": _number(s.max_bolus_units),
            "dose_step_units": _number(s.dose_step_units),
            "time_blocks": [
                {
                    "from": b.start_time.strftime("%H:%M"),
                    "icr_grams_per_unit": _number(b.icr_grams_per_unit),
                    "isf_per_unit": mgdl_to_mmoll(b.isf_mgdl) if mmol else b.isf_mgdl,
                    "isf_mgdl_per_unit": b.isf_mgdl,
                }
                for b in s.time_blocks
            ],
            "clinician_contact": s.clinician_contact,
        }

    def calculate_bolus(self, arguments: dict[str, Any]) -> dict[str, Any]:
        raw = arguments.get("carbs_g")
        if isinstance(raw, bool) or not isinstance(raw, int | float | str):
            raise ToolError("carbs_g is required: the grams of carbohydrate.")
        try:
            carbs = Decimal(str(raw))
        except ArithmeticError as error:
            raise ToolError("carbs_g must be a number.") from error
        if not carbs.is_finite() or not Decimal(0) <= carbs <= MAX_CARBS_G:
            raise ToolError(f"carbs_g must be between 0 and {MAX_CARBS_G}.")
        advice = advise_bolus(self.session, self.user, carbs, now=self.now)
        if isinstance(advice, Refusal):
            return {
                "status": "refused",
                "reason": advice.reason.value,
                "message": advice.message,
                "instruction": "Give no dose number. Tell the user the message.",
            }
        r = advice.result
        cents = Decimal("0.01")
        return {
            "status": "ok",
            "carbs_g": _number(carbs),
            "units": _number(r.units),
            "capped_at_max_bolus": r.capped,
            "meal_units": _number(r.meal_units.quantize(cents)),
            "correction_units": _number(r.correction_units.quantize(cents)),
            "insulin_on_board_units": _number(r.iob_units.quantize(cents)),
            "glucose": self._glucose(advice.glucose_mgdl),
            "reading_at": self.local_time(advice.reading_at),
            "correction_target": self._glucose(advice.target_mgdl),
            "icr_grams_per_unit": _number(advice.icr),
            "isf_mgdl_per_unit": advice.isf_mgdl,
            "time_block_from": advice.block_start.strftime("%H:%M"),
            "note": "A suggestion for the user to check, not an instruction.",
        }

    def propose_adjustment(self, arguments: dict[str, Any]) -> dict[str, Any]:
        raw = arguments.get("pattern")
        try:
            only = PatternKind(raw) if raw else None
        except ValueError as error:
            raise ToolError(f"Unknown pattern {raw!r}.") from error
        found = suggestions_for(self.session, self.user, now=self.now)
        if only is not None:
            found = [s for s in found if s.pattern is only]
        rows = save_suggestions(self.session, self.user, found, now=self.now)
        return {
            "suggestions": [
                {
                    "id": row.id,
                    "pattern": row.pattern,
                    "setting": row.setting,
                    "time_block_from": row.block_start.strftime("%H:%M"),
                    "current": _number(row.current_value),
                    "proposed": _number(row.proposed_value),
                    "reason": row.reason,
                }
                for row in rows
            ],
            "next_step": "Nothing has changed. The user accepts or rejects each suggestion on "
            f"the review page ({REVIEW_PAGE}) and should agree it with their diabetes team.",
        }
