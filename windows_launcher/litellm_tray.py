"""Windows 用の LiteLLM Proxy ランチャー。

設定 GUI とシステムトレイを提供し、`litellm.config` 1 枚に設定を集約して Proxy を起動する。
exe には Proxy 本体を同梱しない。実行フォルダに `.venv` が無ければこれを作り、
PyPI から `litellm[proxy]` をインストールして、そこへ起動する。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import tkinter as tk
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from tkinter import messagebox, ttk
from types import MappingProxyType
from typing import Final
from urllib import request
from urllib.parse import urlparse

from i18n import LANGUAGES, DEFAULT_LANGUAGE, t

HOST_CHOICES: Final = ("127.0.0.1", "0.0.0.0")
CONFIG_NAME: Final = "litellm.config"
LEGACY_CONFIG_NAME: Final = "config.yaml"
LEGACY_SETTINGS_NAME: Final = "litellm-windows.yaml"
LOG_NAME: Final = "litellm.log"
MASTER_KEY_ENV_VAR: Final = "LITELLM_MASTER_KEY"
WEAK_MASTER_KEY_ENV_VAR: Final = "LITELLM_DANGEROUSLY_PERMIT_WEAK_OR_UNSET_MASTER_KEY"
DEFAULT_SETTINGS: Final = MappingProxyType({"host": "127.0.0.1", "port": 4000, "master_key": "", "language": DEFAULT_LANGUAGE})
STARTUP_KEY: Final = r"Software\Microsoft\Windows\CurrentVersion\Run"
STARTUP_VALUE: Final = "LiteLLMProxyTray"

LOCAL_PROVIDER: Final = "local"
PROVIDERS: Final = ("gemini", "openai", "anthropic", LOCAL_PROVIDER, "other")
NO_KEY_PLACEHOLDER: Final = "not-needed"


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def venv_dir() -> Path:
    return app_dir() / ".venv"


def venv_python() -> Path:
    if os.name == "nt":
        return venv_dir() / "Scripts" / "python.exe"
    return venv_dir() / "bin" / "python"


def ensure_venv() -> Path:
    python = venv_python()
    marker = venv_dir() / ".litellm-ready"
    if marker.is_file() and python.is_file():
        return python
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    if not python.is_file():
        subprocess.run(
            [sys.executable, "-m", "venv", str(venv_dir())],
            check=True,
            creationflags=flags,
        )
    subprocess.run(
        [str(python), "-m", "pip", "install", "--upgrade", "pip"],
        check=True,
        creationflags=flags,
    )
    subprocess.run(
        [str(python), "-m", "pip", "install", "litellm[proxy]"],
        check=True,
        creationflags=flags,
    )
    marker.write_text("ok", encoding="utf-8")
    return python


def self_command() -> tuple[str, ...]:
    return (str(ensure_venv()),)


def venv_error_message(error: BaseException, lang: str) -> str:
    if isinstance(error, subprocess.CalledProcessError):
        return t("venv_build_failed", lang, code=error.returncode)
    if isinstance(error, OSError):
        return t("venv_build_failed_generic", lang, error=error)
    return t("venv_build_failed_generic", lang, error=f"{type(error).__name__}: {error}")


def ensure_config(base: Path) -> Path:
    path = base / CONFIG_NAME
    if not path.is_file():
        dump_yaml(path, initial_config(base))
    return path


def initial_config(base: Path) -> dict[str, object]:
    return {**DEFAULT_SETTINGS, **legacy_config(base)}


def legacy_config(base: Path) -> dict[str, object]:
    legacy = base / LEGACY_CONFIG_NAME
    if not legacy.is_file():
        return {}
    raw: Final = load_yaml(legacy)
    stored: Final = load_yaml(base / LEGACY_SETTINGS_NAME)
    env_values: Final = load_dotenv_files((base,))
    sections: Final = {name: raw[name] for name in ("router_settings", "litellm_settings") if name in raw}
    return {
        "host": str(stored.get("host", "127.0.0.1")),
        "port": int(stored.get("port", 4000)),
        "master_key": str(stored.get("master_key", "")),
        "model_list": [
            deployment_entry(resolve_api_key_in(row, env_values)) for row in read_deployments(legacy)
        ],
        **sections,
    }


def resolve_api_key(value: str, env_values: Mapping[str, str]) -> str:
    name: Final = value.removeprefix("os.environ/")
    if name == value:
        return value
    return env_values.get(name, value)


def local_deployment(model_name: str, provider_model: str, api_key: str, base_url: str, lang: str = DEFAULT_LANGUAGE) -> Deployment:
    model = provider_model if provider_model.startswith("openai/") else f"openai/{provider_model}"
    return Deployment(model_name, model, api_key or NO_KEY_PLACEHOLDER, normalize_openai_compatible_base(base_url, lang))


def resolve_api_key_in(row: Deployment, env_values: Mapping[str, str]) -> Deployment:
    return Deployment(
        row.model_name,
        row.model,
        resolve_api_key(row.api_key, env_values),
        row.api_base,
    )


def load_yaml(path: Path) -> dict[str, object]:
    import yaml

    if not path.is_file():
        return {}
    return dict(yaml.safe_load(path.read_text(encoding="utf-8")) or {})


def dump_yaml(path: Path, data: dict[str, object]) -> None:
    import yaml

    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


@dataclass(slots=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 4000
    master_key: str = ""
    language: str = DEFAULT_LANGUAGE

    @staticmethod
    def load(config_path: Path) -> "Settings":
        raw: Final = load_yaml(config_path)
        lang: Final = str(raw.get("language", DEFAULT_LANGUAGE))
        if lang not in LANGUAGES:
            lang = DEFAULT_LANGUAGE
        return Settings(
            host=str(raw.get("host", "127.0.0.1")),
            port=int(raw.get("port", 4000)),
            master_key=str(raw.get("master_key", "")),
            language=lang,
        )

    def save(self, config_path: Path) -> None:
        data = load_yaml(config_path)
        data.update({"host": self.host, "port": self.port, "master_key": self.master_key, "language": self.language})
        dump_yaml(config_path, data)


@dataclass(slots=True)
class Deployment:
    model_name: str
    model: str
    api_key: str
    api_base: str = ""


def read_deployments(config_path: Path) -> tuple[Deployment, ...]:
    entries = load_yaml(config_path).get("model_list") or []
    rows: list[Deployment] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        params = entry.get("litellm_params") or {}
        if not isinstance(params, dict):
            params = {}
        rows.append(
            Deployment(
                str(entry.get("model_name", "")),
                str(params.get("model", "")),
                str(params.get("api_key", "")),
                str(params.get("api_base", "")),
            )
        )
    return tuple(rows)


def write_deployments(config_path: Path, rows: tuple[Deployment, ...]) -> None:
    data = load_yaml(config_path)
    data["model_list"] = [deployment_entry(row) for row in rows]
    dump_yaml(config_path, data)


def deployment_entry(row: Deployment) -> dict[str, object]:
    params: dict[str, object] = {"model": row.model, "api_key": row.api_key}
    if row.api_base:
        params["api_base"] = row.api_base
    return {"model_name": row.model_name, "litellm_params": params}


def autostart_enabled() -> bool:
    if os.name != "nt":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_KEY) as key:
            winreg.QueryValueEx(key, STARTUP_VALUE)
        return True
    except OSError:
        return False


def set_autostart(enable: bool) -> None:
    if os.name != "nt":
        return
    import winreg

    command = " ".join(f'"{part}"' for part in self_command()) + " --headless"
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, STARTUP_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enable:
            winreg.SetValueEx(key, STARTUP_VALUE, 0, winreg.REG_SZ, command)
        else:
            try:
                winreg.DeleteValue(key, STARTUP_VALUE)
            except OSError:
                pass


def append_log_line(log_path: Path, message: str) -> None:
    with log_path.open("a", encoding="utf-8") as log_file:
        log_file.write(message + "\n")


def health_ok(port: int) -> bool:
    try:
        with request.urlopen(f"http://127.0.0.1:{port}/health/liveness", timeout=2) as response:
            return response.status == 200
    except Exception:
        return False


GEMINI_MODELS_URL: Final = "https://generativelanguage.googleapis.com/v1beta/models"
OPENAI_MODELS_URL: Final = "https://api.openai.com/v1/models"


def normalize_openai_compatible_base(value: str, lang: str = DEFAULT_LANGUAGE) -> str:
    parsed = urlparse(value.strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(t("error_url_scheme", lang))
    segments = parsed.path.split("/")
    if "v1" in segments:
        path = "/".join(segments[: segments.index("v1") + 1])
    else:
        path = parsed.path.rstrip("/") + "/v1"
    return f"{parsed.scheme}://{parsed.netloc}{path}"


def unauthenticated_warning(host: str, lang: str = DEFAULT_LANGUAGE) -> str:
    reach: Final = "reach_wide" if host == "0.0.0.0" else "reach_loopback"
    return t("unauth_warning", lang, host=host, reach=t(reach, lang))


def load_dotenv_files(search_dirs: tuple[Path, ...]) -> dict[str, str]:
    values: dict[str, str] = {}
    for directory in search_dirs:
        env_file = directory / ".env"
        if not env_file.is_file():
            continue
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, _, value = line.partition("=")
            values.setdefault(name.strip(), value.strip().strip("'\""))
    return values


def fetch_provider_models(provider: str, api_key: str, base_url: str = "", lang: str = DEFAULT_LANGUAGE) -> tuple[str, ...]:
    if provider == "gemini":
        url = f"{GEMINI_MODELS_URL}?key={api_key}&pageSize=200"
        with request.urlopen(url, timeout=30) as response:
            data = json.loads(response.read())
        return tuple(
            f"gemini/{m['name'].removeprefix('models/')}"
            for m in data.get("models", [])
            if "generateContent" in " ".join(m.get("supportedGenerationMethods", []))
        )
    if provider in ("openai", LOCAL_PROVIDER):
        base = normalize_openai_compatible_base(base_url, lang) if provider == LOCAL_PROVIDER else OPENAI_MODELS_URL
        models_url = base if base.endswith("/models") else f"{base}/models"
        req = request.Request(models_url, headers={"Authorization": f"Bearer {api_key or NO_KEY_PLACEHOLDER}"})
        with request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read())
        return tuple(f"openai/{m['id']}" for m in data.get("data", []))
    if provider == "anthropic":
        raise ValueError(t("anthropic_unsupported", lang))
    raise ValueError(t("fetch_unsupported", lang))


def provider_display_name(provider: str, lang: str) -> str:
    if provider == LOCAL_PROVIDER:
        return "OpenAI-compatible local" if lang == "en" else "openai 互換ローカル"
    if provider == "other":
        return "Other" if lang == "en" else "その他"
    return provider


class ProxyProcess:
    def __init__(self) -> None:
        self.handle: subprocess.Popen[bytes] | None = None

    def running(self) -> bool:
        return self.handle is not None and self.handle.poll() is None

    def pid(self) -> int | None:
        return self.handle.pid if self.handle is not None else None

    def start(self, config: Path, settings: Settings, log_path: Path) -> None:
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        env["LITELLM_LOCAL_MODEL_COST_MAP"] = env.get("LITELLM_LOCAL_MODEL_COST_MAP", "True")
        if settings.master_key:
            env[MASTER_KEY_ENV_VAR] = settings.master_key
        else:
            env[WEAK_MASTER_KEY_ENV_VAR] = "true"
        env.update(load_dotenv_files((app_dir(),)))
        try:
            python = self_command()
        except (subprocess.CalledProcessError, OSError) as error:
            raise RuntimeError(venv_error_message(error, settings.language)) from error
        command = [
            *python,
            "-m", "litellm.proxy.proxy_cli",
            "--config",
            str(config),
            "--host",
            settings.host,
            "--port",
            str(settings.port),
        ]
        creation = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        with log_path.open("ab") as log_file:
            self.handle = subprocess.Popen(
                command,
                cwd=str(config.parent if config.parent != app_dir() else app_dir()),
                env=env,
                stdout=log_file,
                stderr=log_file,
                creationflags=creation,
            )

    def stop(self) -> None:
        if self.handle is None:
            return
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(self.handle.pid), "/T", "/F"],
                check=False,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        else:
            self.handle.terminate()
        self.handle = None


class Launcher:
    def __init__(self) -> None:
        self.dir: Final = app_dir()
        self.log_path: Final = self.dir / LOG_NAME
        self.config_path: Final = ensure_config(self.dir)
        settings: Final = Settings.load(self.config_path)
        self.lang: Final = settings.language
        self.process = ProxyProcess()
        self.tray = None
        self.root = tk.Tk()
        self.root.title(t("app_title", self.lang))
        self.root.protocol("WM_DELETE_WINDOW", self.hide)
        self.host = tk.StringVar(value=settings.host)
        self.port = tk.StringVar(value=str(settings.port))
        self.master_key = tk.StringVar(value=settings.master_key)
        self.language = tk.StringVar(value=settings.language)
        self.autostart = tk.BooleanVar(value=autostart_enabled())
        self.status = tk.StringVar(value=t("status_stopped", self.lang))
        self._build_form()
        self._refresh_rows()

    def _build_form(self) -> None:
        lang = self.lang
        frame = ttk.Frame(self.root, padding=12)
        frame.grid(sticky="nsew")

        grid = ttk.Frame(frame)
        grid.grid(row=0, column=0, sticky="w")
        ttk.Label(grid, text=t("label_host", lang)).grid(row=0, column=0, sticky="w")
        ttk.Combobox(grid, textvariable=self.host, values=HOST_CHOICES, width=14).grid(row=0, column=1, sticky="w")
        ttk.Label(grid, text=t("label_port", lang)).grid(row=1, column=0, sticky="w")
        ttk.Entry(grid, textvariable=self.port, width=16).grid(row=1, column=1, sticky="w")
        ttk.Label(grid, text=t("label_master_key", lang)).grid(row=2, column=0, sticky="w")
        ttk.Entry(grid, textvariable=self.master_key, width=34, show="*").grid(row=2, column=1, sticky="w")
        ttk.Label(grid, text=t("language_label", lang)).grid(row=3, column=0, sticky="w")
        lang_box = ttk.Combobox(grid, textvariable=self.language, values=LANGUAGES, width=14, state="readonly")
        lang_box.grid(row=3, column=1, sticky="w")
        lang_box.bind("<<ComboboxSelected>>", lambda _event: self._on_language_changed())
        ttk.Checkbutton(grid, text=t("autostart_check", lang), variable=self.autostart).grid(
            row=4, column=0, columnspan=2, sticky="w"
        )

        self.config_label = ttk.Label(frame, text=t("config_label", lang, path=self.config_path))
        self.config_label.grid(row=1, column=0, sticky="w", pady=(8, 0))
        picker = ttk.Frame(frame)
        picker.grid(row=2, column=0, sticky="w")
        ttk.Button(picker, text=t("open_config", lang), command=self._open_config).pack(side="left", padx=6)

        self.tree = ttk.Treeview(
            frame, columns=("model_name", "model", "api_key", "api_base"), show="headings", height=7
        )
        for column, title_key, width in (
            ("model_name", "col_model_name", 160),
            ("model", "col_model", 220),
            ("api_key", "col_api_key", 200),
            ("api_base", "col_api_base", 220),
        ):
            self.tree.heading(column, text=t(title_key, lang))
            self.tree.column(column, width=width)
        self.tree.grid(row=3, column=0, sticky="nsew", pady=(8, 0))

        rows = ttk.Frame(frame)
        rows.grid(row=4, column=0, sticky="w", pady=(4, 0))
        ttk.Button(rows, text=t("add_model", lang), command=self._add_row).pack(side="left")
        ttk.Button(rows, text=t("delete_selected", lang), command=self._delete_row).pack(side="left", padx=6)
        ttk.Button(rows, text=t("save", lang), command=self._save_rows).pack(side="left")

        ttk.Label(frame, textvariable=self.status).grid(row=5, column=0, sticky="w", pady=(8, 0))

        buttons = ttk.Frame(frame)
        buttons.grid(row=6, column=0, sticky="w", pady=(8, 0))
        ttk.Button(buttons, text=t("save_and_start", lang), command=self.start).pack(side="left")
        ttk.Button(buttons, text=t("stop", lang), command=self.stop).pack(side="left", padx=6)
        ttk.Button(buttons, text=t("open_log", lang), command=self._open_log).pack(side="left")

    def _on_language_changed(self) -> None:
        lang = self.language.get()
        if lang not in LANGUAGES:
            return
        self.lang = lang
        self.root.title(t("app_title", lang))
        self._refresh_rows()
        self.status.set(t("status_stopped", lang))

    def _refresh_rows(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for row in read_deployments(self.config_path):
            masked = row.api_key
            if masked.startswith("os.environ/"):
                display = masked
            elif len(masked) > 12:
                display = f"{masked[:6]}...{masked[-4:]}"
            else:
                display = masked
            self.tree.insert("", "end", values=(row.model_name, row.model, display, row.api_base))

    def _add_row(self) -> None:
        lang = self.lang
        window = tk.Toplevel(self.root)
        window.title(t("add_window_title", lang))
        window.transient(self.root)

        provider = tk.StringVar(value="gemini")
        name = tk.StringVar()
        provider_model = tk.StringVar()
        api_key = tk.StringVar()
        base_url = tk.StringVar(value="http://127.0.0.1:1234/v1")
        hint = tk.StringVar(value=t("hint_fetch", lang))

        ttk.Label(window, text=t("label_provider", lang)).grid(row=0, column=0, sticky="w", padx=8, pady=4)
        provider_box = ttk.Combobox(window, textvariable=provider, values=[provider_display_name(p, lang) for p in PROVIDERS], width=20, state="readonly")
        provider_box.grid(row=0, column=1, sticky="w", padx=8, pady=4)

        key_row = ttk.Frame(window)
        key_row.grid(row=2, column=1, sticky="w")
        url_row = ttk.Frame(window)
        url_row.grid(row=1, column=1, sticky="w")
        url_entry = ttk.Entry(url_row, textvariable=base_url, width=36)
        ttk.Label(window, text=t("label_base_url", lang)).grid(row=1, column=0, sticky="w", padx=8, pady=4)

        def provider_key(label: str) -> str:
            for p in PROVIDERS:
                if provider_display_name(p, lang) == label:
                    return p
            return label

        def show_provider_fields() -> None:
            key = provider_key(provider.get())
            if key == LOCAL_PROVIDER:
                url_entry.grid(row=0, column=0)
                hint.set(t("hint_local", lang))
            else:
                url_entry.grid_forget()
                hint.set(t("hint_fetch", lang))

        provider_box.bind("<<ComboboxSelected>>", lambda _event: show_provider_fields())

        ttk.Entry(key_row, textvariable=api_key, width=36).pack(side="left")
        fetch_button = ttk.Button(
            key_row,
            text=t("fetch_models", lang),
            command=lambda: self._fill_models(
                provider_key(provider.get()),
                api_key.get().strip(),
                base_url.get().strip(),
                fetch_button,
                hint,
                model_box,
            ),
        )
        fetch_button.pack(side="left", padx=4)
        ttk.Label(window, text=t("label_api_key", lang)).grid(row=2, column=0, sticky="w", padx=8, pady=4)

        ttk.Label(window, text=t("label_name", lang)).grid(row=3, column=0, sticky="w", padx=8, pady=4)
        ttk.Entry(window, textvariable=name, width=48).grid(row=3, column=1, sticky="w", padx=8, pady=4)

        ttk.Label(window, text=t("label_provider_model", lang)).grid(row=4, column=0, sticky="w", padx=8, pady=4)
        model_box = ttk.Combobox(window, textvariable=provider_model, width=48)
        model_box.grid(row=4, column=1, sticky="w", padx=8, pady=4)

        status = ttk.Label(window, textvariable=hint)
        status.grid(row=5, column=1, sticky="w", padx=8)
        provider.set(provider_display_name("gemini", lang))
        show_provider_fields()

        def commit() -> None:
            model_name: Final = name.get().strip()
            provider_model_name: Final = provider_model.get().strip()
            key: Final = api_key.get().strip()
            if not model_name or not provider_model_name:
                messagebox.showerror(t("key_input_title", lang), t("error_required", lang), parent=window)
                return
            local: Final = provider_key(provider.get()) == LOCAL_PROVIDER
            try:
                row = (
                    local_deployment(model_name, provider_model_name, key, base_url.get(), lang)
                    if local
                    else Deployment(model_name, provider_model_name, key)
                )
            except ValueError as error:
                messagebox.showerror(t("label_base_url", lang), str(error), parent=window)
                return
            prov_key = provider_key(provider.get())
            if not local and prov_key in ("gemini", "openai", "anthropic"):
                prefix = f"{prov_key}/"
                if not row.model.startswith(prefix):
                    row = Deployment(row.model_name, f"{prefix}{row.model}", row.api_key, row.api_base)
            rows = read_deployments(self.config_path)
            write_deployments(self.config_path, rows + (row,))
            window.destroy()
            self._refresh_rows()

        ttk.Button(window, text=t("add", lang), command=commit).grid(row=6, column=1, sticky="e", padx=8, pady=8)

    def _fill_models(
        self,
        provider: str,
        api_key: str,
        base_url: str,
        button: ttk.Button,
        hint: tk.StringVar,
        model_box: ttk.Combobox,
    ) -> None:
        lang = self.lang
        if not api_key and provider != LOCAL_PROVIDER:
            hint.set(t("error_key_required", lang))
            return
        if provider == LOCAL_PROVIDER and not base_url:
            hint.set(t("error_url_required", lang))
            return
        button.state(["disabled"])
        hint.set(t("hint_fetching", lang))

        def done() -> None:
            button.state(["!disabled"])

        def worker() -> None:
            try:
                models = fetch_provider_models(provider, api_key, base_url, lang)
            except Exception as error:
                message = t("fetch_fail", lang, message=f"{type(error).__name__}: {error}")
                self.root.after(0, lambda: hint.set(message))
                self.root.after(0, done)
                return
            names = tuple(m.split("/", 1)[1] for m in models)
            self.root.after(0, done)
            self.root.after(0, lambda: hint.set(t("fetch_success", lang, count=len(names))))
            self.root.after(0, lambda: model_box.configure(values=names))

        threading.Thread(target=worker, daemon=True).start()

    def _delete_row(self) -> None:
        lang = self.lang
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo(t("delete_title", lang), t("error_delete_select", lang))
            return
        all_rows = read_deployments(self.config_path)
        positions = {self.tree.index(item) for item in selected}
        write_deployments(self.config_path, tuple(row for i, row in enumerate(all_rows) if i not in positions))
        self._refresh_rows()

    def _save_rows(self) -> None:
        self._refresh_rows()
        self.status.set(t("status_saved", self.lang))

    def _open_config(self) -> None:
        if self.config_path and self.config_path.is_file():
            os.startfile(str(self.config_path))

    def _open_log(self) -> None:
        if self.log_path.is_file():
            os.startfile(str(self.log_path))

    def _validated_settings(self) -> Settings | None:
        lang = self.lang
        try:
            port = int(self.port.get())
        except ValueError:
            messagebox.showerror(t("port_title", lang), t("error_port_number", lang))
            return None
        if not 1 <= port <= 65535:
            messagebox.showerror(t("port_title", lang), t("error_port_range", lang))
            return None
        return Settings(
            host=self.host.get().strip() or "127.0.0.1",
            port=port,
            master_key=self.master_key.get().strip(),
            language=lang,
        )

    def start(self) -> None:
        lang = self.lang
        if self.process.running():
            self.status.set(t("status_already_running", lang))
            return
        settings = self._validated_settings()
        if settings is None:
            return
        if not settings.master_key:
            messagebox.showwarning(t("master_key_title", lang), unauthenticated_warning(settings.host, lang))
        settings.save(self.config_path)
        set_autostart(self.autostart.get())
        try:
            self.process.start(self.config_path, settings, self.log_path)
        except (OSError, RuntimeError) as error:
            messagebox.showerror(t("error_start_failed", lang), str(error))
            return
        self.status.set(t("status_starting", lang, host=settings.host, port=settings.port, log=LOG_NAME))
        threading.Thread(target=self._watch_startup, args=(settings.port,), daemon=True).start()

    def _watch_startup(self, port: int) -> None:
        lang = self.lang
        for _ in range(90):
            if health_ok(port):
                self.status.set(t("status_running", lang, port=port))
                return
            if not self.process.running():
                self.status.set(t("status_failed", lang, log=LOG_NAME))
                return
            threading.Event().wait(2)
        self.status.set(t("status_failed_check", lang))

    def stop(self) -> None:
        self.process.stop()
        self.status.set(t("status_stopped", self.lang))

    def hide(self) -> None:
        if not self._ensure_tray():
            self.root.iconify()
            return
        self.root.withdraw()

    def show(self) -> None:
        self.root.after(0, self.root.deiconify)

    def _ensure_tray(self) -> bool:
        if self.tray is not None:
            return True
        try:
            import pystray
            from PIL import Image, ImageDraw
        except ImportError:
            return False
        image = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
        ImageDraw.Draw(image).ellipse((6, 6, 26, 26), fill=(37, 99, 235, 255))
        lang = self.lang
        menu = pystray.Menu(
            pystray.MenuItem(t("tray_show", lang), lambda: self.show(), default=True),
            pystray.MenuItem(t("tray_start", lang), lambda: self.root.after(0, self.start)),
            pystray.MenuItem(t("tray_stop", lang), lambda: self.root.after(0, self.stop)),
            pystray.MenuItem(t("tray_quit", lang), lambda: self.quit()),
        )
        self.tray = pystray.Icon(t("tray_title", lang), image, t("tray_title", lang), menu)
        threading.Thread(target=self.tray.run, daemon=True).start()
        return True

    def quit(self) -> None:
        settings = self._validated_settings()
        if settings is not None:
            settings.save(self.config_path)
        self.process.stop()
        if self.tray is not None:
            self.tray.stop()
        self.root.after(0, self.root.destroy)

    def run(self) -> None:
        self.root.mainloop()


def run_headless() -> int:
    base = app_dir()
    config = ensure_config(base)
    settings: Final = Settings.load(config)
    log_path: Final = base / LOG_NAME
    if not settings.master_key:
        append_log_line(log_path, unauthenticated_warning(settings.host, settings.language))
    process = ProxyProcess()
    process.start(config, settings, log_path)
    try:
        while process.running():
            threading.Event().wait(5)
    except KeyboardInterrupt:
        process.stop()
    return 0


def main() -> int:
    import multiprocessing

    multiprocessing.freeze_support()
    parser = argparse.ArgumentParser(description=t("headless_description", DEFAULT_LANGUAGE))
    parser.add_argument("--headless", action="store_true", help=t("headless_help", DEFAULT_LANGUAGE))
    args: Final = parser.parse_args()
    if args.headless:
        return run_headless()
    Launcher().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
