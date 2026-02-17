# Stick Drift Bot (Driftline Pro Studio)

Pro-grade stick drift calibration and live compensation for Xbox and PlayStation controllers.

## Modules

- `driftline_pro_gui.py`: flagship visual desktop app (Apple-clean UI)
- `drift_engine.py`: advanced compensation engine
- `drift_bot.py`: hardened CLI flow
- `web/`: browser-based Driftline Web companion
- `tests/test_drift_engine.py`: engine regression tests

## Install

```bash
cd "/Users/johnnymaris/Desktop/stick drift"
python3 -m pip install -r requirements.txt
```

## Run Pro GUI

```bash
./start_driftline_gui.command
```

Or:

```bash
python3 driftline_pro_gui.py
```

## Run CLI Engine

```bash
./start_stick_drift.command
```

Or:

```bash
python3 drift_bot.py
```

## Validate Engine Tests

```bash
python3 -m unittest tests/test_drift_engine.py
```

## Driftline Web (Browser)

The web companion runs in the browser using the Gamepad API and supports:

- Live stick telemetry (raw + compensated)
- Axis mapping wizard (circular stick movement prompts)
- Calibration profile generation
- Local save/load and JSON export/import

### Run locally

```bash
cd "/Users/johnnymaris/Desktop/stick drift/web"
python3 -m http.server 8080
```

Then open:

- `http://localhost:8080`

## Deploy Public Site on Render

This repo includes a Blueprint at `render.yaml` for a static web service.

### 1. Ensure Git remote exists

```bash
cd "/Users/johnnymaris/Desktop/stick drift"
git remote -v
```

If empty, add and push:

```bash
git remote add origin <your-github-repo-url>
git add .
git commit -m "Add Driftline Web + Render blueprint"
git push -u origin main
```

### 2. Create Blueprint service on Render

- In Render Dashboard, choose **New +** -> **Blueprint**
- Select your repo
- Render will detect `render.yaml`
- Approve and deploy

Blueprint summary:

- Service name: `driftline-web`
- Type: static web service
- Publish path: `./web`
- Plan: `free`

## Output Files (Desktop Calibration)

Saved in `profiles/`:

- `*.json`: calibration profiles
- `*_steam_deadzone_hint.txt`: Steam deadzone recommendations
- `*_pro_tuning.json`: advanced tuning presets

## Hard Limitation

Software can dramatically reduce gameplay drift behavior, but it cannot physically repair worn analog stick hardware.
