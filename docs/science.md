# The science behind OpenRun

Every training rule in OpenRun has a source. This page lists them, grouped by what they drive. The same references sit next to the code that implements them (`backend/app/training/`). Spanish version: [docs/es/ciencia.md](es/ciencia.md).

## What Runna does, and what OpenRun matches

Sources: [the5krunner – Runna](https://the5krunner.com/runna/), [the5krunner – Is Runna AI?](https://the5krunner.com/2026/09/28/is-runna-ai/), [endurance.biz – Runna 2026 updates](https://endurance.biz/2026/industry-news/runna-updates-beginner-and-return-to-running-training-plans/).

| Runna feature | OpenRun |
|---|---|
| 5K / 10K / half / marathon plans, beginner and return-to-running | ✅ 5K, 10K, half, marathon and "base" (general fitness / comeback), 3 levels |
| Onboarding: recent race, days per week, long-run day, current volume, race date, goal | ✅ same inputs, prefilled from your history |
| Personalised paces per session | ✅ Daniels VDOT, 10 zones |
| Race-time prediction that updates | ✅ VDOT, Riegel, Garmin and heart-rate based, with a consensus |
| **Pace Insights** | ✅ post-run analysis per interval; ±0.5 VDOT when sessions consistently come out easier or harder |
| **Not feeling 100 %** | ✅ reduce or active rest for 3–7 days, plus "I've been off N days" |
| Strength, warm-up, mobility | ✅ structured sessions by phase, dynamic warm-up, post-run mobility |
| Push workouts to Garmin | ✅ Garmin Connect workout + calendar |
| Adapt for heat | ✅ temperature + dew point at your usual training hour |
| Conversational coach | ✅ tool-using AI coach on your data (in-app or MCP) |
| HRV / readiness | ✅ HRV, sleep, resting HR, load and a daily check-in (Runna does not use HRV) |

A February 2026 WSJ report cited by the5krunner described physiotherapists seeing injuries associated with app plans; OpenRun therefore caps progression, intensity and volume per session and uses readiness.

## Plan engine

### Paces: VDOT (Daniels & Gilbert)
- O₂ cost: `VO2 = −4.60 + 0.182258·v + 0.000104·v²` (v in m/min); sustainable fraction `0.8 + 0.1894393·e^(−0.012778·t) + 0.2989558·e^(−0.1932605·t)`.
- Zones (*Daniels' Running Formula*, 3rd ed.): E 59–74 % of VDOT, M = predicted marathon pace, T 83–88 %, I 95–100 %, R ~105–110 %.
- Checked in tests: 5K 19:57 ≈ VDOT 50, T ≈ 4:15/km.

### Intensity distribution
- ~80 % low / ~20 % moderate-high, at most 2 quality sessions per week. Seiler & Kjerland 2006; Seiler 2010; Stöggl & Sperlich 2014 (polarised > threshold/volume); Casado et al. 2022 (pyramidal distribution in elite distance runners).
- When the long run has a race-pace block, the second quality session becomes easy + strides.

### Volume per session (Daniels)
- Threshold ≤ 10 % of weekly volume; I ≤ min(10 km, 8 %), 3–5 min repetitions with about equal recovery; R ≤ min(8 km, 5 %), full recovery.
- Long run ≤ 25–33 % of weekly volume (up to 42 % at a marathon peak) with a time cap; at most +2 km per week.

### Progression and load
- ≤ +8 % per week with a recovery week (−25 %) every 4 weeks (every 3 for beginners and runners over 50). Nielsen et al. 2014 (injuries in novices with > 30 % increases over 2 weeks); Gabbett 2016 (ACWR 0.8–1.3).
- ACWR is shown only as a soft guide: its predictive value is debated (Impellizzeri et al. 2020).
- Banister TRIMP (1991); fitness/fatigue as 42- and 7-day exponentially weighted averages.

### Periodisation and taper
- Base (~40 %) → build (~35 %) → specific (~25 %) → taper. Issurin 2010.
- Taper: −40–60 % volume keeping intensity and frequency, ~2 weeks (3 for the marathon, 1 for 5K/10K). Bosquet et al. 2007 (meta-analysis); Mujika & Padilla 2003.

### Realistic goals
- Expected improvement is capped at +0.1–0.3 VDOT per week depending on level. If the goal is out of reach the athlete is told, and training uses current fitness (recalibrated with real results), not the goal.

### Strength and mobility
- Heavy (≥ 80 % 1RM) and explosive/plyometric work twice a week improves running economy by 2–8 % without hurting VO₂max. Blagrove et al. 2018 (systematic review); Balsalobre-Fernández et al. 2016 (meta-analysis); Støren et al. 2008.
- Calf-soleus capacity (the soleus takes ~6–8× body weight per stride): loaded bent-knee calf raises (Dorn et al. 2012). Hip abductor strength and single-leg control relate to injury risk (Willy & Davis 2011). Copenhagen adduction lowers groin injuries (Harøy 2019).
- Same day as quality runs, after them ("hard days hard"), maintenance volume at the peak and none in race week (Beattie 2014).
- No static stretching before running (no injury prevention, can blunt power); a dynamic warm-up does help (Behm 2016). Post-run mobility is short and gentle.

## Readiness

### HRV
- 7-day mean of ln(RMSSD) against a 60-day baseline ± 0.5 SD (smallest worthwhile change). Kiviniemi 2007; Plews et al. 2013; Vesterinen 2016; Javaloyes 2019; Düking 2021 (meta-analysis).
- Amber → −30 % of quality volume keeping intensity. Red → recovery run.
- Own measurement with a chest/arm strap: 3 min lying down, first 30 s discarded, artefact filter (> 20 % change between RR intervals).

### The 0–100 score
- Parts: HRV (35 %, z-score of today and the 7-day mean against the baseline; Garmin's HRV status when the baseline is short), last night's sleep (20 %), resting HR against its 60-day mean (15 %), training load (15 %: form/TSB and ACWR > 1.5) and a two-question check-in (15 %: overall feeling and legs, 1–5).
- Subjective wellness reacts to training load at least as well as objective markers (Saw, Main & Gastin 2016, systematic review), so it weighs next to the physiological parts.
- Missing parts are skipped and the weights renormalised; no data, no score. ≥ 65 green, 45–64 amber, < 45 red. The score can only make the HRV-based status stricter, never looser.
- "I'm ill" in the check-in means rest or very easy running today ("neck check", Eichner 1993).

## Adapting the plan

### Missed sessions
- Easy runs are dropped: making them up piles fatigue on the next days.
- A missed key session (quality or long run) moves to the first day in the next 4 days (3 for long runs, and no later than 6 days after the missed one) whose run is easy or empty and has no hard day before or after. It replaces that easy run. If there is no such day it is dropped: one missed session costs nothing measurable, cramming two hard days does (hard/easy principle; Seiler 2010).
- A run done one or two days late, on a day with nothing planned, completes the missed session.

### Coming back after a break
- Short layoffs barely detrain: under a week VO₂max is practically intact; 2–4 weeks cost ~4–7 %; beyond 8 weeks losses are much larger (Mujika & Padilla 2000; Coyle 1984).
- Following Daniels' break guidance: ≤ 5 days no VDOT change; 6–28 days up to −7 %; 29–56 days down to −14 %; longer, −15 % and a new plan is recommended.
- Return: easy-only days first (after illness, about as many as days ill; after an injury, two more), then reduced volume (−20–40 %) for the rest of one or two weeks.
- After fever or chest symptoms, no running until 24–48 h symptom-free (Eichner 1993; Nieman).

### Post-run analysis and automatic paces
- Garmin records one lap per executed workout step (`wktStepIndex` = step order − 1; repeats share an index), so each interval is compared with its pace range, ±2 % tolerance.
- Verdict (quality sessions only): "easier" when intervals average ≥ 2 % faster without HR above LTHR + 2 % (threshold/marathon; HR lags in I/R and is not used); "harder" when half the intervals are ≥ 3 % slower or HR exceeds LTHR + 5 % at pace.
- VDOT ±0.5 when 2 of the last 3 sessions (21 days) agree; at most once a week and never in the 10 days before the goal race.

### Heat
- Performance drops as heat stress rises (Ely et al. 2007; El Helou et al. 2012, optimum ~4–10 °C; Mantzios et al. 2022).
- Coaches' rule T + dew point (°F) (Hadley): ≤ 100 no change, 101–110 +0.5 %, …, 171–180 +11 %, > 180 no outdoor quality. Effort is kept, not pace. Reverted if the forecast cools.

### Races during a plan
- A = goal race (the plan is periodised towards it). B = tune-up: 3-day mini-taper (quality → easy + strides, the day before a shake-out), reducing volume while keeping intensity (Mujika & Padilla 2003; Bosquet 2007), then ~1 easy day per 3 km raced (Daniels). C = training race: no taper, counts as a quality session. Deleting a race restores the original plan.

## Race strategy

- Even effort, not even pace: on hilly courses the fastest finish keeps metabolic power roughly constant (Minetti et al. 2002, energy cost vs gradient; Townshend et al. 2010).
- Minetti's laboratory costs overstate the effect at race speed (grade-adjusted pace models such as Strava's 2017 GAP show a smaller uphill penalty) and the downhill saving is not fully usable: OpenRun takes 80 % of the uphill cost and 50 % of the downhill saving, with grades clipped to −12…+15 %.
- First 1–2 km slightly conservative (Abbiss & Laursen 2008); the total stays on target.
- Fuelling: 30–60 g carbohydrate per hour for 1–2.5 h efforts and a mouth rinse/gel before 75 min (Jeukendrup 2014; ACSM 2016); carbohydrate loading 7–10 g/kg/day 24–36 h before races over 90 min (Burke 2011).

## Fitness estimates, records and predictions

- %HRR ≈ %VO₂R (Swain 1997): `VO2max ≈ (VO2(v) − 3.5) / %HRR + 3.5` on continuous runs > 20 min at 60–90 % HRR; median of ≥ 3 runs. Indicative only (cardiac drift, hills, heat).
- Records: Garmin's fastest 1 km, mile, 5 km and 10 km splits per activity; otherwise the whole activity (−0.5 %/+5 % of the distance) scaled and marked approximate. Imported files: sliding window over the distance–time series, within 0.1 s of Garmin's splits on real FIT files; GPS-only GPX efforts come out 0.2–1.2 % slower (conservative) and are marked approximate.
- Predictions: Daniels VDOT of the best effort ≥ 1 mile in 90 days; Riegel (1981) `T2 = T1·(D2/D1)^1.06` from the closest distance; Garmin's predictor; HR-based VDOT. Consensus = median. Half and marathon predictions assume enough volume and long runs.
