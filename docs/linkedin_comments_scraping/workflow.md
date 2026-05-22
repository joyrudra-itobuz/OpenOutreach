# Workflow

End-to-end walkthrough of how the LinkedIn comment-scraping pipeline works.

## High-level flow

```
Target profile URL
        │
        ▼
 candidate_activity_urls()          ← builds 3 candidate page URLs
        │
        ▼
 goto_page() → LinkedIn activity    ← Playwright navigates, waits for URL match
        │
        │  wait 3–4 s (JS renders)
        ▼
 _scroll_and_collect()              ← iterative scroll + collect loop
        │
        │  per scroll: scrollBy(0, 2 × viewport), wait 2.5 s
        │  stops when: limit reached OR 3 consecutive scrolls yield nothing
        ▼
 List[post_url]                     ← unique, normalised LinkedIn post URLs
        │
        │  (profile_comment_posts only)
        ▼
 _extract_post_data()               ← navigate each URL, scrape text + images
        │
        ▼
 JSON payload → stdout / webhook
```

## Module map

| Module | Role |
|:-------|:-----|
| `linkedin/actions/comment_origins.py` | Core scraping logic — navigation, scrolling, URL extraction |
| `linkedin/management/commands/profile_comment_origins.py` | CLI wrapper — collects URLs only, POSTs raw URL list |
| `linkedin/management/commands/profile_comment_posts.py` | CLI wrapper — collects URLs **and** full post content |
| `linkedin/browser/nav.py` | `goto_page()` — safe navigation helper with URL-match guard |
| `linkedin/api/webhooks.py` | `post_json()` — delivers payload to any HTTP endpoint |
| `linkedin/url_utils.py` | `url_to_public_id()` / `public_id_to_url()` — URL normalisation |

## Step-by-step code walkthrough

### 1. URL normalisation (`collect_comment_origins`)

```python
public_identifier = url_to_public_id(profile_url)
# "https://www.linkedin.com/in/some-person/" → "some-person"
```

`candidate_activity_urls()` produces three candidates tried in order:

```
https://www.linkedin.com/in/some-person/recent-activity/comments/
https://www.linkedin.com/in/some-person/recent-activity/all/
https://www.linkedin.com/in/some-person/recent-activity/posts/
```

The first URL that yields ≥1 post link is used; the rest are skipped.

### 2. Navigation (`goto_page`)

`goto_page` wraps `page.goto()` with a `page.wait_for_url()` guard so the daemon
doesn't proceed if LinkedIn redirected to a login wall or error page.
`wait_until="domcontentloaded"` is used (not `"networkidle"`) because LinkedIn
keeps firing background XHRs indefinitely.

### 3. Initial render wait (`session.wait(3, 4)`)

After navigation, the code waits a random 3–4 seconds. LinkedIn's activity feed is
fully JavaScript-rendered — the DOM is empty right after `domcontentloaded` and the
first batch of feed items only appears after React/Ember finishes its initial paint.

### 4. Scroll loop (`_scroll_and_collect`)

LinkedIn uses an infinite-scroll pattern. Items below the viewport are not in the
DOM at all until they scroll into view.

```python
while len(urls) < limit and no_new_count < max_no_new:
    batch = extract_original_post_urls(session.page, limit=limit)
    new   = [u for u in batch if u not in seen]
    if new:
        seen.update(new); urls.extend(new); no_new_count = 0
    else:
        no_new_count += 1

    session.page.evaluate("window.scrollBy(0, window.innerHeight * 2)")
    session.page.wait_for_load_state("domcontentloaded")
    time.sleep(2.5)   # give the feed time to insert new DOM nodes
```

Termination conditions:

- `len(urls) >= limit` — enough URLs collected
- `no_new_count >= 3` — three scrolls in a row with no new links (end of feed or private profile)

### 5. URL extraction (`extract_original_post_urls`)

Queries three CSS selectors against the current page DOM:

```
a[href*="/feed/update/"]
a[href*="/posts/"]
a[href*="/pulse/"]
```

Each href is normalised by `_normalize_post_url()`:

- Resolved to absolute (`urljoin`)
- Query string and fragment stripped
- Must be on `linkedin.com`
- Must contain one of the three path markers
- Trailing slash enforced

### 6. Post content extraction (`profile_comment_posts` only)

For each collected URL, `_extract_post_data()` navigates to that post and runs:

**Text** — tries these selectors in order, falls back to `body`:

```
[data-test-post-content]
.feed-shared-update-v2__description
.break-words
```

**Images** — finds all `<img>` tags whose `src` starts with
`https://media.licdn.com/`. This captures post images and article hero images
while excluding profile avatars and ad pixels.

Output shape per post:

```json
{
  "url": "https://www.linkedin.com/posts/...",
  "post": "Post body text…",
  "images": ["https://media.licdn.com/dms/image/..."]
}
```

### 7. Webhook delivery

The final JSON array is POSTed via `post_json()`:

```json
{
  "username": "<configured username>",
  "posts": [ ... ]
}
```

`profile_comment_origins` uses a different payload shape:

```json
{
  "type": "profile_comment_origins",
  "collected_at": "2026-05-20T10:00:00+00:00",
  "profile_url": "...",
  "public_identifier": "...",
  "source_url": "...",
  "post_urls": ["...", "..."],
  "warnings": []
}
```

## Failure modes

| Situation | Behaviour |
|:----------|:----------|
| Profile is private / no activity | 3 candidate URLs all return 0 links → `result.post_urls = []` |
| LinkedIn redirects to login wall | `goto_page` raises `RuntimeError` → warning added, next candidate tried |
| Post page fails to load | `_extract_post_data` catches exception, logs to stderr, skips that URL |
| Webhook unreachable | `post_json` raises; exception propagates and the command exits non-zero |
| `DISPLAY` not set (headless server) | Playwright raises on browser launch → run with `DISPLAY=:99` |
