# Scripts Reference

Two Django management commands implement the scraping pipeline.

---

## `profile_comment_origins`

**File**: `linkedin/management/commands/profile_comment_origins.py`

Collects the **URLs** of posts a LinkedIn profile has commented on and optionally
delivers them to a webhook. Does **not** visit or scrape the individual posts.

### Usage

```bash
python manage.py profile_comment_origins \
  --profile-url "https://www.linkedin.com/in/some-person/" \
  [--limit 50] \
  [--webhook-url "https://..."] \
  [--dry-run] \
  [--handle myuser]
```

### Arguments

| Argument | Required | Default | Description |
|:---------|:---------|:--------|:------------|
| `--profile-url` | ✅ | — | Target LinkedIn profile URL (`/in/…`) |
| `--limit` | ❌ | `50` | Max number of post URLs to collect |
| `--webhook-url` | ❌ | `$OPENCLAW_WEBHOOK_URL` | HTTP endpoint to POST the payload to |
| `--dry-run` | ❌ | `false` | Print JSON to stdout, skip webhook |
| `--handle` | ❌ | first active profile | Django username for the login account |

If `--webhook-url` is omitted and `OPENCLAW_WEBHOOK_URL` env var is not set, the
command errors unless `--dry-run` is passed.

### Output (stdout)

```json
{
  "type": "profile_comment_origins",
  "collected_at": "2026-05-20T10:00:00+00:00",
  "profile_url": "https://www.linkedin.com/in/some-person/",
  "public_identifier": "some-person",
  "source_url": "https://www.linkedin.com/in/some-person/recent-activity/comments/",
  "post_urls": [
    "https://www.linkedin.com/posts/author_slug-ugcPost-123456789/",
    "https://www.linkedin.com/feed/update/urn:li:activity:987654321/"
  ],
  "warnings": []
}
```

### Docker example

```bash
docker compose -f local.yml exec -T app sh -lc \
  'DISPLAY=:99 python manage.py profile_comment_origins \
     --profile-url "https://www.linkedin.com/in/some-person/" \
     --limit 10 \
     --dry-run'
```

---

## `profile_comment_posts`

**File**: `linkedin/management/commands/profile_comment_posts.py`

Collects post URLs (same as above) **and** visits each post to scrape its full
text and images. Interactive when run without arguments.

### Usage — interactive mode

```bash
python manage.py profile_comment_posts
```

Prompts in order:

```
Profile URL: https://www.linkedin.com/in/some-person/
Limit [50]: 20
Send results to webhook? [y/N]: y
Webhook URL: https://hooks.example.com/endpoint
Username for webhook body: john_doe
```

If you answer **N** (or press Enter) at the webhook prompt, the command prints
JSON to stdout and exits — no POST is made.

### Usage — non-interactive (all args on CLI)

```bash
python manage.py profile_comment_posts \
  --profile-url "https://www.linkedin.com/in/some-person/" \
  --limit 20 \
  --webhook-url "https://hooks.example.com/endpoint" \
  --username "john_doe" \
  [--dry-run] \
  [--handle myuser]
```

### Arguments

| Argument | Required | Default | Description |
|:---------|:---------|:--------|:------------|
| `--profile-url` | ❌ | prompted | Target LinkedIn profile URL (`/in/…`) |
| `--limit` | ❌ | prompted (default 50) | Max posts to collect and scrape |
| `--webhook-url` | ❌ | prompted | HTTP endpoint to POST results to |
| `--username` | ❌ | prompted | Username field in the webhook body |
| `--dry-run` | ❌ | `false` | Print JSON to stdout, skip webhook |
| `--handle` | ❌ | first active profile | Django username for the login account |

`--handle` and `--dry-run` are never prompted — pass them as flags if needed.

### Output (stdout)

A JSON array, one object per scraped post:

```json
[
  {
    "url": "https://www.linkedin.com/posts/author_slug-ugcPost-123/",
    "post": "Full post text goes here…",
    "images": [
      "https://media.licdn.com/dms/image/D4E22AQE.../shrink_800_800/0/..."
    ]
  },
  {
    "url": "https://www.linkedin.com/feed/update/urn:li:activity:987/",
    "post": "Another post…",
    "images": []
  }
]
```

### Webhook body

```json
{
  "username": "john_doe",
  "posts": [ ... ]
}
```

### Progress display (stderr)

While scraping, a progress bar is rendered to stderr:

```
[################........]  66% Scraping post 8/12
```

### Docker examples

```bash
# Interactive
docker compose -f local.yml exec app sh -lc \
  'DISPLAY=:99 python manage.py profile_comment_posts'

# Non-interactive dry run
docker compose -f local.yml exec -T app sh -lc \
  'DISPLAY=:99 python manage.py profile_comment_posts \
     --profile-url "https://www.linkedin.com/in/some-person/" \
     --limit 5 \
     --dry-run'
```

---

## Choosing between the two commands

| Use case | Command |
|:---------|:--------|
| Just want a list of post URLs | `profile_comment_origins` |
| Want post text + images for content analysis | `profile_comment_posts` |
| Feeding into an LLM for summarisation | `profile_comment_posts` |
| Quick audit / check who a person engages with | `profile_comment_origins` |
