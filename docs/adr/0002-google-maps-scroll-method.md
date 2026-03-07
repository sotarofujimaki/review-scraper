# ADR-0002: Google Mapsスクロール方式

**日付**: 2026-03-07
**ステータス**: 承認

## コンテキスト

Google Mapsのレビューは無限スクロールで読み込まれる。スクロール方式によってボット判定の有無が変わる。

## 検討した選択肢

### 1. `scrollTop = scrollHeight`（JavaScript代入）
- ❌ ボット判定される → 10-15件で読み込み停止
- 高速だがGoogle側で検出

### 2. `mouse.wheel(0, 800)`（Playwrightマウスホイール）
- ✅ 人間的なスクロールとして扱われる
- ❌ Headless Cloud Run環境ではビューポートの問題でターゲット要素を外す場合がある

### 3. `scrollTop` + `mouse.wheel` 併用
- ✅ `scrollTop`でコンテナを確実にスクロール + `mouse.wheel`で人間的なイベントを発生
- Headless/Head付きの両方で動作

## 決定

**選択肢3**: `scrollTop`でコンテナスクロール + `mouse.wheel`でヒューマンイベント併用。

## 試行錯誤

- ローカル（ヘッド付き）: `mouse.wheel`単体で焼肉コミコム15/15件、渋谷プロパティタワー68/68件確認
- Cloud Run（headless）: `mouse.wheel`単体でミライザカ10件のみ → ビューポート問題
- 併用方式でCloud Run検証中

## 結果

- ローカルでは全件取得を確認
- Cloud RunではGCP IPのレート制限もあり、スクロール方式だけでは解決しない場合がある
- スクロール停止 = 取得分で完了（無限リカバリーは行わない）
