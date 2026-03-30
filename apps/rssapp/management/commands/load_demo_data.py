"""
Load Japanese tech / gadget demo data: feeds, articles, tags, bookmarks,
and user states so every feature of the app is exercised.
"""

import hashlib
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.rssapp.models import Article, ArticleUserState, Bookmark, Feed, Tag

User = get_user_model()


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


# ── Feeds ────────────────────────────────────────────────────────────
FEEDS = [
    # (name, url, category, display_order)
    ("GIGAZINE", "https://gigazine.net/news/rss_2.0/", "テクノロジー", 1),
    (
        "ITmedia NEWS",
        "https://rss.itmedia.co.jp/rss/2.0/news_bursts.xml",
        "テクノロジー",
        2,
    ),
    ("Publickey", "https://www.publickey1.jp/atom.xml", "テクノロジー", 3),
    ("GIZMODO JAPAN", "https://www.gizmodo.jp/feed/", "ガジェット", 4),
    ("Engadget 日本版", "https://japanese.engadget.com/rss.xml", "ガジェット", 5),
    (
        "PC Watch",
        "https://pc.watch.impress.co.jp/data/rss/1.0/pcw/feed.rdf",
        "ガジェット",
        6,
    ),
    (
        "はてなブックマーク - テクノロジー",
        "https://b.hatena.ne.jp/hotentry/it.rss",
        "はてな",
        7,
    ),
    ("Zenn Trending", "https://zenn.dev/feed", "開発者ブログ", 8),
    ("Qiita Trending", "https://qiita.com/popular-items/feed", "開発者ブログ", 9),
    ("GitHub Blog", "https://github.blog/feed/", "開発者ブログ", 10),
]

