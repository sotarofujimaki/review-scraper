# ADR-0004: Cloud Runデプロイ戦略

**日付**: 2026-03-07
**ステータス**: 承認

## コンテキスト

`gcloud run deploy --source` はソースハッシュベースのキャッシュを使用するため、依存関係やDockerfileの変更が反映されない場合がある。

## 検討した選択肢

### 1. `gcloud run deploy --source .`
- ❌ ソースハッシュが同じだとキャッシュされたイメージが使われる
- ❌ コード変更したのに古いコードが動く事象が発生

### 2. `gcloud builds submit --tag <unique>` + `gcloud run deploy --image`
- ✅ タイムスタンプベースのユニークタグで毎回新規ビルド
- ✅ トラフィック切替も明示的に制御可能

## 決定

**選択肢2**: `deploy.sh` スクリプトで統一。

```bash
# deploy.sh のフロー
1. .build-timestamp 更新
2. git add -A && git commit && git push
3. gcloud builds submit --tag gcr.io/$PROJECT/review-scraper:v$TIMESTAMP
4. gcloud run deploy --image gcr.io/$PROJECT/review-scraper:v$TIMESTAMP
5. gcloud run services update-traffic --to-revisions=LATEST=100
```

## 結果

- 90+リビジョンを問題なくデプロイ
- キャッシュ問題は完全解消
