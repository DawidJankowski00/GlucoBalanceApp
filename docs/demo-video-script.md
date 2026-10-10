# Demo video script (about 2 minutes)

A screen recording of the hosted demo, with a voice-over. Record at 1280×800, browser zoom 100%, one tab. Start with the demo freshly restarted so the data is clean.

| Time | On screen | Say |
|---|---|---|
| 0:00 | README top, then the login page | "GlucoBalanceApp is a Type 1 diabetes companion I built in Python. It is not a medical device. Everything you will see is synthetic data, and you can try it yourself without signing up." |
| 0:10 | Press **Pump + CGM**. Home page | "When you sign up you choose two things: pump or pens, and a glucometer or a CGM. The whole app adapts to them. This demo user has a pump and a FreeStyle Libre." |
| 0:20 | **Live** page | "With a CGM, readings arrive every few minutes through LibreLinkUp. There are alerts for lows, highs, fast falls and lost signal, and a 30-minute forecast that says 'likely low soon'. It never shows the predicted number, so nobody doses from a guess." |
| 0:35 | **Reports**, scroll slowly | "Reports show time in range and the ambulatory glucose profile. Below are patterns found by fixed, tested rules: here, highs after breakfast on 12 of 13 days, with the readings that back it up. One click turns this into a PDF for the clinic." |
| 0:55 | **Sites** | "Site rotation suggests the site that has rested longest, skips blocked ones, and the body map shows where you have been." |
| 1:05 | **Assistant**, then **Weekly review** | "The assistant is the part I was most careful with. Every number comes from deterministic Python: the bolus calculator and insulin on board. The language model only gets five read-only tools, and every dose number in its reply is checked against what the tools returned. If it invents a number, the reply is blocked. Setting changes are capped at 10% and only happen when you press Accept." |
| 1:25 | Terminal: `uv run python -m glucobalance.evals --provider reckless` summary | "I test that with 56 scenarios, including prompt injection. Even a model that invents a dose every turn gets nothing past the check." |
| 1:40 | Log out, press **Pens + glucometer**, open **Today** | "The pens and glucometer user gets finger-stick readings with tags, long-acting dose reminders and separate rotation for each insulin." |
| 1:50 | **Settings > Export or delete my data** | "Your data is yours: download everything as JSON or CSV, or delete the account and every row it owns." |
| 1:58 | GitHub repo: green CI, coverage badge, ADR list | "Typed, tested, with a decision record for every choice. Links are below." |

## Recording checklist

- Hide bookmarks and notifications; use a clean browser profile.
- Keep the mouse still while talking; move it only to click.
- Export at 1080p, add captions (most people watch muted), and keep it under 2:15.
- Upload unlisted first, watch it once on a phone, then make it public and link it from the README and the write-up.