# ── Sample articles per feed ─────────────────────────────────────────
# (title, link, summary, image_url, days_ago)
ARTICLES_BY_FEED: dict[str, list[tuple[str, str, str, str, int]]] = {
    "GIGAZINE": [
        (
            "AIが自動で論文を要約してくれるサービスが登場",
            "https://gigazine.net/news/20260328-ai-paper-summary/",
            "最新のLLMを活用した論文自動要約サービスが公開され、研究者の間で話題になっています。",
            "https://i.gzn.jp/img/2026/03/28/ai-paper/00.jpg",
            2,
        ),
        (
            "次世代バッテリー技術で充電時間が半分に",
            "https://gigazine.net/news/20260327-next-gen-battery/",
            "固体電池の新技術により、スマホの充電時間が従来の半分になる可能性が示されました。",
            "https://i.gzn.jp/img/2026/03/27/battery/00.jpg",
            3,
        ),
        (
            "量子コンピュータの商用利用がついに現実に",
            "https://gigazine.net/news/20260325-quantum-commercial/",
            "IBMとGoogleが量子コンピュータの商用サービスを正式に開始しました。",
            "https://i.gzn.jp/img/2026/03/25/quantum/00.jpg",
            5,
        ),
    ],
    "ITmedia NEWS": [
        (
            "Apple Vision Pro 2のスペックがリーク、軽量化が大幅に進化",
            "https://www.itmedia.co.jp/news/articles/2603/29/vision-pro-2.html",
            "次期Apple Vision Proは現行モデルから40%軽量化され、バッテリー持続時間も大幅に向上するとのこと。",
            "https://image.itmedia.co.jp/news/articles/2603/29/visionpro2.jpg",
            1,
        ),
        (
            "日本のスタートアップ、AIチップ開発で100億円調達",
            "https://www.itmedia.co.jp/news/articles/2603/28/ai-chip-startup.html",
            "東京拠点のスタートアップがAI専用チップ開発で大型資金調達に成功。",
            "https://image.itmedia.co.jp/news/articles/2603/28/ai-chip.jpg",
            2,
        ),
        (
            "Windows 12の新機能「AI Copilot+」の詳細が明らかに",
            "https://www.itmedia.co.jp/news/articles/2603/26/windows12.html",
            "Microsoftが次期Windows 12に搭載予定のAI機能の詳細を発表しました。",
            "https://image.itmedia.co.jp/news/articles/2603/26/win12.jpg",
            4,
        ),
    ],
    "Publickey": [
        (
            "Docker Desktop 5.0リリース、Wasm対応が正式版に",
            "https://www.publickey1.jp/blog/26/docker_desktop_50_wasm.html",
            "Docker Desktop 5.0でWebAssemblyコンテナが正式サポートされ、クラウドネイティブ開発の選択肢が広がります。",
            "",
            1,
        ),
        (
            "PostgreSQL 18の新機能まとめ",
            "https://www.publickey1.jp/blog/26/postgresql_18.html",
            "PostgreSQL 18ではJSONB型のパフォーマンスが大幅改善され、新たな分析関数も追加されました。",
            "",
            3,
        ),
        (
            "Kubernetes 1.32リリース、AIワークロード対応を強化",
            "https://www.publickey1.jp/blog/26/kubernetes_132.html",
            "GPUスケジューリングの改善とAIモデルサービングの最適化が大きなテーマです。",
            "",
            6,
        ),
    ],
    "GIZMODO JAPAN": [
        (
            "折りたたみスマホの新時代。Samsung Galaxy Z Fold 7レビュー",
            "https://www.gizmodo.jp/2026/03/galaxy-z-fold-7-review.html",
            "ついにペンの収納に対応したGalaxy Z Fold 7。完成度が一段と上がった折りたたみスマホの実力を検証。",
            "https://media.loom-app.com/gizmodo/dist/images/2026/03/fold7.jpg",
            1,
        ),
        (
            "Apple Watchで血糖値モニタリングが可能に？特許情報から読み解く",
            "https://www.gizmodo.jp/2026/03/apple-watch-glucose.html",
            "Appleが血糖値測定に関する新たな特許を取得。次世代Apple Watchへの搭載が期待されます。",
            "https://media.loom-app.com/gizmodo/dist/images/2026/03/glucose.jpg",
            3,
        ),
        (
            "最強のノイキャンイヤホンはどれだ？2026年春の比較テスト",
            "https://www.gizmodo.jp/2026/03/best-anc-earbuds-2026.html",
            "Sony、Apple、Boseの最新モデルを徹底比較。騒音カット性能、音質、装着感を評価しました。",
            "https://media.loom-app.com/gizmodo/dist/images/2026/03/anc.jpg",
            5,
        ),
    ],
    "Engadget 日本版": [
        (
            "Nintendo Switch 2の予約が開始、初回出荷は即完売の見込み",
            "https://japanese.engadget.com/gaming/switch2-preorder-2026.html",
            "任天堂が新型ゲーム機Switch 2の予約を開始。4K対応やDLSS技術の搭載が注目ポイント。",
            "https://s.yimg.com/os/engadget/2026/03/switch2.jpg",
            0,
        ),
        (
            "テスラのヒューマノイドロボット「Optimus Gen 3」が工場で稼働開始",
            "https://japanese.engadget.com/robotics/tesla-optimus-gen3.html",
            "テスラがOptimus Gen 3を自社工場に導入。人間の作業員と並んで組み立て作業を行っています。",
            "https://s.yimg.com/os/engadget/2026/03/optimus.jpg",
            2,
        ),
    ],
    "PC Watch": [
        (
            "Intel Arrow Lake-S Refresh レビュー：省電力と高性能の両立",
            "https://pc.watch.impress.co.jp/docs/topic/review/2026/arrowlake-s.html",
            "第15世代CoreプロセッサのRefreshモデルが登場。電力効率の改善度合いを検証します。",
            "https://pc.watch.impress.co.jp/img/pcw/docs/2026/arrowlake.jpg",
            1,
        ),
        (
            "RTX 5070 Ti 速攻レビュー：4070 Tiから買い換える価値はあるのか",
            "https://pc.watch.impress.co.jp/docs/topic/review/2026/rtx5070ti.html",
            "NVIDIAの最新ミドルハイGPU「RTX 5070 Ti」の性能を人気ゲームで検証。",
            "https://pc.watch.impress.co.jp/img/pcw/docs/2026/rtx5070ti.jpg",
            4,
        ),
    ],
    "はてなブックマーク - テクノロジー": [
        (
            "プログラマーが知っておくべきメモリの話",
            "https://example.com/hatena/memory-for-programmers",
            "スタック・ヒープの基礎からガベージコレクションの仕組みまで丁寧に解説した記事がバズっています。",
            "",
            1,
        ),
        (
            "大規模言語モデルのファインチューニング入門",
            "https://example.com/hatena/llm-finetuning-guide",
            "LLMのファインチューニングをゼロから学べるハンズオン記事。LoRAやQLoRAの実践例も紹介。",
            "",
            2,
        ),
    ],
    "Zenn Trending": [
        (
            "Rustで作るWebフレームワーク入門",
            "https://zenn.dev/example/articles/rust-web-framework",
            "Axumを使ったWebアプリケーション構築のチュートリアル。型安全なAPIの作り方を解説。",
            "https://res.cloudinary.com/zenn/image/upload/articles/rust-web.png",
            1,
        ),
        (
            "Next.js 15のServer Actionsを本番で使ってみた感想",
            "https://zenn.dev/example/articles/nextjs15-server-actions",
            "Server Actionsを実際のプロダクションで運用した知見と注意点をまとめました。",
            "https://res.cloudinary.com/zenn/image/upload/articles/nextjs15.png",
            3,
        ),
        (
            "TypeScript 6.0の新機能をキャッチアップ",
            "https://zenn.dev/example/articles/typescript-6-new-features",
            "TypeScript 6.0で追加された型推論の改善やパフォーマンス向上について解説。",
            "https://res.cloudinary.com/zenn/image/upload/articles/ts6.png",
            5,
        ),
    ],
    "Qiita Trending": [
        (
            "Pythonの型ヒント完全ガイド2026年版",
            "https://qiita.com/example/items/python-type-hints-2026",
            "Python 3.13の新機能も含めた型ヒントの包括的なガイド。mypyとpyrightの使い分けも解説。",
            "",
            0,
        ),
        (
            "GitHub Actionsで実現するCI/CDベストプラクティス",
            "https://qiita.com/example/items/github-actions-best-practices",
            "マトリクスビルド、キャッシュ戦略、セキュリティスキャンの設定例をまとめました。",
            "",
            2,
        ),
    ],
    "GitHub Blog": [
        (
            "GitHub Copilot Workspace: AI-powered development environments",
            "https://github.blog/2026-03-28-copilot-workspace-ga/",
            "GitHub Copilot Workspaceが正式リリース。AIがIssueからPull Requestまでを自動生成します。",
            "https://github.blog/wp-content/uploads/2026/03/copilot-workspace.png",
            2,
        ),
        (
            "Announcing GitHub Models: LLMs directly in your repository",
            "https://github.blog/2026-03-25-github-models/",
            "GitHubリポジトリから直接LLMモデルにアクセスし、アプリケーションに統合する新機能。",
            "https://github.blog/wp-content/uploads/2026/03/github-models.png",
            5,
        ),
    ],
}

