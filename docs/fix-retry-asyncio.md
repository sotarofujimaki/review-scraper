# Fix: Retry asyncio衝突 + テスト追加

## 問題
1. `_run_scrape()` が `asyncio.to_thread()` でスクレイパーを実行
2. 失敗時に `httpx.post("/jobs/{id}/retry")` で自己呼び出し
3. concurrency=1 で自己HTTPリクエストがデッドロック or 別インスタンスへ
4. Playwright Sync API が asyncio ループ内で衝突

## 解決策
HTTPベースの自己リトライを廃止 → `_run_scrape()` 内で直接リトライループ

## テストカバレッジ
- リトライロジック（成功/0件/例外/タイムアウト）
- on_progress Gyazo URL抽出
- キャンセル検出
- Gyazo upload成功/失敗

## テスト方針（プロジェクト共通）
- **新機能・バグ修正のたびにテストを追加する**（都度足す方針）
- 一括で全カバレッジを目指さない。変更したコードに関連するテストを書く
- 全てmock（ブラウザ/Firestore不要）
- `python -m pytest tests/ -v` で実行
