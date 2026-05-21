from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from django.core.management.base import BaseCommand

from linkedin.actions.comment_origins import collect_comment_origins
from linkedin.api.webhooks import post_json
from linkedin.browser.registry import get_or_create_session, resolve_profile


class Command(BaseCommand):
    help = (
        "Find original post links for comments made by a LinkedIn profile "
        "and send them to a webhook."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--profile-url",
            required=True,
            help="LinkedIn /in/ profile or /company/ page URL to inspect",
        )
        parser.add_argument(
            "--webhook-url",
            default="",
            help="Webhook URL for delivery (default: OPENCLAW_WEBHOOK_URL)",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=50,
            help="Maximum number of post links to collect",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Collect links and print payload without POSTing",
        )
        parser.add_argument(
            "--handle",
            default=None,
            help=(
                "Django username for the login profile (default: first "
                "active profile)"
            ),
        )

    def handle(self, *args, **options):
        profile = resolve_profile(options["handle"])
        if not profile:
            self.stderr.write("No active LinkedIn profile found.")
            raise SystemExit(1)

        session = get_or_create_session(profile)
        session.ensure_browser()

        result = collect_comment_origins(
            session,
            options["profile_url"],
            limit=options["limit"],
        )
        payload = {
            "type": "profile_comment_origins",
            "collected_at": datetime.now(timezone.utc).isoformat(),
            **result.as_payload(),
        }

        self.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False))

        if options["dry_run"]:
            return

        webhook_url = options["webhook_url"] or os.environ.get(
            "OPENCLAW_WEBHOOK_URL",
            "",
        )
        if not webhook_url:
            self.stderr.write(
                "Missing webhook URL. Pass --webhook-url or set "
                "OPENCLAW_WEBHOOK_URL."
            )
            raise SystemExit(1)

        response = post_json(webhook_url, payload)
        self.stdout.write(f"Delivered to webhook: HTTP {response['status']}")