# ── Tags ─────────────────────────────────────────────────────────────
TAGS = [
    # (name, color)
    ("AI", "#EF4444"),
    ("ガジェット", "#F59E0B"),
    ("プログラミング", "#10B981"),
    ("レビュー", "#6366F1"),
    ("ハードウェア", "#EC4899"),
    ("Web開発", "#3B82F6"),
    ("セキュリティ", "#8B5CF6"),
    ("ゲーム", "#14B8A6"),
    ("クラウド", "#F97316"),
    ("オープンソース", "#84CC16"),
]


class Command(BaseCommand):
    help = "日本のテック・ガジェット系デモデータを投入する"

    def handle(self, *args, **options):
        user = User.objects.first()
        if not user:
            self.stderr.write(
                "ユーザーが存在しません。先にcreatesuperuserを実行してください。"
            )
            return

        now = timezone.now()

        # ── Feeds & Articles ──────────────────────────────────────
        feed_objs: dict[str, Feed] = {}
        article_objs: list[Article] = []

        for name, url, category, order in FEEDS:
            feed, created = Feed.objects.update_or_create(
                url=url,
                defaults={
                    "name": name,
                    "category": category,
                    "display_order": order,
                    "is_active": True,
                },
            )
            feed_objs[name] = feed
            action = "作成" if created else "更新"
            self.stdout.write(f"  Feed {action}: {name}")

        for feed_name, articles in ARTICLES_BY_FEED.items():
            feed = feed_objs[feed_name]
            for title, link, summary, image_url, days_ago in articles:
                h = _hash(link)
                article, created = Article.objects.update_or_create(
                    hash=h,
                    defaults={
                        "feed": feed,
                        "title": title,
                        "link": link,
                        "normalized_link": link,
                        "guid": link,
                        "summary": summary,
                        "content": f"<p>{summary}</p>",
                        "image_url": image_url,
                        "published_at": now - timedelta(days=days_ago),
                    },
                )
                article_objs.append(article)
                if created:
                    self.stdout.write(f"    Article: {title}")

        self.stdout.write(self.style.SUCCESS(f"\n✓ {len(article_objs)} 記事を登録"))

        # ── Tags ──────────────────────────────────────────────────
        tag_objs: dict[str, Tag] = {}
        for name, color in TAGS:
            tag, _ = Tag.objects.get_or_create(
                user=user,
                name=name,
                defaults={"color": color},
            )
            tag_objs[name] = tag

        self.stdout.write(self.style.SUCCESS(f"✓ {len(tag_objs)} タグを登録"))

        # ── Bookmarks (with tags) ─────────────────────────────────
        BOOKMARKS = [
            {
                "title": "折りたたみスマホの新時代。Samsung Galaxy Z Fold 7レビュー",
                "url": "https://www.gizmodo.jp/2026/03/galaxy-z-fold-7-review.html",
                "description": "Galaxy Z Fold 7の詳細レビュー。折りたたみスマホの完成度がまた一段上がった。",
                "thumbnail_url": "https://images.unsplash.com/photo-1511707267537-b85faf00021e?w=400&h=250&fit=crop",
                "tags": ["ガジェット", "レビュー"],
            },
            {
                "title": "Rustで作るWebフレームワーク入門",
                "url": "https://zenn.dev/topics/rust",
                "description": "Rustを使ったWebフレームワーク開発。Axumなどの実装方法を学ぶ。",
                "thumbnail_url": "https://images.unsplash.com/photo-1517694712202-14dd9538aa97?w=400&h=250&fit=crop",
                "tags": ["プログラミング", "Web開発"],
            },
            {
                "title": "Pythonの型ヒント完全ガイド2026年版",
                "url": "https://qiita.com/search?q=python+type+hints",
                "description": "Python型ヒントの総合ガイド。mypy・pyrightの使い分けやベストプラクティスも網羅。",
                "thumbnail_url": "https://images.unsplash.com/photo-1515879218367-8466d910aaa4?w=400&h=250&fit=crop",
                "tags": ["プログラミング"],
            },
            {
                "title": "GitHub Copilot Workspace: AI-powered development environments",
                "url": "https://github.blog/",
                "description": "GitHub Copilot WorkspaceでIssueからPRまでAIが自動生成。開発ワークフローが大きく変わる。",
                "thumbnail_url": "https://images.unsplash.com/photo-1517694712202-14dd9538aa97?w=400&h=250&fit=crop",
                "tags": ["AI", "オープンソース"],
            },
            {
                "title": "Docker Desktop 5.0リリース、Wasm対応が正式版に",
                "url": "https://www.docker.com/blog/",
                "description": "WebAssemblyコンテナが正式サポート。クラウドネイティブの新しい選択肢。",
                "thumbnail_url": "https://images.unsplash.com/photo-1460925895917-aaf4b51c73a0?w=400&h=250&fit=crop",
                "tags": ["クラウド", "オープンソース"],
            },
            {
                "title": "最強のノイキャンイヤホンはどれだ？2026年春の比較テスト",
                "url": "https://www.gizmodo.jp/",
                "description": "Sony, Apple, Boseの最新ノイキャンイヤホンを徹底比較。",
                "thumbnail_url": "https://images.unsplash.com/photo-1487215078519-e21cc028cb29?w=400&h=250&fit=crop",
                "tags": ["ガジェット", "レビュー"],
            },
            {
                "title": "Intel Arrow Lake-S Refresh レビュー",
                "url": "https://pc.watch.impress.co.jp/",
                "description": "第15世代Coreプロセッサの実力を検証。省電力と性能の両立はいかに。",
                "thumbnail_url": "https://images.unsplash.com/photo-1505994427637-37f821ba912d?w=400&h=250&fit=crop",
                "tags": ["ハードウェア", "レビュー"],
            },
            {
                "title": "Nintendo Switch 2の予約が開始",
                "url": "https://www.engadget.com/",
                "description": "任天堂の新型ゲーム機、4K対応やDLSS搭載で話題に。",
                "thumbnail_url": "https://images.unsplash.com/photo-1612198188060-c7c2a3b66eae?w=400&h=250&fit=crop",
                "tags": ["ガジェット", "ゲーム"],
            },
            {
                "title": "大規模言語モデルのファインチューニング入門",
                "url": "https://zenn.dev/topics/machine-learning",
                "description": "LLMファインチューニングの基礎から実践まで。LoRA、QLoRAの使い方も紹介。",
                "thumbnail_url": "https://images.unsplash.com/photo-1655720828018-edd2daec9349?w=400&h=250&fit=crop",
                "tags": ["AI", "プログラミング"],
            },
            {
                "title": "Kubernetes 1.32リリース、AIワークロード対応を強化",
                "url": "https://kubernetes.io/blog/",
                "description": "GPUスケジューリングの改善やAIモデルサービングの最適化が目玉。",
                "thumbnail_url": "https://images.unsplash.com/photo-1633356122544-f134324ef6db?w=400&h=250&fit=crop",
                "tags": ["クラウド", "AI"],
            },
        ]

        bookmark_count = 0
        for bm_data in BOOKMARKS:
            # find matching article if exists
            source = Article.objects.filter(link=bm_data["url"]).first()
            bm, created = Bookmark.objects.update_or_create(
                user=user,
                url=bm_data["url"],
                defaults={
                    "title": bm_data["title"],
                    "description": bm_data["description"],
                    "thumbnail_url": bm_data["thumbnail_url"],
                    "source_article": source,
                },
            )
            bm.tags.set([tag_objs[t] for t in bm_data["tags"]])
            bookmark_count += 1

        self.stdout.write(self.style.SUCCESS(f"✓ {bookmark_count} ブックマークを登録"))

        # ── ArticleUserState ──────────────────────────────────────
        # Mark some articles as read, favorited, or read-later
        states_created = 0
        for i, article in enumerate(article_objs):
            is_read = i % 3 == 0  # every 3rd article read
            is_fav = i % 5 == 0  # every 5th article favorited
            is_read_later = i % 4 == 1  # every 4th article read-later

            if is_read or is_fav or is_read_later:
                ArticleUserState.objects.update_or_create(
                    user=user,
                    article=article,
                    defaults={
                        "is_read": is_read,
                        "is_favorite": is_fav,
                        "is_read_later": is_read_later,
                    },
                )
                states_created += 1

        self.stdout.write(self.style.SUCCESS(f"✓ {states_created} ユーザー状態を登録"))
        self.stdout.write(self.style.SUCCESS("\nデモデータの投入が完了しました！"))
