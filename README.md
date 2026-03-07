# Review Scraper

Google Maps・TripAdvisorの口コミをスクレイピングするWebアプリ。Cloud Run上で動作し、Cloud Tasksによるジョブ並列実行に対応。

## 主な機能

- 🔍 **Google Maps** — 無限スクロール対応、新しい順ソート、スクロールリカバリ
- 🔍 **TripAdvisor** — DataDome回避、全言語フィルタ、ページネーション対応
- 📸 **ライブスクショ** — Gyazo連携で30秒おきにスクリーンショット撮影・表示
- ☁️ **Cloud Tasks並列化** — ジョブごとに別インスタンスで実行（最大10並列）
- 🖥 **リアルタイムUI** — 進捗・スクショ・インスタンス情報が自動更新
- 🛡 **ステルス機能** — Scrapling（browserforgeフィンガープリント、WebRTCブロック）
- 🔄 **自動リトライ** — 最大3回リトライ、Torプロキシ対応

## アーキテクチャ

```
ブラウザ → Cloud Run (FastAPI)
              ├─ POST /scrape → Firestore(queued) → Cloud Tasks
              │                                        ↓
              │                              POST /worker/run → 新インスタンス
              │                                        ↓
              │                              Scrapling (Playwright) → スクレイピング
              │                                        ↓
              │                              Firestore (結果保存)
              ├─ GET /jobs → ポーリング（2秒間隔）
              └─ GET /jobs/{id}/reviews → 結果取得
```

## ファイル構成

```
review-scraper/
├── main.py                  # FastAPIアプリ（エンドポイント定義、ジョブ管理）
├── config.py                # 設定値（タイムアウト、スクロール設定等）
├── models.py                # Pydanticモデル（ScrapeRequest, JobStatus等）
├── db.py                    # Firestore操作（ジョブCRUD、レビュー保存）
├── css_selectors.py         # CSSセレクタ定義（Google Maps/TripAdvisor）
├── deploy.sh                # Cloud Runデプロイスクリプト
├── Dockerfile               # コンテナ定義（Python + Chromium + Tor）
├── requirements.txt         # 依存パッケージ
│
├── scraper/
│   ├── google.py            # Google Mapsスクレイパー（StealthySession）
│   └── tripadvisor.py       # TripAdvisorスクレイパー（StealthyFetcher）
│
├── utils/
│   ├── gyazo.py             # Gyazoスクリーンショットアップロード
│   ├── tor.py               # Tor接続チェック・回線リニューアル
│   └── date_parser.py       # 日付パーサー
│
├── static/
│   ├── index.html           # フロントエンド（SPA、ページネーション付き）
│   ├── favicon.svg          # ファビコン
│   └── robots.txt           # 検索エンジンブロック
│
├── tests/
│   ├── conftest.py          # テストフィクスチャ（モックDB/スクレイパー）
│   ├── test_main.py         # ジョブ実行テスト（成功/リトライ/タイムアウト等）
│   ├── test_api.py          # APIエンドポイントテスト
│   ├── test_gyazo.py        # Gyazoアップロードテスト
│   ├── test_scraper_google.py      # Google URLパース、DOM抽出テスト
│   └── test_scraper_tripadvisor.py # TripAdvisorドメイン変換、レビュー解析テスト
│
├── scripts/
│   └── create-queue.sh      # Cloud Tasksキュー作成スクリプト
│
├── docs/
│   ├── SCRAPING_RULES.md    # スクレイピングルール
│   ├── scraping-knowledge.md # ナレッジベース
│   ├── fix-retry-asyncio.md # リトライ修正の技術記録
│   └── adr/                 # Architecture Decision Records
│
├── .githooks/
│   └── pre-commit           # pytest自動実行フック
│
├── CLAUDE.md                # 開発ルール（テスト方針、デプロイ手順等）
└── .env                     # 環境変数（GYAZO_ACCESS_TOKEN等）
```

## セットアップ

### 必要なもの

- Python 3.10+
- Google Cloud プロジェクト（Firestore, Cloud Run, Cloud Tasks）
- Gyazo APIトークン（スクリーンショット用、任意）

### ローカル実行

```bash
pip install -r requirements.txt
python -m playwright install chromium

# 環境変数設定
cp .env.example .env  # GYAZO_ACCESS_TOKEN等を設定

# 起動
uvicorn main:app --host 0.0.0.0 --port 8080
```

### デプロイ

```bash
# Cloud Tasksキュー作成（初回のみ）
bash scripts/create-queue.sh

# Cloud Runにデプロイ
bash deploy.sh
```

## API

| メソッド | パス | 説明 |
|---------|------|------|
| `POST` | `/scrape` | スクレイピングジョブ開始 |
| `GET` | `/jobs` | 全ジョブ一覧 |
| `GET` | `/jobs/{id}` | ジョブ詳細 |
| `GET` | `/jobs/{id}/reviews` | レビュー結果 |
| `GET` | `/jobs/{id}/logs` | ジョブログ |
| `POST` | `/jobs/{id}/cancel` | ジョブ停止 |
| `DELETE` | `/jobs/{id}` | ジョブ削除 |
| `POST` | `/worker/run` | ワーカー実行（Cloud Tasks用） |

### スクレイピング開始

```bash
curl -X POST https://your-service.run.app/scrape \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.google.com/maps/place/...", "source": "google"}'
```

## 設定値（config.py）

| 設定 | 値 | 説明 |
|------|-----|------|
| `JOB_TIMEOUT_SECONDS` | 1800 | ジョブタイムアウト（30分） |
| `GOOGLE_STALL_SECONDS` | 120 | スクロール停滞判定（120秒） |
| `GOOGLE_MAX_SCROLLS` | 2000 | 最大スクロール回数 |
| `MAX_OUTER_RETRIES` | 3 | 最大リトライ回数 |

## テスト

```bash
# 全テスト実行
pytest tests/ -q

# pre-commitフック設定
git config core.hooksPath .githooks
```

## 技術スタック

- **Backend**: FastAPI + Uvicorn
- **Scraping**: Scrapling (Playwright + browserforge)
- **Database**: Google Cloud Firestore
- **Queue**: Google Cloud Tasks
- **Hosting**: Google Cloud Run
- **Screenshots**: Gyazo API
- **Anti-detection**: Tor, fingerprint randomization, viewport randomization
