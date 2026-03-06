# スクレイピング知見まとめ

## Google Maps

### スクロール方式
- ❌ `scrollTop = scrollHeight` → ボット判定される。10-15件で読み込み停止
- ✅ `mouse.wheel(0, 800)` → 人間的なスクロールとして扱われる。全件取得可能
- レビューパネル (`div.m6QErb.DxyBCb`) にhoverしてからwheel

### タブ検出
- `button[role="tab"]` でタブ一覧取得
- テキストに「クチコミ」を含むタブをクリック
- タブ数ではなくタブ名で判定（数はURL/カテゴリで変動）

### Cookie ウォームアップ
- Google Maps SPAは `google.com` に先にアクセスしてCookieを取得する必要がある
- `NID`, `AEC` が主要Cookie
- Cookie不足でもページ読み込みは試行する（なくても動くケースあり）

### ソート
- 「新しい順」ソートはメニューボタンクリック → オプション選択
- ソート後にレビュー再読み込みが走るので `wait_for_selector` で待機

### ブラウザプロファイル
- リトライごとに新しいプロファイル (`/tmp/google-profiles/{uuid}`) を作成
- SingletonLock競合を防ぐ
- `disable_resources=True` は使わない（Google Maps SPAのスタイルシートが壊れる）

### レート制限
- GCP IPはGoogleに認識されやすい → 直接接続で試行4回目以降にTor
- Tor経由だとSPAレンダリング不可（タブ0個）→ 直接優先が正解
- スクロール停止 = 取れた分で完了（無限に待たない）

### Scrapling
- `StealthyFetcher.fetch(page_action=...)` ではなく `StealthySession` を直接使う
- `page_action` だとGoogle Maps SPAのレビュータブがレンダリングされない
- `hide_canvas=True`, `block_webrtc=True` でフィンガープリント対策

## TripAdvisor

### CAPTCHA (DataDome)
- `StealthyFetcher.fetch(google_search=True, page_action=action_fn)` で回避
- `google_search=True` → Google検索リファラ経由でアクセス
- `page_action` で直接Playwrightページを操作

### パーサー
- Rating: SVG内の `<title>` 要素 → `inner_html()` から正規表現で抽出
  - `<title>5 of 5 bubbles</title>` or `<title>バブル評価 5 段階中 3</title>`
  - `query_selector_all("title")` ではSVG内のtitleが取れない
- Date: テキストから `Feb 2025` or `2024年3月` を抽出 → ISO変換
- review_id: `ShowUserReviews` リンク or `/Profile/` URLからフォールバック
- Author: `a.BMQDV.ukgoS` セレクタ

### ページネーション
- 1ページ15件。15件未満 = 最終ページ
- `?filterLang=ALL` で全言語取得

### クロージャの注意
- `page_action` 内のクロージャに必要な変数を全て渡すこと
- `make_action(base, pcb, rsc, res, st)` — `rsc`（callback）を忘れると `NameError`

## Cloud Run デプロイ

### キャッシュ問題
- `gcloud run deploy --source` はソースハッシュでイメージをキャッシュ → 変更が反映されない
- **恒久対策**: `gcloud builds submit --no-cache --tag <unique>` → `gcloud run deploy --image` → `update-traffic`
- `--source` は使わない

### トラフィック切替
- 新リビジョンを作っても自動でトラフィックが切り替わらないケースがある
- `gcloud run services update-traffic --to-revisions=<latest>=100` で強制切替

### Torの扱い
- Cloud Run上でTor動作確認済み（Dockerfile内でインストール）
- ただしGoogle Maps/TripAdvisorともにTor出口ノードはブロックされやすい
- 直接優先 + Torフォールバックが実用的

## 一般的なスクレイピングTips

### page.evaluate timeout
- Scraplingのラッパー経由だと `timeout` パラメータが使えない場合がある
- ハング防止には外側でタイムアウト管理

### メモリ管理
- `_cleanup_heavy_elements()` でDOM内の画像/SVG/canvasを定期削除
- 1000件超えるとブラウザがクラッシュしやすい（4GiB推奨）
- レビューは `review_save_callback` でインクリメンタルに保存
