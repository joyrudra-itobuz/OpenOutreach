from __future__ import annotations

from linkedin.management.commands.profile_comment_intents import Command


def test_build_google_chat_text_formats_blocks():
    cmd = Command()
    text = cmd._build_google_chat_text(
        [
            {
                "post_number": 9,
                "author": "Siddharth Patel",
                "intent": "NO",
                "lead": "Medium",
                "url": (
                    "https://www.linkedin.com/feed/update/"
                    "urn:li:activity:7462396522836451328/"
                ),
                "reason": "Recruiting freelancers, not buyer intent.",
                "suggested_reply": "Thanks for sharing this.",
            }
        ]
    )

    assert "Post 9: Siddharth Patel" in text
    assert "Intent: NO | Lead: Medium" in text
    assert "URL: https://www.linkedin.com/feed/update/" in text
    assert "Reason: Recruiting freelancers, not buyer intent." in text


def test_build_google_chat_text_empty_posts():
    cmd = Command()
    text = cmd._build_google_chat_text([])
    assert text == "No intent-positive posts found in the analyzed set."
