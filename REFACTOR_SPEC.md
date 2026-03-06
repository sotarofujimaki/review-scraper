# Review Scraper リファクタリング設計書

## 現状の問題点

1. **設定のハードコード** — タイムアウト、リトライ数がコード内に散在（マジックナンバー）
2. **未使用コード** — `_csv_response`関数、`csv`/`io`/`StreamingResponse` import が残存
3. **型安全性なし** — Review が dict で流れている
4. **重複import** — `import re` がループ内で複数回、`from datetime import ...` がインライン
5. **__pycache__ が git に入っている**
6. **Tor判定ロジック重複** — google.py と tripadvisor.py で同じ socket チェック
7. **models/enum が main.py 内に定義** — 他ファイルから参照しづらい

## リファクタリング内容

### 1. `config.py` — 設定集約（新規作成）
すべてのマジックナンバーを集約:
```python
MAX_RETRIES = 5
JOB_TIMEOUT_SECONDS = 600
STALE_JOB_MINUTES = 30
DUPLICATE_URL_MINUTES = 5
GOOGLE_PAGE_TIMEOUT_MS = 90_000
GOOGLE_WARMUP_TIMEOUT_MS = 30_000
GOOGLE_STALL_SECONDS = 60
GOOGLE_NO_NEW_THRESHOLD = 5
TA_PAGE_TIMEOUT_MS = 30_000
TA_REVIEWS_PER_PAGE = 15
TA_MAX_PAGES = 30
TOR_PROXY_URL = "socks5://127.0.0.1:9050"
GOOGLE_PROFILE_BASE = "/tmp/google-profiles"
FIRESTORE_COLLECTION = "scrape_jobs"
FIRESTORE_BATCH_SIZE = 450
```

### 2. `models.py` — Pydantic モデル（新規作成）
```python
class Source(str, Enum): google, tripadvisor
class ScrapeRequest(BaseModel): url, source
class Review(BaseModel): review_id, author, rating, posted_at, comment
class JobStatus(str, Enum): running, done, failed
```

### 3. `utils/tor.py` — Tor ユーティリティ（新規作成）
google.py/tripadvisor.py 共通のTor接続チェック・回線更新を集約:
```python
def renew_circuit() -> bool
def get_proxy_for_retry(retry: int) -> str | None
def is_tor_available() -> bool
```

### 4. `main.py` — リファクタ
- Source, ScrapeRequest を models.py から import
- config から定数を import
- `_csv_response` 関数と関連 import 削除
- `_run_scrape` 内の scraper 選択を簡潔に
- `from datetime import ...` をトップレベルに

### 5. `db.py` — リファクタ
- config.FIRESTORE_COLLECTION, FIRESTORE_BATCH_SIZE を使用
- `from datetime import ...` をトップレベルに統一

### 6. `scraper/google.py` — リファクタ
- config からタイムアウト値を import
- `utils.tor` から Tor 関数を import（ローカル定義削除）
- `import re` をトップレベルに統一（ループ内の重複削除）
- `import os, uuid` をトップレベルに
- 不要な `import shutil` 重複削除

### 7. `scraper/tripadvisor.py` — リファクタ
- config からタイムアウト値を import
- `utils.tor` から Tor 関数を import
- `import re` の重複 import 削除
- `import socket` のインライン削除（tor.py に移動）
- TripAdvisor の `_parse_review_card` 内の author/comment セレクタを css_selectors.py のものを使う（まだハードコードされてる箇所がある）

### 8. `.gitignore` — 追加
```
__pycache__/
*.pyc
.env
```
git rm --cached で既存の __pycache__ を除外。

## 注意事項
- **動作を変えない** — ロジックの変更なし、構造のみ
- **テスト** — import エラーがないことを `python3 -c "from scraper.google import scrape_google_reviews; from scraper.tripadvisor import scrape_tripadvisor_reviews; from main import app; print('OK')"` で確認
- **既に作成済みのファイル** — `config.py`, `models.py`, `.gitignore` は途中まで作成済み。内容を確認して不足分を補完
- **main.py** — 途中まで書き換え済み（新版が存在する）。動作確認が必要
- **デプロイしない** — 完了後に宗太郎さんに確認を取る
