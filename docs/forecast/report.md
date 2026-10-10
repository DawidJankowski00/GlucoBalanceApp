# Forecast report

Generated on 2026-10-10 by `uv run python -m glucobalance.forecast`.
Do not edit by hand; run the command again instead.

- Data: synthetic patients (glucobalance.forecast.history), 30 days per patient, one reading every 5 minutes.
- Training: the first 70% of the days of 8 patients (48,320 forecasts).
- Tested on the remaining days of those patients, and on 3 patients the model never saw.
- Horizon: 30 minutes. Features: `glucose`, `delta_5`, `delta_15`, `delta_30`, `slope_30`, `bend`, `iob`, `bolus_60`, `cob`, `carbs_60`, `hour_sin`, `hour_cos`.

Clarke zones: A is clinically accurate, B is off but harmless, C would cause an unneeded correction, D misses a low or high that needed treatment, E confuses a low with a high.

### Later days of the training patients (20,704 forecasts)

| Model | RMSE (mg/dL) | MAE (mg/dL) | Zone A | Zone B | Zone C | Zone D | Zone E |
|---|---:|---:|---:|---:|---:|---:|---:|
| last value | 14.1 | 10.1 | 93.3% | 5.8% | 0.0% | 0.9% | 0.0% |
| linear trend | 13.9 | 10.4 | 94.2% | 5.4% | 0.0% | 0.4% | 0.0% |
| gradient boosting | 8.3 | 6.3 | 98.8% | 0.8% | 0.0% | 0.4% | 0.0% |

Lows caught: moments at or above 70 mg/dL that were below 70 mg/dL 30 minutes later.

| Model | Warn below | Lows caught | Warnings that were right | Missed | False alarms |
|---|---:|---:|---:|---:|---:|
| last value | 70 | 0% | n/a | 356 | 0 |
| last value | 80 (app) | 66% | 29% | 121 | 583 |
| last value | 90 | 91% | 18% | 32 | 1523 |
| linear trend | 70 | 48% | 39% | 185 | 269 |
| linear trend | 80 (app) | 86% | 24% | 50 | 951 |
| linear trend | 90 | 99% | 16% | 5 | 1889 |
| gradient boosting | 70 | 34% | 67% | 234 | 59 |
| gradient boosting | 80 (app) | 91% | 39% | 33 | 495 |
| gradient boosting | 90 | 100% | 20% | 1 | 1409 |

### Unseen patients (25,884 forecasts)

| Model | RMSE (mg/dL) | MAE (mg/dL) | Zone A | Zone B | Zone C | Zone D | Zone E |
|---|---:|---:|---:|---:|---:|---:|---:|
| last value | 18.8 | 12.8 | 89.7% | 9.0% | 0.0% | 1.3% | 0.0% |
| linear trend | 17.0 | 12.0 | 92.4% | 7.3% | 0.0% | 0.4% | 0.0% |
| gradient boosting | 10.2 | 7.2 | 98.3% | 1.3% | 0.0% | 0.4% | 0.0% |

Lows caught: moments at or above 70 mg/dL that were below 70 mg/dL 30 minutes later.

| Model | Warn below | Lows caught | Warnings that were right | Missed | False alarms |
|---|---:|---:|---:|---:|---:|
| last value | 70 | 0% | n/a | 485 | 0 |
| last value | 80 (app) | 58% | 27% | 203 | 756 |
| last value | 90 | 87% | 19% | 62 | 1807 |
| linear trend | 70 | 65% | 44% | 172 | 405 |
| linear trend | 80 (app) | 88% | 26% | 57 | 1189 |
| linear trend | 90 | 98% | 16% | 10 | 2422 |
| gradient boosting | 70 | 41% | 73% | 284 | 73 |
| gradient boosting | 80 (app) | 91% | 40% | 44 | 666 |
| gradient boosting | 90 | 98% | 21% | 10 | 1830 |

## Reading these numbers honestly

- The patients are synthetic. Their glucose follows a simple model with clean meal and insulin effects and sensor noise, so it is easier to predict than real data. Published 30-minute forecasts on real CGM data report RMSEs of roughly 18 to 30 mg/dL; expect numbers in that range for a real person, not the ones above.
- The model only knows the carbs and insulin that were logged. Unlogged snacks, exercise, illness and stress are invisible to it.
- Lows are rare, so the low-warning numbers rest on a few hundred events.
- The app never shows the predicted value; it only shows a "likely low soon" warning, and only when the CGM data is fresh. See `docs/forecast/model-card.md`.
