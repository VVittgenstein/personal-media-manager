# personal-pron-media-manager
A local Windows WebUI for managing personal media libraries. Features responsive layout, album organization, flat video views, and safe file management tools.

## Backend (dev)

- Install: `python3 -m pip install -r backend/requirements.txt`
- Run (args): `python3 -m backend.api --media-root <ABS_PATH>`
- Run (config): edit `config/backend.json` then `python3 -m backend.api`
- Windows (one-click): set `media_root` in `config/backend.json` then double-click `start.bat` (or `start.bat "D:\\Media"`)
- Thumbnails: `GET /api/thumb?path=<REL_PATH>`
- Video mosaics (requires FFmpeg on PATH): `GET /api/video-mosaic?path=<REL_PATH>`
