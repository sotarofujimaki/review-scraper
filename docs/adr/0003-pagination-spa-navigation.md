# ADR-0003: TripAdvisorページネーション方式

**日付**: 2026-03-07
**ステータス**: 承認
**関連**: ADR-0001

## コンテキスト

TripAdvisorの「All languages」フィルタ適用後、次ページへの遷移でフィルタ状態を維持する必要がある。

## 検討した選択肢

### 1. `page.goto(url + "?filterLang=ALL")` でページ遷移
- ❌ フィルタがリセットされる（`filterLang`パラメータはSPAに無視される）
- ❌ `-or15-` オフセット付きURLでもフィルタなしのページ1が表示される

### 2. `page.goto(href)` + フィルタ再適用
- ❌ フィルタ再適用でページ1に戻る（フィルタ変更 = ページリセット）

### 3. Playwright `nxt.click(force=True)`
- ❌ `make_action`クロージャ内ではSPA遷移が発火しない（DOMが更新されない）
- 直接テストでは成功するが、スクレイパー内では失敗

### 4. JS native `a.click()`
- ✅ SPA遷移が正常に発火（フィルタ状態維持 + DOMが新ページに更新）
- React/SPAのイベントハンドラがJS native clickで発火する

## 決定

**選択肢4**: `page.evaluate(() => { const a = document.querySelector('a[aria-label*="Next"]'); if (a) a.click(); })` でSPA内ページ遷移。

## 試行錯誤

### なぜPlaywright `click()` と JS `click()` で結果が違うのか

| 方法 | SPA遷移 | 備考 |
|------|---------|------|
| `element.click()` (Playwright, no force) | ❌ | Brazeオーバーレイでタイムアウト |
| `element.click(force=True)` (Playwright) | ❌ | DOM更新されず（`make_action`内） |
| `page.evaluate(() => a.click())` (JS native) | ✅ | Reactのイベントハンドラが発火 |
| `a.dispatchEvent(new MouseEvent('click'))` | 未検証 | — |

**推測**: Playwright の `force=True` click はブラウザの合成イベントとして処理され、Reactの合成イベントシステム（SyntheticEvent）と相性が悪い。JS native `click()` はブラウザネイティブのclickイベントを発生させ、Reactが正常にキャッチする。

## 結果

- 鞠智: 15 + 15 + 11 = 41件（3ページ全取得）
- フィルタ状態がページ間で維持される
- 「次へ」ボタンがなくなったら最終ページ
