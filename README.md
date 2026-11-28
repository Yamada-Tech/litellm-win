# LiteLLM Proxy Windows

**English** | [日本語](#日本語)

## English

Double-click `LiteLLMTray.exe` and LiteLLM Proxy starts on Windows 11 / 10. You can configure models and API keys in the GUI, close the window to収納トレイ, and start it at Windows login.

The exe does not bundle the Proxy itself. On first run it creates a `.venv` in the same folder, installs `litellm[proxy]` from PyPI, and starts the Proxy from there. If `.venv` already exists, it is reused and not reinstalled.

This repository is a minimal layout derived from https://github.com/BerriAI/litellm that carries only the exe source and build config. The upstream original documentation is kept in [README_org.md](README_org.md).

### How to run

Settings are gathered in a single file `litellm.config` in the run folder. This file is not meant to be edited by hand; it is written by the GUI.

1. Get `LiteLLMTray.exe`. Use a prebuilt copy or build it yourself
2. Run `LiteLLMTray.exe`. If `litellm.config` is missing it is created next to the exe
3. First run installs the venv and `litellm[proxy]`. An internet connection and Python are required
4. Fill in master key and models in the window, then press "Save and start". Settings are also saved on exit

Python and Rust are only needed for building.

```
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[proxy]" pystray pillow pyinstaller
.venv\Scripts\python.exe -m PyInstaller --noconfirm --distpath . windows_launcher\LiteLLMTray.spec
```

The resulting exe is about 15 MB since it only bundles pystray and PIL. The Proxy (about 200 MB) is not inside the exe; it is unpacked into `.venv` on first run.

If a legacy `config.yaml` or `litellm-windows.yaml` sits next to the exe, it is migrated to `litellm.config` on first run. `os.environ/GEMINI_API_KEY_1` references inside `config.yaml` are replaced with real values from `.env`.

### GUI

| Item | Meaning |
| --- | --- |
| Bind | `127.0.0.1` is local only, `0.0.0.0` is LAN-wide |
| Port | Default 4000 |
| Master key | Protects the Proxy. Starts even without one, but a warning shows |
| Add model | Enter provider and API key, then press "Fetch models" to pick from the list |
| OpenAI-compatible local | LM Studio, Ollama, vLLM etc. added via URL. Servers without a key can leave the key empty |
| Language | English or Japanese; saved in `litellm.config` |
| Save and start | Writes `litellm.config` and starts the Proxy, waiting for a healthy start |
| Stop | Stops the running Proxy and its children |

Pressing the close button hides the window and shows an icon in the notification area. Clicking the icon shows it; right-click gives Show / Start / Stop / Quit.

### Command usage

For the OpenAI SDK:

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:4000/v1", api_key="master key")
print(client.chat.completions.create(model="gemini-3.5-flash-lite", messages=[{"role": "user", "content": "hello"}]))
```

Or with curl:

```
curl http://127.0.0.1:4000/v1/chat/completions -H "Authorization: Bearer master key" -H "Content-Type: application/json" -d "{\"model\":\"gemini-3.5-flash-lite\",\"messages\":[{\"role\":\"user\",\"content\":\"hello\"}]}"
```

The Web UI is `http://127.0.0.1:4000/ui`, API reference is `http://127.0.0.1:4000/` and `http://127.0.0.1:4000/swagger`.
Start history lives in `litellm.log` next to the exe.

### API key safety

API keys typed into the GUI are written to `litellm.config` in plain text. The file is `.gitignore`d and is not pushed, but treat it as plain text if the folder is shared or backed up. You can also hand-edit `api_key: os.environ/GEMINI_API_KEY_1`; the real value is read from `.env` next to the exe.

Starting without a master key makes LiteLLM pass requests without authentication. With `127.0.0.1` only you can reach it, but with `0.0.0.0` anyone on the LAN can. `--headless` logs the same warning to `litellm.log`.

### Auto-start at Windows login

Checking "Start on Windows login" starts the venv Python with `--headless` at logon. `--headless` does not open the GUI and starts the Proxy with the saved `litellm.config` settings. Registration is limited to the current user.

### Rebuilding

`windows_launcher\LiteLLMTray.spec` gathers only pystray and PIL. The Proxy itself is not bundled; it unpacks into `.venv` on first run. The build command is the same as above.

### FAQ

`0.0.0.0` but unreachable from other PCs
: Open the port in Windows Defender Firewall. When you do, always set a master key

Forgot the master key
: `litellm.config` stores it in plain text. type a new key in the GUI and save to replace it

Model list fetch fails
: Anthropic has no model list API. type the model name by hand. Invalid keys also fail

Proxy does not stop
: Use the tray "Quit". Closing the window does not stop it

Model returns 429
: Registering multiple keys for the same `model_name` switches to another key automatically. `num_retries`, `cooldown_time`, and per-failure-type cooldown (`allowed_fails_policy`) can be tuned in `router_settings` in `litellm.config`

First run fails
: Installing `litellm[proxy]` needs internet access and Python. If `.venv` is broken, delete `.venv` and `.litellm-ready` and restart

### Layout

```
LiteLLMTray.exe              the launcher (pystray/PIL only; Proxy is not bundled)
.venv/                       runtime environment built on first run
.litellm-ready               marker file for a finished venv
litellm.config               settings written at run time
litellm.log                  start history and Proxy log
config.yaml                  legacy model list (migrated into litellm.config)
windows_launcher/            exe source, build config, and tests
README_org.md                upstream litellm README
```

## License

LiteLLM is MIT. See the upstream repository and [LICENSE](LICENSE).

<a id="日本語"></a>

## 日本語

`LiteLLMTray.exe` をダブルクリックするだけで、Windows 11 / 10 の上に LiteLLM Proxy が立ち上がる配布物です。
GUI でモデルと API キーを設定でき、閉じるボタンでトレイに収納され、Windows 起動時に自動実行もできます。

exe には LiteLLM Proxy 本体は同梱されていません。初回起動時に実行フォルダへ `.venv` を作り、PyPI から `litellm[proxy]` をインストールして Proxy を起動します。
実行フォルダに `.venv` が既にある場合はそれを使い、再インストールはしません。

本リポジトリは https://github.com/BerriAI/litellm を元にしており、exe のソースとビルド設定だけを持つ最小構成に整理しています。
upstream のオリジナルドキュメントは [README_org.md](README_org.md) に残してあります。

### 動かし方

設定は実行フォルダの `litellm.config` 1 枚に集約されています。このファイルは手で触るものではなく、
GUI に入力した内容が書き込まれるファイルです。

1. `LiteLLMTray.exe` を手に入れます。ビルド済みの exe を配布してもらうか、自分でビルドします
2. `LiteLLMTray.exe` を実行します。`litellm.config` が無ければ exe と同じフォルダに作られます
3. 初回は venv 構築と `litellm[proxy]` のインストールを行います。インターネット接続と Python が必要です
4. ウィンドウでマスターキーとモデルを入力して「保存して起動」を押します。終了時も保存されます

ビルドが必要な場合だけ Python と Rust を使います。

```
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[proxy]" pystray pillow pyinstaller
.venv\Scripts\python.exe -m PyInstaller --noconfirm --distpath . windows_launcher\LiteLLMTray.spec
```

出来上がった exe は pystray と PIL のみを同梱するため 15 MB 前後です。Proxy 本体の約 200 MB は exe には入らず、
初回起動時に `.venv` として実行フォルダへ展開されます。

古い `config.yaml` と `litellm-windows.yaml` が同じフォルダにある場合は、初回起動時に
`litellm.config` へ自動で引っ越します。`config.yaml` の `os.environ/GEMINI_API_KEY_1` のような
環境変数参照は、`.env` の実値に置き換わります。

### GUI の使い方

| 項目 | 内容 |
| --- | --- |
| バインド | `127.0.0.1` は自分だけ、`0.0.0.0` は LAN 全体からアクセス可能 |
| ポート | 既定は 4000 |
| マスターキー | Proxy 自体を守るキー。未設定でも起動しますが、警告ダイアログが出ます |
| モデルを追加 | プロバイダと API キーを入れると「モデル一覧を取得」で使えるモデルを一覧から選べます |
| openai 互換ローカル | LM Studio、Ollama、vLLM などを URL で追加します。鍵を要求しないサーバーは API キーを空にできます |
| 言語 | English / Japanese を選べます。`litellm.config` に保存されます |
| 保存して起動 | 設定を `litellm.config` に書き出して Proxy を起動し、正常起動完了まで待ちます |
| 停止 | 起動中の Proxy とその子プロセスを止めます |

閉じるボタンを押すとウィンドウは消え、タスクバー右下の通知領域にアイコンが出ます。
アイコンをクリックすると表示、右クリックで表示 / 起動 / 停止 / 終了ができます。

### 使い方 (コマンド)

OpenAI SDK を使う場合はベース URL とキーを次のように指定します。

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:4000/v1", api_key="マスターキー")
print(client.chat.completions.create(model="gemini-3.5-flash-lite", messages=[{"role": "user", "content": "hello"}]))
```

curl の場合は次の通りです。

```
curl http://127.0.0.1:4000/v1/chat/completions -H "Authorization: Bearer マスターキー" -H "Content-Type: application/json" -d "{\"model\":\"gemini-3.5-flash-lite\",\"messages\":[{\"role\":\"user\",\"content\":\"hello\"}]}"
```

Web UI は `http://127.0.0.1:4000/ui`、API レファレンスは `http://127.0.0.1:4000/` と
`http://127.0.0.1:4000/swagger` です。
起動履歴は同じフォルダの `litellm.log` に残ります。

### API キーの安全な扱い

GUI に入力した API キーは `litellm.config` にそのまま書かれます。このファイルは `.gitignore` 済みなので
push はされませんが、共有フォルダやバックアップに置く場合は平文だと理解しておいてください。
既存のファイルを手編集する場合は `api_key: os.environ/GEMINI_API_KEY_1` のように環境変数参照も使えます。
その場合、実値は exe と同じフォルダの `.env` から読まれます。

マスターキー未設定で起動すると、LiteLLM は認証なしで要求を通します。バインドが `127.0.0.1` なら
他の PC からは到達しませんが、`0.0.0.0` にした瞬間に LAN 全体から誰でも使える状態になります。
`--headless` で起動した場合も同じ警告が `litellm.log` に記録されます。

### Windows 起動時の自動実行

GUI の「Windows 起動時に自動実行」にチェックを入れると、ログオン時に venv 内 Python が `--headless` で起動します。
`--headless` は GUI を開かず、`litellm.config` に保存された設定でそのまま Proxy を立ち上げます。
登録は現在のユーザーのログオン時に限定されます。

### exe を再ビルドする場合

`windows_launcher\LiteLLMTray.spec` は pystray と PIL のみを集める設定です。Proxy 本体は exe に入れず、
初回起動時に venv として展開されます。コマンドは「動かし方」のビルド手順と同じです。

### よくある質問

`0.0.0.0` にしても他 PC からアクセスできない
: Windows Defender ファイアウォールの受信ルールでポートを開いてください。開く場合はマスターキーを必ず設定します

マスターキーを忘れた
: `litellm.config` の `master_key` に平文で保存されています。GUI で新しいキーを入力して保存すれば置き換わります

モデル一覧の取得が失敗する
: Anthropic はモデル一覧 API を提供していません。モデル名を手入力してください。キーが無効な場合も失敗します

終了しても Proxy が止まらない
: トレイメニューの「終了」を使ってください。ウィンドウを閉じただけでは Proxy は動き続きます

モデルが 429 を返す
: 同じ `model_name` に複数のキーを登録すると自動で別のキーへ切り替えます。`num_retries` と
`cooldown_time`、エラー種別ごとのクールダウン条件 (`allowed_fails_policy`) は
`litellm.config` の `router_settings` で調整できます

初回起動で失敗する
: `litellm[proxy]` のインストールにはインターネット接続と Python が必要です。`.venv` が壊れている場合は
`.venv` と `.litellm-ready` を削除して再起動してください

### 構成

```
LiteLLMTray.exe              実行ファイル (pystray/PIL のみ同梱、Proxy 本体は exe に含まない)
.venv/                       初回起動時に作られる実行環境 (litellm[proxy] 等)
.litellm-ready               venv 構築完了マーカー
litellm.config               実行時に作られる設定 (バインド、ポート、マスターキー、モデル一覧、言語)
litellm.log                  起動履歴と Proxy のログ
config.yaml                  初期モデル定義 (exe と同じフォルダに置くと litellm.config へ取り込む)
windows_launcher/            exe のソースとビルド設定とテスト
README_org.md                upstream litellm のオリジナル README
```

### ライセンス

LiteLLM は MIT ライセンスです。詳細は upstream のリポジトリと [LICENSE](LICENSE) を参照してください。
