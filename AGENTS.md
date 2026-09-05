# Repository Guidelines

## Project Structure & Module Organization

This repository monitors harmful algal blooms in the upper Gulf of Thailand.

- `data-pipeline/src/` extracts Sentinel-2, MODIS, and rainfall data through Google Earth Engine; tests are in `data-pipeline/tests/`.
- `detection/src/` computes spectral indices, climatology, thresholds, and rule-based risk; tests are in `detection/tests/`, reports in `detection/reports/`.
- `backend/src/` contains the FastAPI service, database models, scheduler, and routers; tests are in `backend/tests/`.
- `frontend/src/` contains the React/Vite dashboard, components, pages, hooks, and styles; static assets are in `frontend/public/`.
- `data/validation/water_mask_truth.json` is the retained water-mask regression fixture; `docs/` contains design and implementation plans.

Keep the three Python services as separate projects and virtual environments. Preserve the existing namespaced `importlib` bridges between their `src/` directories.

## Build, Test, and Development Commands

Install frontend dependencies with `cd frontend && npm install`. Start both services with `./scripts/dev.sh`; the API uses port 8000 and Vite normally uses port 5173. Separately, run `cd backend && source venv/bin/activate && uvicorn src.main:app --reload` and `cd frontend && npm run dev`.

Run the Python suites with `./venv/bin/python -m pytest tests/ -q` from each of `data-pipeline/`, `detection/`, and `backend/`. Root frontend commands are `npm run build`, `npm run lint`, and `npm run preview`.

## Coding Style & Naming Conventions

Use Python 3.11+, four-space indentation, descriptive `snake_case` names, and module docstrings identifying data sources and limitations. Use React components/pages in `PascalCase`, hooks as `useThing`, and utilities/constants in the existing local style. Run `npm run lint`; no Python formatter or linter is configured.

## Testing Guidelines

Add pytest tests under the relevant service’s `tests/`, using `test_*.py` files and `test_*` functions. Keep tests deterministic: suites mock or bypass live Earth Engine at typed boundaries. Run the frontend Node tests and manually verify dashboard changes against the running API.

## Commit & Pull Request Guidelines

Use short, imperative commit subjects, preferably with a Conventional Commit prefix and scope, such as `feat(frontend): add risk map overlay` or `fix(backend): handle stale cache`. PRs should explain the change, list verification commands, link an issue or plan when applicable, include screenshots for UI changes, and call out config, schema, or validation-data changes.

## Security & Configuration

Never commit `.env` files, Earth Engine credentials, API keys, database URLs, or generated local databases. Copy `.env.example` files for setup. Read `LIMITATIONS.md` before changing user-facing claims: detection and indicative rule-based prediction remain separate.
