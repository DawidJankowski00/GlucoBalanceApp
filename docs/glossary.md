# Glossary

Plain-language definitions of the diabetes terms used in GlucoBalanceApp. This is not medical advice; settings should be agreed with a diabetes team.

| Term | Meaning |
|---|---|
| **Basal** | Background insulin that covers the body's needs between meals and overnight. Pumps deliver it continuously (rapid-acting insulin); pen users take a daily long-acting dose. |
| **Bolus** | A dose of rapid-acting insulin taken for food (meal bolus) or to bring a high glucose down (correction bolus). |
| **ICR** | Insulin-to-carb ratio: grams of carbohydrate covered by 1 unit of insulin (for example 1:10). Often differs by time of day. |
| **ISF** | Insulin sensitivity factor (also called correction factor): how much 1 unit of insulin lowers glucose, in mg/dL (or mmol/L). |
| **IOB** | Insulin on board: rapid-acting insulin already given that is still working. It is subtracted from a new bolus to avoid stacking doses. It depends on the insulin action time. |
| **CGM** | Continuous glucose monitor: a sensor worn on the body that reports glucose every few minutes, with a trend arrow. |
| **TIR** | Time in range: the percentage of readings within the target range (commonly 70-180 mg/dL, 3.9-10.0 mmol/L). Time below and above range are tracked alongside it. |
| **AGP** | Ambulatory glucose profile: a standard chart that overlays many days of glucose onto one typical 24-hour day, showing median and percentile bands. |

## Related terms

- **Target:** the glucose value a correction aims for.
- **Insulin action time:** how long a bolus keeps working (typically 3-5 hours); used by the IOB model.
- **Hypo / hyper:** glucose that is too low (below 70 mg/dL) or too high.
- **Hypo treatment:** fast-acting carbohydrate taken for a hypo, commonly 15 g (glucose tablets or juice), with a recheck after 15 minutes. Each person's plan comes from their diabetes team.
- **Fingerstick:** a glucose reading from a meter and a drop of blood from the fingertip. CGM users take one to confirm a reading that looks wrong.
- **Correction:** a bolus taken only to bring a high glucose down, not for food.
- **Reading tag:** a label on a meter reading that says when it was taken: fasting, before meal, after meal, bedtime or night. Statistics per time of day use it.
- **Favourite meal:** a named amount of carbs saved for one-tap logging. It records grams only; the dose is always a separate decision.
- **Open Food Facts:** a free, crowd-sourced food database used for the carb search. Its values can be wrong, so the number is always checked before saving.
- **Site rotation:** moving each infusion set or injection to a different spot so the skin and fat underneath can recover. Using one spot too often causes lumps (lipohypertrophy) where insulin is absorbed unevenly.
- **Rest period:** how many days a site should rest before it is suggested again (default 14). A site still resting can be used, but only after every rested site.
- **Blocked site:** a site marked not available, for a while (bruise, sport) or until removed (lump, scar, tattoo). It is never suggested.
- **Property-based test:** a test that states a rule for every input (for example "a blocked site is never suggested") and lets Hypothesis generate hundreds of random inputs to try to break it.

## The bolus formula used in GBA

`carbs / ICR + (current glucose - target) / ISF - IOB`, rounded to the pen or pump step and never negative. Computed by plain, tested Python, never by the LLM.
