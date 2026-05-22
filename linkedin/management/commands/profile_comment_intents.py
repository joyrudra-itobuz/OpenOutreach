from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Literal

from django.core.management.base import BaseCommand
from pydantic import BaseModel, Field
from pydantic_ai import Agent

from linkedin.actions.comment_origins import collect_comment_origins
from linkedin.api.webhooks import post_json
from linkedin.browser.registry import get_or_create_session, resolve_profile
from linkedin.llm import get_llm_model, run_agent_sync


class IntentDecision(BaseModel):
    intent: Literal["YES", "NO"] = Field(
        description=(
            "YES when there is clear business intent for B2B outreach."
        ),
    )
    lead: Literal["High", "Medium", "Low"] = Field(
        description="How promising this post is as a potential lead.",
    )
    reason: str = Field(description="One concise reason for the verdict.")
    suggested_reply: str = Field(
        description=(
            "A concise, human response suitable for LinkedIn comments."
        ),
    )


class Command(BaseCommand):
    help = (
        "Collect commented posts, classify business intent with the "
        "configured "
        "LLM, and optionally deliver to a webhook."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--profile-url",
            required=True,
            help="LinkedIn /in/ profile URL to inspect",
        )
        parser.add_argument(
            "--webhook-url",
            default="",
            help=(
                "Webhook URL for delivery. Defaults to "
                "COMMENT_INTENT_WEBHOOK_URL "
                "then OPENCLAW_WEBHOOK_URL."
            ),
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=20,
            help="Maximum number of commented posts to analyze",
        )
        parser.add_argument(
            "--business-only",
            action="store_true",
            help="Return/send only intent=YES posts",
        )
        parser.add_argument(
            "--webhook-format",
            choices=["json", "google_chat"],
            default="json",
            help="Webhook payload format",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print payload without POSTing",
        )
        parser.add_argument(
            "--handle",
            default=None,
            help=(
                "Django username for the login profile (default: first active "
                "profile)"
            ),
        )

    def handle(self, *args, **options):
        profile = resolve_profile(options["handle"])
        if not profile:
            self.stderr.write("No active LinkedIn profile found.")
            raise SystemExit(1)

        session = get_or_create_session(profile)
        session.ensure_browser()

        origins = collect_comment_origins(
            session,
            options["profile_url"],
            limit=options["limit"],
        )

        analyses = []
        total = len(origins.post_urls)
        self.stderr.write(f"Found {total} post(s) to analyze")

        for index, url in enumerate(origins.post_urls, start=1):
            self._render_progress(
                index - 1,
                total,
                f"Analyzing post {index}/{total}",
            )
            post_data = self._extract_post_data(session, url)
            if not post_data:
                continue
            decision = self._assess_business_intent(post_data)
            analyses.append(
                {
                    "post_number": index,
                    "author": post_data["author"],
                    "intent": decision.intent,
                    "lead": decision.lead,
                    "url": url,
                    "reason": decision.reason,
                    "suggested_reply": decision.suggested_reply,
                }
            )

        self._render_progress(
            total,
            total,
            "Analyzing complete" if total else "No posts",
        )
        self.stderr.write("")

        posts = analyses
        if options["business_only"]:
            posts = [item for item in analyses if item["intent"] == "YES"]

        payload = {
            "type": "profile_comment_intents",
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "profile_url": origins.profile_url,
            "public_identifier": origins.public_identifier,
            "source_url": origins.source_url,
            "posts": posts,
            "warnings": origins.warnings,
        }

        self.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False))

        if options["dry_run"]:
            return

        webhook_url = options["webhook_url"] or os.environ.get(
            "COMMENT_INTENT_WEBHOOK_URL",
            "",
        ) or os.environ.get("OPENCLAW_WEBHOOK_URL", "")
        if not webhook_url:
            self.stderr.write(
                "Missing webhook URL. Pass --webhook-url or set "
                "COMMENT_INTENT_WEBHOOK_URL / OPENCLAW_WEBHOOK_URL.",
            )
            raise SystemExit(1)

        if options["webhook_format"] == "google_chat":
            body = {"text": self._build_google_chat_text(posts)}
        else:
            body = payload

        response = post_json(webhook_url, body)
        self.stdout.write(f"Delivered to webhook: HTTP {response['status']}")

    def _extract_post_data(self, session, url: str) -> dict | None:
        try:
            session.page.goto(url, wait_until="domcontentloaded")
            session.wait(1, 2)
            return {
                "author": self._extract_author(session),
                "post": self._extract_post_text(session),
                "url": url,
            }
        except Exception as exc:
            self.stderr.write(f"Failed to parse post {url}: {exc}")
            return None

    def _extract_author(self, session) -> str:
        selectors = (
            ".update-components-actor__title span[dir='ltr'] span",
            ".update-components-actor__title",
            ".feed-shared-actor__name",
        )
        for selector in selectors:
            el = session.page.query_selector(selector)
            if not el:
                continue
            text = (el.inner_text() or "").strip()
            if text:
                return text
        return "Unknown"

    def _extract_post_text(self, session) -> str:
        selectors = (
            "[data-test-post-content]",
            ".feed-shared-update-v2__description",
            ".update-components-text",
            ".break-words",
        )
        for selector in selectors:
            el = session.page.query_selector(selector)
            if not el:
                continue
            text = (el.inner_text() or "").strip()
            if text:
                return text
        return ""

    def _assess_business_intent(self, post_data: dict) -> IntentDecision:
        prompt = (
            "You are a strict B2B lead-intent classifier. Evaluate whether "
            "this "
            "LinkedIn post indicates real business intent relevant for agency "
            "outreach.\n\n"
            "Business intent = the author is likely seeking services, "
            "partners, vendors, consulting help, implementation support, "
            "or has a pain point "
            "that an agency can solve.\n"
            "Non-intent examples = personal milestones, generic motivation, "
            "hiring freelancers for someone else's project without buyer "
            "intent, "
            "or casual engagement posts.\n\n"
            f"Author: {post_data['author']}\n"
            f"URL: {post_data['url']}\n"
            f"Post Text:\n{post_data['post']}\n\n"
            "Return structured output with:\n"
            "- intent: YES or NO\n"
            "- lead: High/Medium/Low\n"
            "- reason: one concise sentence\n"
            "- suggested_reply: one short LinkedIn comment reply"
        )

        agent = Agent(
            get_llm_model(),
            output_type=IntentDecision,
            model_settings={"temperature": 0.2, "timeout": 90},
        )
        return run_agent_sync(agent.run(prompt)).output

    def _build_google_chat_text(self, posts: list[dict]) -> str:
        if not posts:
            return "No intent-positive posts found in the analyzed set."

        blocks = []
        for post in posts:
            blocks.append(
                "\n".join(
                    [
                        (
                            f"Post {post['post_number']}: "
                            f"{post['author']}"
                        ),
                        (
                            f"Intent: {post['intent']} | "
                            f"Lead: {post['lead']}"
                        ),
                        f"URL: {post['url']}",
                        f"Reason: {post['reason']}",
                        f"Suggested Reply: {post['suggested_reply']}",
                    ]
                )
            )

        return "\n\n".join(blocks)

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
