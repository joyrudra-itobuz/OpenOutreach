from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from linkedin.actions.comment_origins import collect_comment_origins
from linkedin.api.webhooks import post_json
from linkedin.browser.registry import get_or_create_session, resolve_profile


class Command(BaseCommand):
    help = (
        "Collects full post content (text, images, url) for all posts a "
        "LinkedIn profile has commented on, and outputs a JSON array ready "
        "for OpenClaw webhook."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--profile-url",
            default=None,
            help=(
                "LinkedIn /in/ profile or /company/ page URL to inspect "
                "(prompted if omitted)"
            ),
        )
        parser.add_argument(
            "--webhook-url",
            default=None,
            help="Webhook URL for delivery (prompted if omitted)",
        )
        parser.add_argument(
            "--username",
            default=None,
            help="Username to include in webhook body (prompted if omitted)",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Maximum number of posts to collect (prompted if omitted)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print JSON to stdout without POSTing",
        )
        parser.add_argument(
            "--handle",
            default=None,
            help=(
                "Django username for the login profile (default: first active "
                "profile)"
            ),
        )

    def _prompt(self, prompt_text: str, default: str = "") -> str:
        """Read a line from stdin, showing an optional default."""
        display = (
            f"{prompt_text} [{default}]: " if default else f"{prompt_text}: "
        )
        self.stderr.write(display, ending="")
        value = input().strip()
        return value if value else default

    def handle(self, *args, **options):
        # --- Interactive prompts for missing required values ---
        profile_url = options["profile_url"]
        if not profile_url:
            profile_url = self._prompt("Profile URL")
            if not profile_url:
                self.stderr.write("Profile URL is required.")
                raise SystemExit(1)

        limit = options["limit"]
        if limit is None:
            raw = self._prompt("Limit", default="50")
            try:
                limit = int(raw)
            except ValueError:
                limit = 50

        webhook_url = options["webhook_url"]
        username = options["username"]
        dry_run = options["dry_run"]

        if not dry_run and webhook_url is None:
            answer = self._prompt(
                "Send results to webhook? [y/N]", default="N"
            ).lower()
            if answer in ("y", "yes"):
                webhook_url = self._prompt("Webhook URL")
                if not username:
                    username = self._prompt("Username for webhook body")
            else:
                dry_run = True  # no webhook → treat as dry-run (print only)

        # Fill remaining defaults
        if webhook_url is None:
            webhook_url = ""
        if username is None:
            username = ""

        # --- Main execution ---
        profile = resolve_profile(options["handle"])
        if not profile:
            self.stderr.write("No active LinkedIn profile found.")
            raise SystemExit(1)

        self._log("Starting browser session")
        session = get_or_create_session(profile)
        session.ensure_browser()

        self._log(f"Collecting commented post URLs for {profile_url}")
        result = collect_comment_origins(
            session,
            profile_url,
            limit=limit,
        )
        post_urls = result.post_urls
        total = len(post_urls)
        self._log(f"Found {total} post(s) to scrape")

        posts = []
        for index, url in enumerate(post_urls, start=1):
            self._render_progress(
                index - 1,
                total,
                f"Scraping post {index}/{total}",
            )
            self._log(f"Scraping {url}")
            post_data = self._extract_post_data(session, url)
            if post_data:
                posts.append(post_data)
        self._render_progress(
            total,
            total,
            f"Scraping post {total}/{total}" if total else "Scraping posts",
        )
        self.stderr.write("")

        payload = posts
        json_out = json.dumps(payload, indent=2, ensure_ascii=False)
        self._log(f"Scraping complete. Collected {len(payload)} item(s)")
        self.stdout.write(json_out)

        if dry_run or not webhook_url:
            if dry_run:
                self._log("Dry run requested; skipping webhook delivery")
            return

        self._log(f"Posting payload to webhook: {webhook_url}")
        webhook_body = {
            "username": username,
            "posts": payload,
        }
        response = post_json(webhook_url, webhook_body)
        self.stdout.write(f"Delivered to webhook: HTTP {response['status']}")

    def _extract_post_data(self, session, url):
        try:
            session.page.goto(url, wait_until="domcontentloaded")
            session.wait(1, 2)
            post_text = self._extract_post_text(session)
            images = self._extract_post_images(session)
            return {
                "images": images,
                "post": post_text,
                "url": url,
            }
        except Exception as e:
            self.stderr.write(f"Failed to extract post at {url}: {e}")
            return None

    def _log(self, message: str) -> None:
        self.stderr.write(message)

    def _render_progress(self, current: int, total: int, label: str) -> None:
        width = 24
        if total <= 0:
            bar = "[........................]"
            percent = 0
        else:
            filled = int(width * current / total)
            bar = "[" + ("#" * filled) + ("." * (width - filled)) + "]"
            percent = int((current / total) * 100)
        self.stderr.write(f"\r{bar} {percent:3d}% {label}", ending="")

    def _extract_post_text(self, session):
        try:
            el = session.page.query_selector(
                (
                    "[data-test-post-content], "
                    ".feed-shared-update-v2__description, "
                    ".break-words"
                ),
            )
            if el:
                return el.inner_text().strip()
            return session.page.inner_text("body").strip()
        except Exception:
            return ""

    def _extract_post_images(self, session):
        try:
            imgs = session.page.query_selector_all("img")
            urls = []
            for img in imgs:
                src = img.get_attribute("src")
                if src and src.startswith("https://media.licdn.com/"):
                    urls.append(src)
            return urls
        except Exception:
            return []
