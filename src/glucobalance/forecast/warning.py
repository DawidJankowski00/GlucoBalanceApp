"""The only way the forecast reaches the user: a "likely low soon" warning.

The predicted number is never shown. Even a good 30-minute forecast misses by around 10 to 20
mg/dL on average (see ``docs/forecast/report.md``), so a number would look more certain than
it is and could tempt someone to dose from it. A warning that says "check and be ready to
treat" asks for an action that is safe even when the forecast is wrong.

The warning fires when the prediction is below 80 mg/dL, not 70. Forecasts pull towards the
average, so predictions of an oncoming low tend to land a little above it; on the synthetic
test patients a 70 mg/dL line caught under half of the lows, while 80 caught about nine in
ten at the price of more false alarms (the report has the full table).
"""

LOW_MGDL = 70
WARN_BELOW_MGDL = 80


def likely_low_soon(
    current_mgdl: float,
    predicted_mgdl: float,
    *,
    low_mgdl: int = LOW_MGDL,
    warn_below: int = WARN_BELOW_MGDL,
) -> bool:
    """Warn when glucose is not low yet but is predicted to fall below ``warn_below``.

    When glucose is already below ``low_mgdl`` the live page shows the low itself, with
    treatment steps, so the forecast adds nothing.
    """
    return current_mgdl >= low_mgdl and predicted_mgdl < warn_below
