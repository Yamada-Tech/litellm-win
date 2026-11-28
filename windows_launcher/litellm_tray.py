"""Windows 用の LiteLLM Proxy ランチャー。

設定 GUI とシステムトレイを提供し、`litellm.config` 1 枚に設定を集約して Proxy を起動する。
Proxy 本体は exe に同梱されており、自分自身を `--proxy-internal` で再起動する形で起動する。
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

HOST_CHOICES: Final = ("127.0.0.1", "0.0.0.0")
CONFIG_NAME: Final = "litellm.config"
LEGACY_CONFIG_NAME: Final = "config.yaml"
LEGACY_SETTINGS_NAME: Final = "litellm-windows.yaml"
LOG_NAME: Final = "litellm.log"
MASTER_KEY_ENV_VAR: Final = "LITELLM_MASTER_KEY"
WEAK_MASTER_KEY_ENV_VAR: Final = "LITELLM_DANGEROUSLY_PERMIT_WEAK_OR_UNSET_MASTER_KEY"
DEFAULT_SETTINGS: Final = MappingProxyType({"host": "127.0.0.1", "port": 4000, "master_key": ""})
STARTUP_KEY: Final = r"Software\Microsoft\Windows\CurrentVersion\Run"
STARTUP_VALUE: Final = "LiteLLMProxyTray"


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def self_command() -> tuple[str, ...]:
    """自分自身をもう一度起動するときのファイル名のかたち。"""
    if getattr(sys, "frozen", False):
        return (sys.executable,)
    return (sys.executable, str(Path(__file__).resolve()))


def ensure_config(base: Path) -> Path:
    """設定ファイルが無ければ実行フォルダに作る。"""
    path = base / CONFIG_NAME
    if not path.is_file():
        dump_yaml(path, initial_config(base))
    return path


def initial_config(base: Path) -> dict[str, object]:
    return {**DEFAULT_SETTINGS, **legacy_config(base)}


def legacy_config(base: Path) -> dict[str, object]:
    """旧 config.yaml / .env / litellm-windows.yaml の設定を 1 枚にまとめる。"""
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
    """os.environ/ 参照を .env の実値に置き換える。見つからなければ参照を残す。"""
    name: Final = value.removeprefix("os.environ/")
    if name == value:
        return value
    return env_values.get(name, value)


def local_deployment(model_name: str, provider_model: str, api_key: str, base_url: str) -> Deployment:
    """OpenAI 互換のローカルサーバー 1 本を作る。鍵を要求しないサーバーは placeholder を入れる。"""
    model = provider_model if provider_model.startswith("openai/") else f"openai/{provider_model}"
    return Deployment(model_name, model, api_key or NO_KEY_PLACEHOLDER, normalize_openai_compatible_base(base_url))


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

    @staticmethod
    def load(config_path: Path) -> "Settings":
        raw: Final = load_yaml(config_path)
        return Settings(
            host=str(raw.get("host", "127.0.0.1")),
            port=int(raw.get("port", 4000)),
            master_key=str(raw.get("master_key", "")),
        )

    def save(self, config_path: Path) -> None:
        data = load_yaml(config_path)
        data.update({"host": self.host, "port": self.port, "master_key": self.master_key})
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
LOCAL_PROVIDER: Final = "openai 互換ローカル"
PROVIDERS: Final = ("gemini", "openai", "anthropic", LOCAL_PROVIDER, "その他")
# ローカル推論サーバーは鍵を検証しないが、OpenAI SDK は空の Bearer ヘッダを拒否する
NO_KEY_PLACEHOLDER: Final = "not-needed"


def normalize_openai_compatible_base(value: str) -> str:
    """OpenAI 互換サーバーのベース URL を `<host>/v1` の形に揃える。"""
    parsed = urlparse(value.strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("URL は http:// または https:// で入力してください")
    segments = parsed.path.split("/")
    if "v1" in segments:
        path = "/".join(segments[: segments.index("v1") + 1])
    else:
        path = parsed.path.rstrip("/") + "/v1"
    return f"{parsed.scheme}://{parsed.netloc}{path}"


def unauthenticated_warning(host: str) -> str:
    """マスターキー無しで起動する后果を、起動を止めずに伝える。"""
    reach: Final = "LAN 全体からアクセスできる状態です" if host == "0.0.0.0" else "アクセスは自分だけになります"
    return (
        "マスターキーが未設定のまま起動します。未設定の LiteLLM は認証なしで要求を通すため、"
        f"誰でもアクセス可能となります。ネットワーク外に公開しないでください。"
        f"現在のバインド {host} では {reach}。"
    )


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


def fetch_provider_models(provider: str, api_key: str, base_url: str = "") -> tuple[str, ...]:
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
        base = normalize_openai_compatible_base(base_url) if provider == LOCAL_PROVIDER else OPENAI_MODELS_URL
        models_url = base if base.endswith("/models") else f"{base}/models"
        req = request.Request(models_url, headers={"Authorization": f"Bearer {api_key or NO_KEY_PLACEHOLDER}"})
        with request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read())
        return tuple(f"openai/{m['id']}" for m in data.get("data", []))
    if provider == "anthropic":
        raise ValueError("Anthropic はモデル一覧 API を提供していません。モデル名を手入力してください")
    raise ValueError("このプロバイダの一覧取得は未対応です。モデル名を手入力してください")


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
            # 未設定だと Proxy 本体が起動を拒否するので、upstream 公式の escape hatch で通す
            env[WEAK_MASTER_KEY_ENV_VAR] = "true"
        env.update(load_dotenv_files((app_dir(),)))
        command = [
            *self_command(),
            "--proxy-internal",
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
        self.process = ProxyProcess()
        self.tray = None
        self.root = tk.Tk()
        self.root.title("LiteLLM Proxy")
        self.root.protocol("WM_DELETE_WINDOW", self.hide)
        self.host = tk.StringVar(value=settings.host)
        self.port = tk.StringVar(value=str(settings.port))
        self.master_key = tk.StringVar(value=settings.master_key)
        self.autostart = tk.BooleanVar(value=autostart_enabled())
        self.status = tk.StringVar(value="停止中")
        self._build_form()
        self._refresh_rows()

    def _build_form(self) -> None:
        frame = ttk.Frame(self.root, padding=12)
        frame.grid(sticky="nsew")

        grid = ttk.Frame(frame)
        grid.grid(row=0, column=0, sticky="w")
        ttk.Label(grid, text="バインド").grid(row=0, column=0, sticky="w")
        ttk.Combobox(grid, textvariable=self.host, values=HOST_CHOICES, width=14).grid(row=0, column=1, sticky="w")
        ttk.Label(grid, text="ポート").grid(row=1, column=0, sticky="w")
        ttk.Entry(grid, textvariable=self.port, width=16).grid(row=1, column=1, sticky="w")
        ttk.Label(grid, text="マスターキー").grid(row=2, column=0, sticky="w")
        ttk.Entry(grid, textvariable=self.master_key, width=34, show="*").grid(row=2, column=1, sticky="w")
        ttk.Checkbutton(grid, text="Windows 起動時に自動実行", variable=self.autostart).grid(
            row=3, column=0, columnspan=2, sticky="w"
        )

        self.config_label = ttk.Label(frame, text=f"設定ファイル: {self.config_path}")
        self.config_label.grid(row=1, column=0, sticky="w", pady=(8, 0))
        picker = ttk.Frame(frame)
        picker.grid(row=2, column=0, sticky="w")
        ttk.Button(picker, text="設定を開く", command=self._open_config).pack(side="left", padx=6)

        self.tree = ttk.Treeview(
            frame, columns=("model_name", "model", "api_key", "api_base"), show="headings", height=7
        )
        for column, title, width in (
            ("model_name", "モデル名", 160),
            ("model", "プロバイダ側モデル", 220),
            ("api_key", "API キー", 200),
            ("api_base", "ベース URL", 220),
        ):
            self.tree.heading(column, text=title)
            self.tree.column(column, width=width)
        self.tree.grid(row=3, column=0, sticky="nsew", pady=(8, 0))

        rows = ttk.Frame(frame)
        rows.grid(row=4, column=0, sticky="w", pady=(4, 0))
        ttk.Button(rows, text="モデルを追加", command=self._add_row).pack(side="left")
        ttk.Button(rows, text="選択を削除", command=self._delete_row).pack(side="left", padx=6)
        ttk.Button(rows, text="保存", command=self._save_rows).pack(side="left")

        ttk.Label(frame, textvariable=self.status).grid(row=5, column=0, sticky="w", pady=(8, 0))

        buttons = ttk.Frame(frame)
        buttons.grid(row=6, column=0, sticky="w", pady=(8, 0))
        ttk.Button(buttons, text="保存して起動", command=self.start).pack(side="left")
        ttk.Button(buttons, text="停止", command=self.stop).pack(side="left", padx=6)
        ttk.Button(buttons, text="ログを開く", command=self._open_log).pack(side="left")

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
        window = tk.Toplevel(self.root)
        window.title("モデルを追加")
        window.transient(self.root)

        provider = tk.StringVar(value="gemini")
        name = tk.StringVar()
        provider_model = tk.StringVar()
        api_key = tk.StringVar()
        base_url = tk.StringVar(value="http://127.0.0.1:1234/v1")
        hint = tk.StringVar(value="キーを入れて「モデル一覧を取得」を押すと、モデル名に候補が出ます")

        ttk.Label(window, text="プロバイダ").grid(row=0, column=0, sticky="w", padx=8, pady=4)
        provider_box = ttk.Combobox(window, textvariable=provider, values=PROVIDERS, width=20, state="readonly")
        provider_box.grid(row=0, column=1, sticky="w", padx=8, pady=4)

        key_row = ttk.Frame(window)
        key_row.grid(row=2, column=1, sticky="w")
        url_row = ttk.Frame(window)
        url_row.grid(row=1, column=1, sticky="w")
        url_entry = ttk.Entry(url_row, textvariable=base_url, width=36)
        ttk.Label(window, text="ベース URL").grid(row=1, column=0, sticky="w", padx=8, pady=4)

        def show_provider_fields() -> None:
            if provider.get() == LOCAL_PROVIDER:
                url_entry.grid(row=0, column=0)
                hint.set("LM Studio / Ollama / vLLM などの URL です。鍵を要求しないサーバーは空のままにできます")
            else:
                url_entry.grid_forget()
                hint.set("キーを入れて「モデル一覧を取得」を押すと、モデル名に候補が出ます")

        provider_box.bind("<<ComboboxSelected>>", lambda _event: show_provider_fields())

        ttk.Entry(key_row, textvariable=api_key, width=36).pack(side="left")
        fetch_button = ttk.Button(
            key_row,
            text="モデル一覧を取得",
            command=lambda: self._fill_models(
                provider.get(),
                api_key.get().strip(),
                base_url.get().strip(),
                fetch_button,
                hint,
                model_box,
            ),
        )
        fetch_button.pack(side="left", padx=4)
        ttk.Label(window, text="API キー").grid(row=2, column=0, sticky="w", padx=8, pady=4)

        ttk.Label(window, text="モデル名").grid(row=3, column=0, sticky="w", padx=8, pady=4)
        ttk.Entry(window, textvariable=name, width=48).grid(row=3, column=1, sticky="w", padx=8, pady=4)

        ttk.Label(window, text="プロバイダ側モデル").grid(row=4, column=0, sticky="w", padx=8, pady=4)
        model_box = ttk.Combobox(window, textvariable=provider_model, width=48)
        model_box.grid(row=4, column=1, sticky="w", padx=8, pady=4)

        status = ttk.Label(window, textvariable=hint)
        status.grid(row=5, column=1, sticky="w", padx=8)
        show_provider_fields()

        def commit() -> None:
            model_name: Final = name.get().strip()
            provider_model_name: Final = provider_model.get().strip()
            key: Final = api_key.get().strip()
            if not model_name or not provider_model_name:
                messagebox.showerror("入力", "モデル名とプロバイダ側モデルは必須です", parent=window)
                return
            local: Final = provider.get() == LOCAL_PROVIDER
            try:
                row = (
                    local_deployment(model_name, provider_model_name, key, base_url.get())
                    if local
                    else Deployment(model_name, provider_model_name, key)
                )
            except ValueError as error:
                messagebox.showerror("ベース URL", str(error), parent=window)
                return
            if not local and provider.get() in ("gemini", "openai", "anthropic"):
                prefix = f"{provider.get()}/"
                if not row.model.startswith(prefix):
                    row = Deployment(row.model_name, f"{prefix}{row.model}", row.api_key, row.api_base)
            rows = read_deployments(self.config_path)
            write_deployments(self.config_path, rows + (row,))
            window.destroy()
            self._refresh_rows()

        ttk.Button(window, text="追加", command=commit).grid(row=6, column=1, sticky="e", padx=8, pady=8)

    def _fill_models(
        self,
        provider: str,
        api_key: str,
        base_url: str,
        button: ttk.Button,
        hint: tk.StringVar,
        model_box: ttk.Combobox,
    ) -> None:
        if not api_key and provider != LOCAL_PROVIDER:
            hint.set("API キーを入力してください")
            return
        if provider == LOCAL_PROVIDER and not base_url:
            hint.set("ベース URL を入力してください")
            return
        button.state(["disabled"])
        hint.set("モデル一覧を取得しています...")

        def done() -> None:
            button.state(["!disabled"])

        def worker() -> None:
            try:
                models = fetch_provider_models(provider, api_key, base_url)
            except Exception as error:
                message = f"取得に失敗しました: {type(error).__name__}: {error}"
                self.root.after(0, lambda: hint.set(message))
                self.root.after(0, done)
                return
            names = tuple(m.split("/", 1)[1] for m in models)
            self.root.after(0, done)
            self.root.after(0, lambda: hint.set(f"{len(names)} 件取得しました。入力欄から選べます"))
            self.root.after(0, lambda: model_box.configure(values=names))

        threading.Thread(target=worker, daemon=True).start()

    def _delete_row(self) -> None:
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo("削除", "削除する行を選択してください")
            return
        all_rows = read_deployments(self.config_path)
        positions = {self.tree.index(item) for item in selected}
        write_deployments(self.config_path, tuple(row for i, row in enumerate(all_rows) if i not in positions))
        self._refresh_rows()

    def _save_rows(self) -> None:
        self._refresh_rows()
        self.status.set("モデル設定を保存しました")

    def _open_config(self) -> None:
        if self.config_path and self.config_path.is_file():
            os.startfile(str(self.config_path))

    def _open_log(self) -> None:
        if self.log_path.is_file():
            os.startfile(str(self.log_path))

    def _validated_settings(self) -> Settings | None:
        try:
            port = int(self.port.get())
        except ValueError:
            messagebox.showerror("ポート", "ポートは数値で入力してください")
            return None
        if not 1 <= port <= 65535:
            messagebox.showerror("ポート", "ポートは 1 から 65535 の範囲で入力してください")
            return None
        return Settings(
            host=self.host.get().strip() or "127.0.0.1",
            port=port,
            master_key=self.master_key.get().strip(),
        )

    def start(self) -> None:
        if self.process.running():
            self.status.set("すでに起動しています")
            return
        settings = self._validated_settings()
        if settings is None:
            return
        if not settings.master_key:
            messagebox.showwarning("マスターキー", unauthenticated_warning(settings.host))
        settings.save(self.config_path)
        set_autostart(self.autostart.get())
        try:
            self.process.start(self.config_path, settings, self.log_path)
        except OSError as error:
            messagebox.showerror("起動失敗", str(error))
            return
        self.status.set(f"起動中 http://{settings.host}:{settings.port}/  ログ: {LOG_NAME}")
        threading.Thread(target=self._watch_startup, args=(settings.port,), daemon=True).start()

    def _watch_startup(self, port: int) -> None:
        for _ in range(90):
            if health_ok(port):
                self.status.set(f"稼働中 http://127.0.0.1:{port}/")
                return
            if not self.process.running():
                self.status.set(f"起動に失敗しました。{LOG_NAME} を確認してください")
                return
            threading.Event().wait(2)
        self.status.set("起動を確認できません。ログを確認してください")

    def stop(self) -> None:
        self.process.stop()
        self.status.set("停止中")

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
        menu = pystray.Menu(
            pystray.MenuItem("表示", lambda: self.show(), default=True),
            pystray.MenuItem("起動", lambda: self.root.after(0, self.start)),
            pystray.MenuItem("停止", lambda: self.root.after(0, self.stop)),
            pystray.MenuItem("終了", lambda: self.quit()),
        )
        self.tray = pystray.Icon("LiteLLM Proxy", image, "LiteLLM Proxy", menu)
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
        append_log_line(log_path, unauthenticated_warning(settings.host))
    process = ProxyProcess()
    process.start(config, settings, log_path)
    try:
        while process.running():
            threading.Event().wait(5)
    except KeyboardInterrupt:
        process.stop()
    return 0


def run_bundled_proxy() -> None:
    if not getattr(sys, "frozen", False):
        sys.path.insert(0, str(app_dir()))
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    sys.argv = [sys.argv[0]] + [arg for arg in sys.argv[1:] if arg != "--proxy-internal"]
    from litellm.proxy.proxy_cli import run_server

    run_server()


def main() -> int:
    import multiprocessing

    multiprocessing.freeze_support()
    if "--proxy-internal" in sys.argv:
        run_bundled_proxy()
        return 0
    parser = argparse.ArgumentParser(description="LiteLLM Proxy Windows ランチャー")
    parser.add_argument("--headless", action="store_true", help="GUI なしで保存済み設定を使い起動する")
    args: Final = parser.parse_args()
    if args.headless:
        return run_headless()
    Launcher().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
