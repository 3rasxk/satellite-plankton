"""FastAPI backend for the Gulf of Thailand Algal Bloom Monitor.

Wraps `detection/src`'s `detect()`/`risk_level()` (Phase 2) in HTTP
endpoints. Owned by the `backend-api` agent (.claude/agents/backend-api.md)
-- this package does not implement any detection/prediction logic itself,
it calls Phase 2's public functions and shapes their output as JSON.
"""
