# ADR-0001: TripAdvisor全言語レビュー取得

**日付**: 2026-03-07
**ステータス**: 承認

## コンテキスト

TripAdvisorはブラウザのlocale/ドメインに基づいて言語フィルタを自動適用する。
- `.com` → English-onlyフィルタ（`Filters (1)` 表示）
- `.jp` → Japanese-onlyフィルタ（フィルタUIなし）
- `.co.uk` → English-onlyフィルタ

鞠智の例: 全41件のうち `.com` では6件、`.jp` では18件しか表示されない。

## 検討した選択肢

### 1. URLパラメータ `filterLang=ALL`
- ❌ TripAdvisorのSPAリダイレクトでパラメータが除去される
- gotoしてもURL上から消える

### 2. `.com` → `.jp` ドメイン変換
- ✅ 日本語レビュー18件は取得可能
- ❌ 英語・中国語・韓国語レビューは表示されない
- ❌ 全言語取得には不十分

### 3. Filtersモーダルで「All languages」を選択
- ✅ 全41件取得可能
- ⚠️ フィルタモーダルを開く操作が不安定（成功率〜50%）
- ⚠️ Brazeマーケティングモーダルがオーバーレイとして干渉

### 4. 複数ドメイン（`.com` + `.jp`）からスクレイプして統合
- ❌ 重複排除が複雑
- ❌ 中国語・韓国語のドメインも必要

## 決定

**選択肢3**: `.com`ドメインでFiltersモーダルを操作して「All languages」を選択する。
フィルタ適用失敗時は `FILTER_RETRY` でセッション全体をリトライ（最大5回）。

## 試行錯誤

### フィルタモーダルを開く方法
| 方法 | 結果 |
|------|------|
| `filter_btn.click()` (Playwright) | ❌ Brazeオーバーレイが`pointer-events`をインターセプト → 30sタイムアウト |
| `filter_btn.click(force=True)` (Playwright) | ❌ `make_action`クロージャ内では`[role="dialog"]`が検出されない（直接テストでは成功） |
| `page.evaluate(() => fb.click())` (JS native) | ❌ 同上 |
| `fb.dispatchEvent(new MouseEvent('click', {bubbles:true}))` | ✅ 成功率〜50%。Brazeバイパス可能 |

### `make_action`クロージャ内でモーダルが開かない問題
**原因**: 不明。直接`page_action`で同じコードを書くと100%成功するが、`make_action`で生成されたクロージャ内では`dispatchEvent`後に`[role="dialog"]`が検出されない場合がある。

**対策**: フィルタ失敗→リトライで対応。50%成功率 × 5回リトライ = 97%の成功率。

### English解除後の「All languages」選択
- `English`ボタンは`<button>`要素 → Playwright `click(force=True)` で解除可能
- 解除後に「All languages」「Japanese」「Chinese」等の選択肢が`role="option"`として出現
- `All languages`の`role="option"`をPlaywright `click(force=True)` で選択
- 最後に`Apply`ボタンをクリック

### Braze除去
```javascript
document.querySelectorAll('.ab-iam-root, iframe[title="Modal Message"]').forEach(el => el.remove());
```
フィルタクリック前後で2回実行する必要がある（再出現するため）。

## 結果

- 鞠智: 6件 → **41件**（JP:21 / KR:9 / CN:7 / EN:4）
- フィルタ操作は不安定だがリトライで実用的
- ページネーション時のフィルタ維持は別ADR（ADR-0003）で対応
