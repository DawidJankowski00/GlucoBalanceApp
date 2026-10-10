"""Stage 10: a 30-minute glucose forecast, used only for a "likely low soon" warning.

The package is split like the dosing core: pure functions that can be tested with plain
values, and one service (``glucobalance.forecast_service``) that loads data from the database.

- ``history``: the plain input (readings, carbs, boluses) and synthetic patients for training.
- ``features``: turns a history into one row of numbers per moment, plus the 30-minute target.
- ``models``: the two baselines (last value, linear trend) and the gradient boosting model.
- ``evaluation``: RMSE, MAE, the Clarke error grid and how well lows are caught.
- ``warning``: the rule that turns a prediction into the warning shown on the live page.

Run ``uv run python -m glucobalance.forecast`` to train, evaluate and write the report.
"""
