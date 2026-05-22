# LinkedIn Comments Scraping

This folder documents the LinkedIn comment-scraping pipeline built into OpenOutreach.

## What it does

Given a target LinkedIn profile URL, the pipeline:

1. Navigates to that profile's public activity feed (`/recent-activity/comments/`)
2. Scrolls the page iteratively to trigger LinkedIn's infinite-scroll lazy loader
3. Collects the URLs of the original posts the person commented on
4. Optionally visits each post URL and scrapes its full text and images
5. Delivers the result as a JSON payload to a configured webhook (OpenClaw or any HTTP endpoint)

## Files in this folder

| File | Description |
|:-----|:------------|
| [workflow.md](workflow.md) | End-to-end pipeline walkthrough — code flow, data shapes, failure modes |
| [scripts.md](scripts.md) | CLI reference for `profile_comment_origins` and `profile_comment_posts` |
| [ollama_setup.md](ollama_setup.md) | How to run a local Ollama model and wire it in as the LLM provider |

## Quick start (Docker)

```bash
# Interactive — prompts for URL, limit, and webhook
docker compose -f local.yml exec app sh -lc \
  'DISPLAY=:99 python manage.py profile_comment_posts'

# Non-interactive — all args on the CLI
docker compose -f local.yml exec app sh -lc \
  'DISPLAY=:99 python manage.py profile_comment_posts \
     --profile-url "https://www.linkedin.com/in/some-person/" \
     --limit 20 \
     --dry-run'
```

## Quick start (local dev)

```bash
DISPLAY=:99 .venv/bin/python manage.py profile_comment_posts
```
