# Model card: 30-minute glucose forecast

A model card is a short, standard summary of what a model is for, how it was built and tested, and where it should not be trusted (Mitchell et al., 2019).

## Model details

- **What it does:** predicts CGM glucose 30 minutes ahead, in mg/dL.
- **Type:** gradient boosted decision trees (`HistGradientBoostingRegressor` from scikit-learn), 300 trees, learning rate 0.05, at most 31 leaves per tree, at least 40 samples per leaf. It predicts the change from the current value.
- **Code:** `src/glucobalance/forecast/`. Train with `uv run python -m glucobalance.forecast`.
- **Fallback:** without a trained model file the app uses the linear trend baseline.
- **Version:** Stage 10, October 2026. See ADR 0019.

## Intended use

- Only to decide whether to show a "Likely low soon" warning on the live page: glucose at or above 70 mg/dL now and predicted below 80 mg/dL.
- Only for CGM users, only on fresh data (newest reading at most 15 minutes old) with no gaps in the last 30 minutes.

## Not intended for

- **Dosing.** The forecast never feeds the bolus calculator, the adjustment suggester or the assistant.
- Showing a predicted number or line to the user.
- Glucometer users, or CGM data with 15-minute gaps (such as LibreLinkUp history).
- Diagnosing anything. This is an educational project and not a medical device.

## Inputs

12 features per reading: the glucose value; its change over 5, 15 and 30 minutes; the 30-minute least-squares slope; whether the trend is bending; insulin on board (linear, 4 hours) and rapid insulin in the last hour; carbs on board (linear, 3 hours) and carbs in the last hour; the local time of day as sine and cosine. Details in `forecast/features.py`.

## Training data

Synthetic patients from `forecast/history.py`: 8 patients, 30 days each, one reading every 5 minutes, trained on the first 70% of each patient's days. Each patient has random settings and meal habits, imperfect and sometimes missed boluses, corrections, treated lows, a dawn rise, slow drift and sensor noise. No real person's data was used.

## Evaluation

On the last 30% of the training patients' days, and on 3 patients the model never saw. Full tables in [report.md](report.md). On unseen patients:

| Model | RMSE (mg/dL) | Clarke zone A | Zone A + B | Lows caught at the app's line | Warnings that were right |
|---|---:|---:|---:|---:|---:|
| Last value | 18.8 | 89.7% | 98.7% | 58% | 27% |
| Linear trend | 17.0 | 92.4% | 99.7% | 88% | 26% |
| Gradient boosting | 10.2 | 98.3% | 99.6% | 91% | 40% |

## Limitations and risks

- **Synthetic data flatters the model.** The training patients follow a simple model with clean meal and insulin effects. Published 30-minute forecasts on real CGM data report RMSEs of roughly 18 to 30 mg/dL. Expect real-world errors two to three times those above.
- **Only logged events are known.** Unlogged snacks, exercise, illness, stress, alcohol and site problems are invisible, and are common causes of lows.
- **Many false alarms.** About six in ten warnings are not followed by a low. The warning asks only for a check, which is safe when it is wrong.
- **Missed lows.** About one low in ten is not warned about. The live CGM alerts for lows and fast falls stay in place and do not depend on the forecast.
- **Sensor errors pass through.** A compression low or a sensor in its first day will look like a real fall.
- **Pickle files.** Model files are pickles; only load models you trained yourself.

## Ethical considerations

The app shows a warning, not a value, so an uncertain prediction cannot be mistaken for a reading or used to dose. The forecast is off for anyone without a CGM. Training uses synthetic patients only, in line with keeping real health data on the user's machine.
