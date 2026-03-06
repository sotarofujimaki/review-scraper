# Review Scraper 改善設計書 v2

## 対象ファイル
- scraper/google.py
- scraper/tripadvisor.py
- config.py

## 1. Google Maps (`scraper/google.py`)

### 1a. StealthySession kwargs強化
`_start_session` 内の `session_kwargs` に以下を追加:
```python
session_kwargs = dict(
    headless=True,
    locale="ja-JP",
    timezone_id="Asia/Tokyo",
    user_data_dir=profile_dir,
    disable_resources=True,      # 追加: font/image/media等を自動ブロック
    hide_canvas=True,            # 追加: Canvas fingerprint ノイズ
    block_webrtc=True,           # 追加: WebRTC IP漏れ防止
    google_search=True,          # 追加: Googleリファラー自動設定
    blocked_domains={"doubleclick.net", "googlesyndication.com", "googleadservices.com", "google-analytics.com", "googletagmanager.com"},
)
```
- `disable_resources=True` を使うので、手動の `page.route("**/*.{png,jpg,...}", lambda route: route.abort())` は削除

### 1b. Stage 2スキップ
`_collect_all_reviews` のスタル回復で:
- Stage 1（ページリフレッシュ）失敗後、Stage 2をスキップしてすぐStage 3（Tor）へ
- Stage 2は同じIPなので意味がない
- `_try_stage2_recovery` 関数は残すが、呼び出し箇所をコメントアウトまたは削除
- recovery_stage の値を調整（1→3にジャンプ）

### 1c. カウンタリセット防止
回復中の `progress_callback(0, ...)` を `progress_callback(len(all_reviews), ...)` に変更。
`_try_stage1_recovery`, `_try_stage2_recovery`, `_try_stage3_recovery` 内の progress_callback 呼び出しで、第1引数にall_reviewsの件数を渡す。
→ all_reviewsを引数に追加するか、len(saved_ids)を使う

### 1d. 部分成功
全Stage失敗で終了する際、`all_reviews` が空でなければ正常終了扱いで返す（例外を投げない）。
現在のコード末尾で `raise RuntimeError` している箇所を、`all_reviews` があれば `return all_reviews` に変更。

## 2. TripAdvisor (`scraper/tripadvisor.py`)

### 2a. StealthyFetcher kwargs強化
`fetch_kwargs` に追加:
```python
fetch_kwargs = dict(
    headless=True,
    network_idle=True,
    google_search=True,
    page_action=action_fn,
    wait=5,
    hide_canvas=True,           # 追加
    block_webrtc=True,          # 追加
    disable_resources=True,     # 追加
    timezone_id="Asia/Tokyo",   # 追加
    locale="ja-JP",             # 追加
    blocked_domains={"doubleclick.net", "googlesyndication.com", "google-analytics.com", "googletagmanager.com", "facebook.com", "facebook.net"},
)
```

### 2b. 試行順序変更
現在: 試行1=直接, 試行2-5=Tor
変更: 
- 試行1: 直接 + google_search=True（現状通り）
- 試行2: 直接 + google_search=False（リファラーなし。google_searchが逆効果の場合）
- 試行3-5: Tor + google_search=True

`attempt` の値に応じて `google_search` と `proxy` を切り替える。

### 2c. 6件→0件バグ修正
`5884746f` で6件検出 → 0件完了。原因調査:
- `make_action` 内の `_parse_review_card` が全カードでNone返している可能性
- `rsc(new_batch)` が呼ばれているか確認
- **デバッグログ追加**: `_parse_review_card` でパース失敗時に progress_callback でログ出力
  - `pcb(len(all_reviews), f"パース失敗: author={author}, rating={rating}, comment={comment[:20]}")`
- `_parse_review_card` の戻り値条件: `if not comment and not rating: return None` → ratingだけでもOKなはず
- **最後の `res["reviews"] = all_reviews` の前に、new_count==0で即breakしてる可能性**
  → 1ページ目で new_count > 0 だが < 15 → `break` → `res["reviews"] = all_reviews` は実行される → OK
  → 問題は `rsc(new_batch)` が呼ばれた後、`res["reviews"]` にもデータがあるのにmain.pyで `len(reviews)` が0になること
  → **`scrape_tripadvisor_reviews` の戻り値は `result["reviews"]`** → これが空なら問題
  → `make_action` はクロージャで `res["reviews"] = all_reviews` をセット → OK
  → **可能性: `new_batch` は作られたが `all_reviews` に `append` されてない**
  → コードを確認して `all_reviews.append(review)` と `new_batch.append(review)` の両方があるか確認

**実際のコード確認が必要。** `new_batch` を使うように変更した際に `all_reviews.append` が抜けてないか要チェック。

## 3. config.py

以下を追加:
```python
# Blocked ad/tracking domains
BLOCKED_DOMAINS_GOOGLE = {"doubleclick.net", "googlesyndication.com", "googleadservices.com", "google-analytics.com", "googletagmanager.com"}
BLOCKED_DOMAINS_TA = {"doubleclick.net", "googlesyndication.com", "google-analytics.com", "googletagmanager.com", "facebook.com", "facebook.net"}
```

## 制約
- `python3 -c "from scraper.google import scrape_google_reviews; from scraper.tripadvisor import scrape_tripadvisor_reviews; from main import app; print('OK')"` で確認
- git commit & push
- デプロイしない
