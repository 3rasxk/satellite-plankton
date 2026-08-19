# backend

FastAPI service — five endpoints (`/risk-map`, `/timeseries`, `/detect`, `/summary`, `/validation`) + scheduler. Owned by the `backend-api` agent — see `.claude/agents/backend-api.md`.

## Setup

```bash
cd backend
/opt/homebrew/bin/python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in real Supabase keys, never commit .env
uvicorn src.main:app --reload
```
