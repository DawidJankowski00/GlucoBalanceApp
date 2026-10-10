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
- **Reminder rule:** how a reminder is repeated: every N days, every day at a time, or a fixed delay after an event (for example 15 minutes after a low).
- **Quiet hours:** a daily window (for example 22:00 to 07:00) when reminders wait until it ends. The recheck after a low ignores it.
- **Snooze / done:** snooze pushes one reminder later by a chosen time; done records that you did it and restarts the countdown.
- **Scheduler (APScheduler):** a library that runs a function on a timer inside the app. Here it checks every minute for reminders that are due. Its job list is kept in the database so a restart does not lose it.
- **Web Push:** the standard way for a website to send a notification to a phone through the browser's push service, even when the site is closed.
- **VAPID keys:** a public and private key pair that proves to the push service that the messages come from this server. Only the public key is shared.
- **Service worker:** a small script the browser keeps running in the background for a site. Ours only shows push notifications.
- **LibreLinkUp:** Abbott's app for family members who follow someone's FreeStyle Libre readings. GBA logs in as such a *follower* to import readings.
- **Follower account:** a separate LibreLinkUp account invited from the Libre app. It is not the account of the FreeStyle Libre app, and GBA should be the only app using it.
- **Trend arrow:** the sensor's estimate of where glucose is heading: ↓ falling fast (more than 2 mg/dL per minute), ↘ falling, → steady, ↗ rising, ↑ rising fast.
- **Stale data:** no new CGM reading for more than 15 minutes. The last value may be out of date, so it is greyed out and nothing should be dosed from it.
- **Polling and backoff:** asking the server for new readings every few minutes, and waiting longer after each failure (and at least 5 minutes after "too many requests") so the account is not blocked.
- **Fernet:** symmetric, authenticated encryption from the `cryptography` package. GBA uses it to store the LibreLinkUp password; the key lives only in an environment variable.
- **Simulator source:** a pretend CGM that replays a simulated day, used for demos and tests.
- **Time in range (TIR) bands:** the share of readings in range, below range (under your low limit) and above range (over your high limit). *Very low* (under 54 mg/dL) and *very high* (over 250 mg/dL) are counted inside below and above.
- **Coefficient of variation (CV):** how much glucose swings, as the standard deviation divided by the mean. 36% or lower is the usual goal for stable glucose.
- **GMI (glucose management indicator):** an estimate of HbA1c from the mean CGM glucose: `3.31 + 0.02392 × mean mg/dL`. It can differ from a lab HbA1c.
- **Percentile:** the value below which a given share of readings fall. The median is the 50th percentile; the 5th and 95th mark the edges of nine in ten readings.
- **Sensor coverage:** the share of 15-minute slots in a period that have a CGM reading. At least 70% over 14 days is needed for reliable statistics.
- **Low episode:** one stretch of low readings. Lows within an hour of each other count as one episode.
- **Lipohypertrophy:** a lump of fatty tissue under the skin from using the same site too often. Insulin is absorbed unevenly there, which can show up as higher glucose after using that site.
- **Notification centre:** the Alerts page in the app. Every reminder lands here first, so nothing is lost if a phone push fails.

## The bolus formula used in GBA

`carbs / ICR + (current glucose - target) / ISF - IOB`, rounded to the pen or pump step and never negative. Computed by plain, tested Python, never by the LLM.
