import json
import tempfile
import unittest
from pathlib import Path

from backend.config.backend_config import load_backend_config


class TestBackendConfig(unittest.TestCase):
    def test_load_backend_config_missing_file_raises_when_explicit(self) -> None:
        with self.assertRaises(FileNotFoundError):
            load_backend_config(Path("__definitely_missing_config__.json"))

    def test_load_backend_config_reads_media_root_host_port(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "backend.json"
            path.write_text(
                json.dumps(
                    {
                        "media_root": "C:\\MediaRoot",
                        "host": "127.0.0.1",
                        "port": 5001,
                    }
                ),
                encoding="utf-8",
            )

            cfg = load_backend_config(path)
            self.assertEqual(cfg.media_root, "C:\\MediaRoot")
            self.assertEqual(cfg.host, "127.0.0.1")
            self.assertEqual(cfg.port, 5001)

    def test_load_backend_config_empty_media_root_treated_as_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "backend.json"
            path.write_text(json.dumps({"media_root": "   "}), encoding="utf-8")
            cfg = load_backend_config(path)
            self.assertIsNone(cfg.media_root)

    def test_load_backend_config_rejects_wrong_types(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "backend.json"
            path.write_text(json.dumps({"port": "5000"}), encoding="utf-8")
            with self.assertRaises(TypeError):
                load_backend_config(path)
