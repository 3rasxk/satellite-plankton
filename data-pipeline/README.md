# data-pipeline

Sentinel-2 + MODIS extraction via Google Earth Engine. Owned by the `satellite-data` agent — see `.claude/agents/satellite-data.md`.

## Setup

```bash
cd data-pipeline
/opt/homebrew/bin/python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
earthengine authenticate
```

**Do not use the default `python3` on PATH if it resolves to a PlatformIO/Arduino toolchain Python** — it ships an old LibreSSL build and `earthengine authenticate` fails with an SSL certificate error. Check with `which python3`; use the Homebrew or `/usr/bin` system Python instead (confirmed clean on this machine: `/opt/homebrew/bin/python3`, OpenSSL 3.6.3).
