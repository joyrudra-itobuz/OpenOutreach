from __future__ import annotations

from dataclasses import dataclass

from linkedin.actions.comment_origins import (
    _normalize_post_url,
    candidate_activity_urls,
    collect_comment_origins,
    extract_original_post_urls,
)


@dataclass
class _FakeLink:
    href: str

    def get_attribute(self, name: str):
        return self.href if name == "href" else None


class _FakeLocator:
    def __init__(self, hrefs: list[str]):
        self._hrefs = hrefs

    def all(self):
        return [_FakeLink(href) for href in self._hrefs]


class _FakePage:
    def __init__(self, url: str, hrefs: list[str]):
        self.url = url
        self._hrefs = hrefs

    def locator(self, selector: str):
        return _FakeLocator(self._hrefs)

    def goto(self, url: str, wait_until: str = "domcontentloaded"):
        self.url = url
        return None


class _FakeSession:
    def __init__(self, page: _FakePage):
        self.page = page

    def ensure_browser(self):
        return None

    def wait(self, *args, **kwargs):
        return None


def test_candidate_activity_urls():
    urls = candidate_activity_urls(
        "https://www.linkedin.com/in/jane-doe/?trk=foo",
    )
    assert urls == [
        "https://www.linkedin.com/in/jane-doe/recent-activity/comments/",
        "https://www.linkedin.com/in/jane-doe/recent-activity/all/",
        "https://www.linkedin.com/in/jane-doe/recent-activity/posts/",
    ]


def test_normalize_post_url_removes_tracking_and_keeps_linkedin_posts():
    url = _normalize_post_url(
        "https://www.linkedin.com/in/jane-doe/recent-activity/comments/",
        "/feed/update/urn:li:activity:1234567890/?trk=foo",
    )
    assert url == (
        "https://www.linkedin.com/feed/update/urn:li:activity:1234567890/"
    )


def test_extract_original_post_urls_deduplicates_and_limits():
    page = _FakePage(
        "https://www.linkedin.com/in/jane-doe/recent-activity/comments/",
        [
            "/feed/update/urn:li:activity:1/?trk=foo",
            "/feed/update/urn:li:activity:1/?trk=bar",
            "/posts/example-2/?trk=baz",
        ],
    )

    urls = extract_original_post_urls(page, limit=10)
    assert urls == [
        "https://www.linkedin.com/feed/update/urn:li:activity:1/",
        "https://www.linkedin.com/posts/example-2/",
    ]


def test_collect_comment_origins_returns_payload(monkeypatch):
    page = _FakePage(
        "https://www.linkedin.com/in/jane-doe/recent-activity/comments/",
        ["/feed/update/urn:li:activity:42/?trk=foo"],
    )
    session = _FakeSession(page)

    def fake_goto_page(
        session,
        action,
        expected_url_pattern,
        timeout=None,
        error_message="",
    ):
        action()

    monkeypatch.setattr(
        "linkedin.actions.comment_origins.goto_page",
        fake_goto_page,
    )

    result = collect_comment_origins(
        session,
        "https://www.linkedin.com/in/jane-doe/",
        limit=5,
    )
    assert result.public_identifier == "jane-doe"
    assert result.post_urls == [
        "https://www.linkedin.com/feed/update/urn:li:activity:42/",
    ]
