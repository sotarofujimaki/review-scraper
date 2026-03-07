# Architecture Decision Records (ADR)

意思決定ログ。なぜその選択をしたか、何を試して何が失敗したかを記録する。

## フォーマット

```
# ADR-XXXX: タイトル

**日付**: YYYY-MM-DD
**ステータス**: 承認 / 却下 / 廃止
**関連**: ADR-XXXX（あれば）

## コンテキスト
何が問題だったか。背景。

## 検討した選択肢
1. 選択肢A — メリット / デメリット
2. 選択肢B — メリット / デメリット

## 決定
何を選んだか。

## 試行錯誤（該当する場合）
実際に試したこと、失敗したこと、なぜ失敗したか。

## 結果
決定の影響。今後の注意点。
```

## 一覧

| ADR | タイトル | 日付 | ステータス |
|-----|---------|------|-----------|
| [0001](0001-tripadvisor-all-languages.md) | TripAdvisor全言語レビュー取得 | 2026-03-07 | 承認 |
| [0002](0002-google-maps-scroll-method.md) | Google Mapsスクロール方式 | 2026-03-07 | 承認 |
| [0003](0003-pagination-spa-navigation.md) | TripAdvisorページネーション方式 | 2026-03-07 | 承認 |
| [0004](0004-deploy-strategy.md) | Cloud Runデプロイ戦略 | 2026-03-07 | 承認 |
| [0005](0005-firestore-persistence.md) | Firestoreによるジョブ永続化 | 2026-03-07 | 承認 |
