# 0019. Glucose forecast: synthetic training data, gradient boosting against two baselines, a warning instead of a number

- Status: accepted
- Date: 2026-10-10

## Context

Stage 10 asks for a 30-minute glucose forecast with honest error reporting, shown only as a "likely low soon" warning. There is no real data to train on (design rule: real health data stays on the user's machine, the demo holds simulated patients only), simglucose is optional and slow, and CI must test everything in seconds.

## Decision

- **Plain input, pure features** (`forecast/history.py`, `forecast/features.py`): a `History` of (time, value) tuples for readings, carbs and rapid boluses, like the seed's `SimulatedData`. One row per reading: the value, its 5/15/30-minute changes, the 30-minute least-squares slope, whether the trend is bending, insulin on board (the linear model of ADR 0017), carbs on board (linear over 3 hours), recent bolus and carbs, and the local time of day as sine and cosine. No row is built without readings 5, 15 and 30 minutes back. The target is the 30-minute *change*.
- **Synthetic patients for training** (`synthetic_history`): a small model with gamma-shaped carb and insulin curves, imperfect, late or missed boluses, corrections, treated lows, a dawn rise, drift and sensor noise. It is seeded, so every run gives the same data. `--source simglucose` swaps in the UVA/Padova simulator for a slower, more realistic run.
- **Two baselines and one learned model** (`forecast/models.py`): last value, linear trend, and scikit-learn's `HistGradientBoostingRegressor`. All three share one `Forecaster` interface with `predict(rows)`.
- **Honest evaluation** (`forecast/evaluation.py`, `forecast/experiment.py`): split by time (first 70% of each patient's days to train) and also tested on patients never seen in training. RMSE, MAE, Clarke error grid zones, and lows caught versus false alarms at three warning lines. `python -m glucobalance.forecast` writes `docs/forecast/report.md`, which states plainly that synthetic data is easier than real data.
- **A warning, never a number** (`forecast/warning.py`, `forecast_service.py`): the live page shows "Likely low soon" when glucose is at or above 70 mg/dL and the forecast is below 80 mg/dL. It needs a CGM, fresh data (15 minutes, as for dosing) and no gaps. The predicted value is never displayed or pushed, and the warning says not to dose from it.
- **The 80 mg/dL line**: at 70 the model caught under half of the lows that followed (forecasts pull towards the average). At 80 it caught about nine in ten, with roughly four in ten warnings correct. A missed low is worse than an extra "check your glucose", and the action asked for is safe either way.
- **Model files are optional** (`GBA_FORECAST_MODEL_PATH`): without one the app uses the linear trend baseline, so a fresh clone works. The Docker image trains the model at build time (seconds). Models are saved with joblib and never committed (`models/` is ignored).

## Consequences

- scikit-learn, numpy, scipy and joblib become runtime dependencies (about 100 MB in the image).
- joblib uses pickle, and loading a pickle can run code. Only model files you trained yourself may be loaded; the loader also checks the feature list so a stale model fails loudly rather than predicting nonsense.
- The reported accuracy is for synthetic patients and overstates what a real person will see. The report and the model card say so; real-data numbers need a user's own CGM history and stay on their machine.
- The forecast only knows logged carbs and insulin. Exercise, unlogged snacks and illness are invisible to it.
- The assistant does not use the forecast. Feeding an uncertain prediction to the LLM would invite it to quote numbers; that can be reconsidered with real-data results.

## Alternatives considered

- **LightGBM or XGBoost:** faster on large data, but another compiled dependency for a few tens of thousands of rows. scikit-learn's histogram gradient boosting uses the same idea.
- **A neural network (LSTM):** more data-hungry, harder to explain, and no better on short horizons in most published comparisons.
- **A physiological model fitted per user:** more interpretable, but needs reliable meal and insulin logs and much more work. The baselines plus a boosted model is the standard first step.
- **Showing the predicted value or a forecast line:** looks precise when the error is 10 to 30 mg/dL and could tempt someone to dose from it.
- **Push notifications for the warning:** the live CGM alerts already push lows and fast falls. A forecast push with this false-alarm rate would train people to ignore alerts.
