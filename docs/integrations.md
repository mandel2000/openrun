# Integrations

## Garmin

Garmin's official API is only for approved companies, so OpenRun uses [python-garminconnect](https://github.com/cyberjunky/python-garminconnect) (mobile SSO login with MFA, auto-refreshed tokens). Tested with a Forerunner 265; any watch that syncs with Garmin Connect and supports structured workouts should work.

- **In**: activities (with laps and detailed series for maps and charts), overnight HRV, sleep, resting HR, Body Battery, Training Readiness, LTHR, VO₂max, Garmin's race predictions and personal records.
- **Out**: structured workouts (steps with pace targets in m/s) uploaded and scheduled in the Garmin Connect calendar; the watch downloads them on its next sync. Only new or changed workouts are pushed.
- **Connect**: *Settings › Garmin*, email and password (the password is not stored, only the session tokens). Each user connects their own account; tokens live in the data folder.
- It is an unofficial API: Garmin can change it without notice. Logging in from a datacenter IP can trigger extra verification; logging in at home and copying the tokens to the server avoids it ([self-hosting.md](self-hosting.md#moving-from-your-computer-to-a-server)).

## Any other watch, app or Strava

- **Upload runs** in *Progress › Activities › Upload activity*: `.fit`, `.gpx`, `.tcx` (also `.gz`) from any device or app. FIT and TCX use the device's distance; GPX distance is computed from the track with light smoothing. Uploaded runs get a map, pace/HR/elevation charts and km splits, match the planned session of that day (or of the previous two days) and feed records, load and predictions.
- **Import history** in *Settings › Import history*: a full Strava export (Strava › Settings › My Account › *Download or Delete Your Account* › *Request Archive*), a full Garmin export, or many files at once. Best efforts (1K, mile, 5K, 10K, half, marathon) are computed from each track; runs already present are skipped. Detailed series are kept for the last 12 months.
- A direct Strava connection is not included: new Strava API applications are limited to a single athlete until Strava reviews them.

## Heart-rate straps (e.g. Amazfit Helio Strap)

Zepp has no public API; the strap broadcasts the standard Bluetooth heart-rate profile (0x180D) with RR intervals.

- **While running**: pair it with your watch as an external HR sensor; its heart rate ends up in the watch's activity.
- **Morning HRV**: *Settings › Connect strap › Measure HRV* (Web Bluetooth, Chrome/Edge). RMSSD is computed on the server.
- **History**: import the Zepp data export (.zip or CSV) in *Settings*.

## Weather

[Open-Meteo](https://open-meteo.com) (no key needed): hourly forecast for the heat adjustment at your usual training hour, the race-day forecast in the race strategy, and terrain elevation for courses without altitude. Location comes from *Settings* or your latest run.

## Maps

[OpenStreetMap](https://www.openstreetmap.org) tiles through [Leaflet](https://leafletjs.com).

## Race calendar

The coach and the Races page can search [Orycron Sport](https://www.orycronsport.com)'s calendar (races around Salamanca, Spain). It has no API: the public listing and event pages are read and cached for 12 h. Races can always be added by hand. Calendars for other regions are a welcome contribution: see `backend/app/integrations/orycron.py` for the shape a provider needs.
