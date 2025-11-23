# Repository Guidelines

## Project Structure & Module Organization
- Core processing scripts live at the repo root (`oil_mqtt_transform.py`, `oil_recalc.py`, `oil_analysis.py`, `oil_cost_analysis.py`, `notifier.py`) and assume `config/config.yaml` plus the SQLite file in `data/`.
- `web/` hosts the Flask + Socket.IO dashboard (`web_app.py`, `templates/`, `static/`, `mqtt_viewer.py`, `utils/`) and expects the same config/database paths.
- `scripts/` holds maintenance utilities (cost imports, HDD updates, refill analysis); run them from the repo root so relative imports resolve.
- `utils/` contains shared helpers like `config_loader.py`; re-use these instead of re-parsing YAML.
- `config/` carries the real `config.yaml`, an `example_config.yaml` template, and logrotate settings; avoid committing secrets.
- `assets/` and `static/` store documentation and UI assets. `data/` and `logs/` are runtime artifacts—keep them out of commits.

## Build, Test, and Development Commands
- Create/refresh a virtualenv: `python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`.
- Run the dashboard locally: `python web/web_app.py` (uses `config/config.yaml` and SQLite DB).
- Connectivity checks: `python test_connectivity.py`; notification check: `python test_gotify.py`.
- Ad-hoc analysis or maintenance: `python scripts/update_hdd_data.py` or `python scripts/refill_cost_analysis.py` as needed.
- Service management (on target host): `sudo systemctl status|start|stop KeroTrack-Web KeroTrack-MQTT`.

## Coding Style & Naming Conventions
- Follow PEP8 with 4-space indentation; favor type hints where practical (see `utils/config_loader.py`).
- Prefer f-strings, explicit logging/print statements, and small focused functions.
- Keep filenames descriptive and snake_case; align module names with their primary responsibility.
- Centralize configuration access through `utils/config_loader.py` and avoid hard-coded paths.

## Testing Guidelines
- Use the virtualenv above; tests assume `config/config.yaml` exists but you can point to `example_config.yaml` for dry runs.
- For notification checks, use non-production Apprise URLs to avoid noisy alerts.
- Add unit-style tests alongside scripts (e.g., `test_*.py` at repo root) and keep them idempotent against the SQLite fixture data.

## Commit & Pull Request Guidelines
- Match existing history: short, sentence-case summaries that describe the change (e.g., “Add refill cost delta to analysis view”); prefer the imperative mood.
- In PRs, include a brief description, test commands run, and any config prerequisites. Link issues when applicable.
- For UI or dashboard changes, attach before/after screenshots from `web/`.
- Never commit secrets, generated DBs in `data/`, or local logs. Update `example_config.yaml` when adding new config keys.

## Security & Configuration Tips
- Redact MQTT credentials, Apprise tokens, and DB paths in commits and screenshots.
- Default to using `example_config.yaml` in docs/tests; keep `config.yaml` machine-specific.
- Preserve service unit names (`KeroTrack-Web`, `KeroTrack-MQTT`) and keep `update_kerotrack.sh`/`KeroTrack_Setup.sh` executable when modifying deployment scripts.
