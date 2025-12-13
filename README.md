# personal-pron-media-manager
A local Windows WebUI for managing personal media libraries. Features responsive layout, album organization, flat video views, and safe file management tools.

## Backend (dev)

- Install: `python3 -m pip install -r backend/requirements.txt`
- Run: `python3 -m backend.api --media-root <ABS_PATH>`
- Thumbnails: `GET /api/thumb?path=<REL_PATH>`
- Video mosaics (requires FFmpeg on PATH): `GET /api/video-mosaic?path=<REL_PATH>`
