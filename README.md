# Feedee

Django + Go で構成された RSS リーダー & ブックマークマネージャー。

## 機能

### RSS リーダー

- フィード購読・カテゴリ分け・ドラッグ並び替え
- 記事一覧（検索・フィルタ・ページネーション）
- リーダービュー（キーボードショートカット対応）
- 記事状態管理（既読・お気に入り・あとで読む）
- 一括既読機能

### ブックマーク

- URL からメタデータ自動取得（タイトル・説明・サムネイル）
- タグ管理（カラーコード付き）
- RSS 記事からのブックマーク作成

### 設定

- フィード管理・タグ管理・アカウント設定を統合 Settings ページで管理
- ユーザーごとの表示設定（ソート順・ページあたり件数）

### インフラ

- Go ワーカーによる並行 RSS フェッチ（バッチ内重複排除・リトライ付き）
- Token ベース API 認証（ワーカー ↔ Django 間）
- 本番環境: Nginx + Gunicorn + PostgreSQL（Docker Compose）
- 開発環境: SQLite + Django runserver（Docker Compose）

## 技術スタック

| レイヤー | 技術 |
|---------|------|
| バックエンド | Django 5.2 / Django REST Framework 3.17 |
| フロントエンド | Django テンプレート / Tailwind CSS (CDN) |
| RSS ワーカー | Go 1.22 |
| DB（開発） | SQLite |
| DB（本番） | PostgreSQL 16 |
| Web サーバー | Nginx 1.27 + Gunicorn |
| パッケージ管理 | uv (Python) / Go modules |
| HTML サニタイズ | nh3 (Rust ベース) |

## プロジェクト構成

```
config/              Django 設定・URL ルート
  settings/
    base.py          共通設定
    development.py   開発環境設定
    production.py    本番環境設定
apps/rssapp/         メインアプリケーション
  models.py          Feed, Article, ArticleUserState, UserProfile, Tag, Bookmark
  views.py           Web ビュー + API ビュー
  serializers.py     DRF シリアライザ
  forms.py           Django フォーム
  urls.py            Web URL ルーティング
  api_urls.py        API URL ルーティング
  utils.py           URL 正規化・ハッシュ生成・メタデータ取得
  context_processors.py  サイドバー用コンテキスト
templates/           HTML テンプレート
  base.html          レイアウト（サイドバー・ヘッダー）
  rss/               RSS 関連画面
  bookmarks/         ブックマーク関連画面
static/css/          カスタム CSS
rss_worker/          Go RSS ワーカー
  main.go            エントリーポイント
  Dockerfile         ワーカー用 Docker イメージ
docker/
  entrypoint.sh      本番起動スクリプト
  nginx.conf         Nginx 設定
```

## セットアップ

### 開発環境（ローカル）

```bash
# 依存関係インストール
uv sync

# DB マイグレーション
uv run python manage.py migrate

# スーパーユーザー作成
uv run python manage.py createsuperuser

# Django 起動
uv run python manage.py runserver

# RSS ワーカー起動（別ターミナル）
go run rss_worker/main.go
```

### 開発環境（Docker）

```bash
make up       # バックグラウンド起動
make logs     # ログ確認
make down     # 停止
```

### 本番環境

```bash
# .env ファイルを作成（必須項目）
cp .env.example .env
# DJANGO_SECRET_KEY, POSTGRES_PASSWORD, WORKER_API_TOKEN を設定

make prod-up       # 起動
make prod-migrate  # マイグレーション
make prod-logs     # ログ確認
```

## API エンドポイント

すべての API は Token 認証が必要（`Authorization: Token <token>`）。

| メソッド | パス | 説明 |
|---------|------|------|
| `GET` | `/api/feeds/` | アクティブなフィード一覧 |
| `POST` | `/api/feeds/reorder/` | フィード並び順更新 |
| `POST` | `/api/articles/ingest/` | 記事取り込み（ワーカー用） |
| `GET/PATCH` | `/api/articles/<id>/state/` | 記事のユーザー状態取得・更新 |
| `POST` | `/api/bookmarks/fetch-metadata/` | URL メタデータ取得 |

## Web ページ

| パス | 説明 |
|------|------|
| `/` | ダッシュボード（全記事一覧） |
| `/feeds/<id>/` | フィード別記事一覧 |
| `/articles/<id>/reader/` | 記事リーダー |
| `/bookmarks/` | ブックマーク一覧 |
| `/bookmarks/add/` | ブックマーク追加 |
| `/settings/` | 設定（Feeds タブ） |
| `/settings/tags/` | 設定（Tags タブ） |
| `/settings/account/` | 設定（Account タブ） |

## 環境変数

### Django

| 変数名 | デフォルト | 説明 |
|--------|-----------|------|
| `DJANGO_SECRET_KEY` | (開発用キー) | Secret key（本番では必ず変更） |
| `DJANGO_DEBUG` | `True` | デバッグモード |
| `DJANGO_ALLOWED_HOSTS` | `*` | 許可ホスト（カンマ区切り） |
| `DJANGO_SETTINGS_MODULE` | — | 設定モジュールパス |

### 本番のみ

| 変数名 | デフォルト | 説明 |
|--------|-----------|------|
| `POSTGRES_DB` | `feedee` | DB 名 |
| `POSTGRES_USER` | `feedee` | DB ユーザー |
| `POSTGRES_PASSWORD` | (必須) | DB パスワード |
| `GUNICORN_WORKERS` | `3` | Gunicorn ワーカー数 |
| `NGINX_PORT` | `80` | Nginx ポート |

### RSS ワーカー

| 変数名 | デフォルト | 説明 |
|--------|-----------|------|
| `DJANGO_BASE_URL` | `http://127.0.0.1:8000` | Django API の URL |
| `WORKER_API_TOKEN` | — | API 認証トークン（本番では必須） |
| `HTTP_TIMEOUT_SECONDS` | `15` | HTTP タイムアウト（秒） |
| `MAX_CONCURRENCY` | `8` | 並行フェッチ数 |
| `INGEST_MAX_RETRY` | `3` | 取り込みリトライ回数 |
| `INGEST_INITIAL_BACKOFF_SECONDS` | `1` | リトライ初期待機時間（秒） |

## Make コマンド

```
make dev            開発環境起動（フォアグラウンド）
make up             開発環境起動（バックグラウンド）
make down           開発環境停止
make logs           開発ログ表示
make test           テスト実行
make migrate        マイグレーション実行
make shell          Django シェル
make worker         RSS ワーカーをローカル実行

make prod-up        本番環境起動
make prod-down      本番環境停止
make prod-logs      本番ログ表示
make prod-migrate   本番マイグレーション
make prod-shell     本番 Django シェル

make backup-dev     開発 DB バックアップ
make backup-prod    本番 DB バックアップ
make restore-dev    開発 DB リストア
make restore-prod   本番 DB リストア
```
