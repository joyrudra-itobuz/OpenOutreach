from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from urllib.parse import urljoin, urlparse

from linkedin.browser.nav import goto_page
from linkedin.exceptions import SkipProfile

logger = logging.getLogger(__name__)

_POST_LINK_SELECTORS = (
    'a[href*="/feed/update/"]',
    'a[href*="/posts/"]',
    'a[href*="/pulse/"]',
)

_POST_URN_SELECTORS = (
    ".feed-shared-update-v2[data-urn]",
    '[data-view-name="feed-full-update"] [data-urn]',
)

_SHOW_MORE_SELECTORS = (
    ".scaffold-finite-scroll__load-button",
    'button:has-text("Show more results")',
)


@dataclass(slots=True)
class CommentOriginResult:
    profile_url: str
    public_identifier: str
    source_url: str | None = None
    post_urls: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_payload(self) -> dict:
        return asdict(self)


def candidate_activity_urls(profile_url: str) -> list[str]:
    parsed = urlparse((profile_url or "").strip())
    path_parts = [part for part in parsed.path.split("/") if part]
    if len(path_parts) < 2 or path_parts[0] not in {"in", "company"}:
        raise ValueError(
            "profile_url must point to a LinkedIn /in/ profile or /company/ page"
        )

    base_profile_url = (
        f"https://www.linkedin.com/{path_parts[0]}/{path_parts[1]}/"
    )
    return [
        f"{base_profile_url}recent-activity/comments/",
        f"{base_profile_url}recent-activity/all/",
        f"{base_profile_url}recent-activity/posts/",
    ]


def _normalize_post_url(base_url: str, href: str) -> str | None:
    if not href:
        return None

    absolute = urljoin(base_url, href.strip())
    parsed = urlparse(absolute)
    if "linkedin.com" not in parsed.netloc:
        return None

    clean = parsed._replace(query="", fragment="").geturl()
    if any(
        marker in clean
        for marker in ("/feed/update/", "/posts/", "/pulse/")
    ):
        if clean.startswith(
            (
                "https://www.linkedin.com/feed/update/",
                "https://www.linkedin.com/posts/",
                "https://www.linkedin.com/pulse/",
            )
        ) and not clean.endswith("/"):
            clean += "/"
        return clean
    return None


def _normalize_post_urn(urn: str) -> str | None:
    if not urn:
        return None

    clean_urn = urn.strip()
    if not clean_urn.startswith("urn:li:"):
        return None

    if clean_urn.startswith(("urn:li:activity:", "urn:li:ugcPost:")):
        return f"https://www.linkedin.com/feed/update/{clean_urn}/"

    return None


def extract_original_post_urls(page, limit: int = 50) -> list[str]:
    seen: set[str] = set()
    urls: list[str] = []

    link_selector = ", ".join(_POST_LINK_SELECTORS)
    for locator in page.locator(link_selector).all():
        href = locator.get_attribute("href") or ""
        clean = _normalize_post_url(page.url, href)
        if not clean or clean in seen:
            continue
        seen.add(clean)
        urls.append(clean)
        if len(urls) >= limit:
            break

    if len(urls) < limit:
        urn_selector = ", ".join(_POST_URN_SELECTORS)
        for locator in page.locator(urn_selector).all():
            urn = locator.get_attribute("data-urn") or ""
            clean = _normalize_post_urn(urn)
            if not clean or clean in seen:
                continue
            seen.add(clean)
            urls.append(clean)
            if len(urls) >= limit:
                break

    return urls


def _try_click_show_more(page) -> bool:
    for selector in _SHOW_MORE_SELECTORS:
        button = page.locator(selector).first
        if button.count() <= 0:
            continue
        if not button.is_visible():
            continue
        button.click()
        page.wait_for_load_state("domcontentloaded")
        return True
    return False


def _scroll_and_collect(session, limit: int) -> list[str]:
    """Scroll the page iteratively to trigger LinkedIn lazy-loading, collecting
    post URLs as they appear in the DOM. Returns when ``limit`` URLs are found
    or three consecutive scrolls yield nothing new."""
    seen: set[str] = set()
    urls: list[str] = []
    no_new_count = 0
    max_no_new = 3
    scroll_pause = 2.5  # seconds between scrolls

    while len(urls) < limit and no_new_count < max_no_new:
        batch = extract_original_post_urls(session.page, limit=limit)
        new = [u for u in batch if u not in seen]
        if new:
            seen.update(new)
            urls.extend(new)
            no_new_count = 0
        else:
            no_new_count += 1

        if len(urls) >= limit:
            break

        # LinkedIn sometimes switches from infinite-scroll to a finite
        # "Show more results" button after initial batches.
        clicked_show_more = False
        try:
            clicked_show_more = _try_click_show_more(session.page)
        except Exception:
            clicked_show_more = False

        if not clicked_show_more:
            session.page.evaluate("window.scrollBy(0, window.innerHeight * 2)")
            session.page.wait_for_load_state("domcontentloaded")
        import time
        time.sleep(scroll_pause)

    return urls[:limit]


def collect_comment_origins(
    session,
    profile_url: str,
    limit: int = 50,
) -> CommentOriginResult:
    session.ensure_browser()

    parsed = urlparse((profile_url or "").strip())
    path_parts = [part for part in parsed.path.split("/") if part]
    if len(path_parts) < 2 or path_parts[0] not in {"in", "company"}:
        raise ValueError(
            "profile_url must point to a LinkedIn /in/ profile or /company/ page"
        )
    public_identifier = path_parts[1]

    result = CommentOriginResult(
        profile_url=profile_url,
        public_identifier=public_identifier,
    )

    for activity_url in candidate_activity_urls(profile_url):
        try:
            goto_page(
                session,
                action=lambda: session.page.goto(
                    activity_url,
                    wait_until="domcontentloaded",
                ),
                expected_url_pattern="/recent-activity",
                error_message="Failed to open LinkedIn activity page",
            )
            # Give the JS feed time to render before the first selector pass
            session.wait(3, 4)
        except SkipProfile as exc:
            result.warnings.append(str(exc))
            continue
        except RuntimeError as exc:
            result.warnings.append(str(exc))
            continue

        urls = _scroll_and_collect(session, limit=limit)
        if urls:
            result.source_url = session.page.url
            result.post_urls = urls
            return result

        result.warnings.append(f"No post links found on {activity_url}")

    return result
