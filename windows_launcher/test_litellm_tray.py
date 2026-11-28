"""Tests for the launcher's config file handling. Run with: python -m unittest discover windows_launcher"""

from __future__ import annotations

import http.server
import json
import tempfile
import threading
import unittest
from pathlib import Path

import litellm_tray as tray


class ModelsHandler(http.server.BaseHTTPRequestHandler):
    seen: list[str] = []

    def do_GET(self) -> None:
        ModelsHandler.seen.append(self.headers.get("Authorization", ""))
        payload = json.dumps({"data": [{"id": "qwen3-14b"}, {"id": "gemma-3n-e4b"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args: object) -> None:
        pass


class OpenAICompatibleTest(unittest.TestCase):
    def setUp(self) -> None:
        ModelsHandler.seen = []
        self.server = http.server.HTTPServer(("127.0.0.1", 0), ModelsHandler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def test_local_fetch_lists_models_and_sends_a_placeholder_key(self) -> None:
        models = tray.fetch_provider_models(tray.LOCAL_PROVIDER, "", f"http://127.0.0.1:{self.port}/v1")
        self.assertEqual(models, ("openai/qwen3-14b", "openai/gemma-3n-e4b"))
        self.assertEqual(ModelsHandler.seen, [f"Bearer {tray.NO_KEY_PLACEHOLDER}"])


class BaseUrlTest(unittest.TestCase):
    def test_adds_the_v1_suffix_once(self) -> None:
        self.assertEqual(
            tray.normalize_openai_compatible_base("http://127.0.0.1:1234/"),
            "http://127.0.0.1:1234/v1",
        )
        self.assertEqual(
            tray.normalize_openai_compatible_base("http://192.168.1.5:8000/v1"),
            "http://192.168.1.5:8000/v1",
        )
        self.assertEqual(
            tray.normalize_openai_compatible_base("http://localhost:11434/v1/chat/completions"),
            "http://localhost:11434/v1",
        )

    def test_rejects_a_value_that_is_not_a_url(self) -> None:
        for value in ("", "localhost:1234", "127.0.0.1:1234"):
            with self.assertRaises(ValueError):
                tray.normalize_openai_compatible_base(value)


class LocalDeploymentTest(unittest.TestCase):
    def test_builds_an_openai_route_with_the_placeholder_key(self) -> None:
        row = tray.local_deployment("local-qwen", "qwen3-14b", "", "http://127.0.0.1:1234")
        self.assertEqual(
            row,
            tray.Deployment("local-qwen", "openai/qwen3-14b", tray.NO_KEY_PLACEHOLDER, "http://127.0.0.1:1234/v1"),
        )

    def test_keeps_a_real_key_and_an_already_prefixed_model(self) -> None:
        row = tray.local_deployment("vllm", "openai/llama-3.3", "sk-real", "http://192.168.1.9:8000/v1")
        self.assertEqual(
            row,
            tray.Deployment("vllm", "openai/llama-3.3", "sk-real", "http://192.168.1.9:8000/v1"),
        )

    def test_rejects_a_base_url_without_a_scheme(self) -> None:
        with self.assertRaises(ValueError):
            tray.local_deployment("local", "model", "", "127.0.0.1:1234")


class ApiBaseRoundTripTest(unittest.TestCase):
    def setUp(self) -> None:
        self._folder = tempfile.TemporaryDirectory()
        self.path = Path(self._folder.name) / "litellm.config"

    def tearDown(self) -> None:
        self._folder.cleanup()

    def test_api_base_survives_a_write_and_read(self) -> None:
        row = tray.Deployment("local", "openai/qwen3-14b", tray.NO_KEY_PLACEHOLDER, "http://127.0.0.1:1234/v1")
        tray.write_deployments(self.path, (row,))
        self.assertEqual(tray.read_deployments(self.path), (row,))

    def test_a_cloud_row_omits_the_api_base_key(self) -> None:
        tray.write_deployments(self.path, (tray.Deployment("flash", "gemini/gemini-3.5-flash-lite", "k"),))
        entry = tray.load_yaml(self.path)["model_list"][0]
        self.assertNotIn("api_base", entry["litellm_params"])


class ConfigFileTest(unittest.TestCase):
    def setUp(self) -> None:
        self._folder = tempfile.TemporaryDirectory()
        self.base = Path(self._folder.name)

    def tearDown(self) -> None:
        self._folder.cleanup()

    def test_creates_config_with_defaults_when_missing(self) -> None:
        created = tray.ensure_config(self.base)
        self.assertEqual(created.name, "litellm.config")
        self.assertTrue(created.is_file())
        settings = tray.Settings.load(created)
        self.assertEqual((settings.host, settings.port, settings.master_key), ("127.0.0.1", 4000, ""))
        self.assertEqual(tray.read_deployments(created), ())

    def test_existing_config_is_left_alone(self) -> None:
        first = tray.ensure_config(self.base)
        tray.Settings(host="0.0.0.0", port=4321, master_key="sk-abc").save(first)
        self.base.joinpath("litellm.config.bak").write_text("unused", encoding="utf-8")

        settings = tray.Settings.load(tray.ensure_config(self.base))
        self.assertEqual((settings.host, settings.port, settings.master_key), ("0.0.0.0", 4321, "sk-abc"))

    def test_saving_settings_keeps_the_model_list(self) -> None:
        path = tray.ensure_config(self.base)
        tray.write_deployments(path, (tray.Deployment("m1", "gemini/gemma-4", "key-1"),))

        tray.Settings(host="127.0.0.1", port=4000, master_key="sk-x").save(path)

        self.assertEqual(tray.read_deployments(path), (tray.Deployment("m1", "gemini/gemma-4", "key-1"),))

    def test_migrates_legacy_config_env_and_stored_settings(self) -> None:
        (self.base / "config.yaml").write_text(
            "model_list:\n"
            "  - model_name: flash\n"
            "    litellm_params:\n"
            "      model: gemini/gemini-3.5-flash-lite\n"
            "      api_key: os.environ/GEMINI_API_KEY_1\n"
            "  - model_name: literal\n"
            "    litellm_params:\n"
            "      model: openai/gpt-5.1\n"
            "      api_key: sk-provider-plain\n"
            "      api_base: http://192.168.1.9:8000/v1\n"
            "router_settings:\n"
            "  num_retries: 3\n"
            "litellm_settings:\n"
            "  drop_params: true\n",
            encoding="utf-8",
        )
        (self.base / "litellm-windows.yaml").write_text(
            "host: 0.0.0.0\nport: 4100\nmaster_key: sk-master\n", encoding="utf-8"
        )
        (self.base / ".env").write_text("GEMINI_API_KEY_1=real-key-1\n", encoding="utf-8")

        settings = tray.Settings.load(tray.ensure_config(self.base))

        self.assertEqual((settings.host, settings.port, settings.master_key), ("0.0.0.0", 4100, "sk-master"))
        self.assertEqual(
            tray.read_deployments(self.base / "litellm.config"),
            (
                tray.Deployment("flash", "gemini/gemini-3.5-flash-lite", "real-key-1"),
                tray.Deployment("literal", "openai/gpt-5.1", "sk-provider-plain", "http://192.168.1.9:8000/v1"),
            ),
        )
        migrated = tray.load_yaml(self.base / "litellm.config")
        self.assertEqual(migrated["router_settings"], {"num_retries": 3})
        self.assertEqual(migrated["litellm_settings"], {"drop_params": True})

    def test_missing_env_value_keeps_the_reference(self) -> None:
        self.assertEqual(
            tray.resolve_api_key("os.environ/GEMINI_API_KEY_9", {"GEMINI_API_KEY_1": "used"}),
            "os.environ/GEMINI_API_KEY_9",
        )
        self.assertEqual(tray.resolve_api_key("sk-plain", {}), "sk-plain")

    def test_headless_warning_is_appended_without_losing_the_log(self) -> None:
        log_path = self.base / "litellm.log"
        log_path.write_text("earlier line\n", encoding="utf-8")

        tray.append_log_line(log_path, tray.unauthenticated_warning("0.0.0.0", "ja"))

        lines = log_path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(lines[0], "earlier line")
        self.assertIn("ネットワーク外に公開", lines[1])
        self.assertEqual(len(lines), 2)

    def test_warning_names_the_bind_and_never_blocks_start(self) -> None:
        loopback = tray.unauthenticated_warning("127.0.0.1", "ja")
        wide = tray.unauthenticated_warning("0.0.0.0", "ja")
        for message in (loopback, wide):
            self.assertIn("マスターキー", message)
            self.assertIn("ネットワーク外に公開", message)
        self.assertIn("LAN", wide)
        self.assertNotIn("LAN", loopback)


if __name__ == "__main__":
    unittest.main()
