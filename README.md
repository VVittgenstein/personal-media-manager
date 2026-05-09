# personal-media-manager

A local Windows WebUI for browsing, searching, and safely organizing personal media libraries.

## Technical highlights

- Python backend using the standard library HTTP server plus Pillow/FFmpeg integrations for thumbnails, album covers, and video mosaics.
- Vanilla JavaScript single-page UI for albums, scattered files, videos, search, overlays, and local file operations.
- MediaRoot sandboxing, two-step confirmation, HMAC-backed confirm tokens, soft delete/archive operations, and JSONL operation logging.
- Designed for local-first use: no cloud account, no remote upload, and no external media indexing service.

## Backend (dev)

- Install: `python3 -m pip install -r backend/requirements.txt`
- Run (args): `python3 -m backend.api --media-root <ABS_PATH>`
- Run (config): edit `config/backend.json` then `python3 -m backend.api`
- Windows (one-click): set `media_root` in `config/backend.json` then double-click `start.bat` (or `start.bat "D:\\Media"`). It will create `.venv` and install Python deps on first run.
- Thumbnails: `GET /api/thumb?path=<REL_PATH>`
- Original images: `GET /api/image?path=<REL_PATH>`
- Video mosaics (requires FFmpeg on PATH): `GET /api/video-mosaic?path=<REL_PATH>`
