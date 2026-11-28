# LiteLLM Proxy Windows 実行パッケージ

`LiteLLMTray.exe` をダブルクリックするだけで、Windows 11 / 10 の上に LiteLLM Proxy が立ち上がる配布物です。
Python、venv、Docker、WSL は不要です。GUI でモデルと API キーを設定でき、閉じるボタンでトレイに収納され、
Windows 起動時に自動実行もできます。

本リポジトリは https://github.com/BerriAI/litellm を元にしており、exe に Proxy 本体を同梱するための
最小構成に整理しています。upstream のオリジナルドキュメントは [README_org.md](README_org.md) に残してあります。

## 動かし方

設定は実行フォルダの `litellm.config` 1 枚に集約されています。このファイルは手で触るものではなく、
GUI に入力した内容が書き込まれるファイルです。

1. `LiteLLMTray.exe` を手に入れます。ビルド済みの exe を配布してもらうか、自分でビルドします
2. `LiteLLMTray.exe` を実行します。`litellm.config` が無ければ exe と同じフォルダに作られます
3. ウィンドウでマスターキーとモデルを入力して「保存して起動」を押します。終了時も保存されます

ビルドが必要な場合だけ Python と Rust を使います。

```
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[proxy]" pystray pillow pyinstaller
.venv\Scripts\python.exe -m PyInstaller --noconfirm --distpath . windows_launcher\LiteLLMTray.spec
```

Rust のツールチェーンが見つからないエラーが出たら https://rustup.rs を一度実行してください。
出来上がった exe は 260 MB 前後あり、GitHub に載せると大きすぎるため git には入れていません。
exe 1 本と README だけを配布すれば、ビルド環境のない人にも配れます。

古い `config.yaml` と `litellm-windows.yaml` が同じフォルダにある場合は、初回起動時に
`litellm.config` へ自動で引っ越します。`config.yaml` の `os.environ/GEMINI_API_KEY_1` のような
環境変数参照は、`.env` の実値に置き換わります。

## GUI の使い方

| 項目 | 内容 |
| --- | --- |
| バインド | `127.0.0.1` は自分だけ、`0.0.0.0` は LAN 全体からアクセス可能 |
| ポート | 既定は 4000。他 PC の Docker 版と同じ 4000 が既定値です |
| マスターキー | Proxy 自体を守るキー。未設定でも起動しますが、警告ダイアログが出ます |
| モデルを追加 | プロバイダと API キーを入れると「モデル一覧を取得」で使えるモデルを一覧から選べます |
| openai 互換ローカル | LM Studio、Ollama、vLLM などを URL で追加します。`http://127.0.0.1:1234/v1` のように入れるとそのサーバーのモデル一覧が取れます。鍵を要求しないサーバーは API キーを空にできます |
| 保存して起動 | 設定を `litellm.config` に書き出して Proxy を起動し、正常起動完了まで待ちます |
| 停止 | 起動中の Proxy とその子プロセスを止めます |

閉じるボタンを押すとウィンドウは消え、タスクバー右下の通知領域にアイコンが出ます。
アイコンをクリックすると表示、右クリックで表示 / 起動 / 停止 / 終了ができます。

## 使い方 (コマンド)

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

## API キーの安全な扱い

GUI に入力した API キーは `litellm.config` にそのまま書かれます。このファイルは `.gitignore` 済みなので
push はされませんが、共有フォルダやバックアップに置く場合は平文だと理解しておいてください。
既存のファイルを手編集する場合は `api_key: os.environ/GEMINI_API_KEY_1` のように環境変数参照も使えます。
その場合、実値は exe と同じフォルダの `.env` から読まれます。

マスターキー未設定で起動すると、LiteLLM は認証なしで要求を通します。バインドが `127.0.0.1` なら
他の PC からは到達しませんが、`0.0.0.0` にした瞬間に LAN 全体から誰でも使える状態になります。
`--headless` で起動した場合も同じ警告が `litellm.log` に記録されます。

## Windows 起動時の自動実行

GUI の「Windows 起動時に自動実行」にチェックを入れると、ログオン時に同じ exe が `--headless` で起動します。
`--headless` は GUI を開かず、`litellm.config` に保存された設定でそのまま Proxy を立ち上げます。
登録は現在のユーザーのログオン時に限定され、コントロールパネルのスタートアップ項目から消せます。

## exe を再ビルドする場合

`windows_launcher\LiteLLMTray.spec` が litellm 本体、依存パッケージ、tiktoken のエンコーディング定義を
集める設定になっています。コマンドは「動かし方」のビルド手順と同じで、生成される exe は 260 MB 前後です。
同じフォルダに古い exe があると上書きされます。

## よくある質問

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

## 構成

```
LiteLLMTray.exe              実行ファイル (Proxy 本体と依存を同梱)
litellm.config               実行時に作られる設定 (バインド、ポート、マスターキー、モデル一覧)
litellm.log                  起動履歴と Proxy のログ
config.yaml                  初期モデル定義 (exe と同じフォルダに置くと litellm.config へ取り込む)
windows_launcher/            exe のソースとビルド設定とテスト
README_org.md                upstream litellm のオリジナル README
```

## ライセンス

LiteLLM は MIT ライセンスです。詳細は upstream のリポジトリと [LICENSE](LICENSE) を参照してください。
