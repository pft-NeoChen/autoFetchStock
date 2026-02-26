# Repository Guidelines

## Project Structure & Module Organization
- `src/`: Application code.
  - `fetcher/`: TWSE/Shioaji data ingestion and API adapters.
  - `processor/`: Data cleaning, MA calculations, and K-line transformations.
  - `renderer/`: Dash/Plotly visualization components and callbacks.
  - `scheduler/`: APScheduler jobs for market-hour polling.
  - `storage/`: JSON persistence, atomic writes, and file I/O helpers.
  - `app/`: Dash app factory plus assets for UI styling.
- `tests/`: Pytest suites mirroring the `src` layout with unit and integration coverage.
- `scripts/`: Utility entry points (e.g., `scripts/test_shioaji_login.py` for API sanity checks).
- `specs/`: Functional/architecture notes and history for reference.
- `config.env.example`: Copy to `config.env` for local secrets; `cert/` holds Shioaji certificates (gitignored).

## Build, Test, and Development Commands
- Create env and install deps (Python 3.10+): `python -m venv venv && source venv/bin/activate && pip install -r requirements.txt`.
- Run the app in simulation mode: `python -m src.main`.
- Run the app against production feed: `python -m src.main --production` (requires populated `config.env` and valid cert in `cert/`).
- Quick Shioaji connectivity check: `python scripts/test_shioaji_login.py`.
- Test suite: `pytest` (uses markers `unit`, `integration`, `e2e`, `slow`).
- Coverage report: `pytest --cov=src --cov-report=term-missing`; target ≥80% (configured in `pyproject.toml`).

## Coding Style & Naming Conventions
- Follow PEP 8 with 4-space indentation and descriptive snake_case for modules, functions, and variables.
- Prefer explicit type hints for public functions and data models.
- Keep modules small and focused; match test modules to `src/<package>/` counterparts.
- Configuration keys live in `config.env`; keep secrets out of source control.

## Testing Guidelines
- Place unit tests under `tests/<module>/test_*.py`; mirror filenames from `src`.
- Use Pytest markers to scope runs, e.g., `pytest -m unit` for fast checks or `-m "not slow"` for CI-friendly runs.
- Integration tests may require `config.env` and mockable network boundaries; gate external calls behind fixtures when possible.
- Add regression tests for every bug fix touching fetchers, schedulers, or renderers.

## Commit & Pull Request Guidelines
- Commit messages follow `<type>: <summary>`; common types observed: `feat`, `fix`, `docs`, `refactor`, `chore`, `test`.
- Keep summaries imperative and ≤72 chars; add scope when helpful, e.g., `fix(chart): adjust big-order volume calc`.
- PRs should include: purpose/impact summary, linked issue ID, screenshots for UI changes, and test evidence (`pytest` or coverage output).
- Avoid committing secrets; verify `config.env` and `cert/` stay untracked.

## Security & Configuration Tips
- Never store real credentials in the repo; rely on `config.env` and keep `cert/` locally.
- For production runs, confirm certificate paths and person ID in `config.env` before enabling `--production`.
- Logs under `logs/` may contain session info; rotate or redact before sharing.

## Agent-Specific Instructions
- 與協作者對話時預設使用中文回應與說明，保持專業、精簡且以本專案脈絡為主。
