from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def post_json(url: str, payload: dict, timeout: int = 10) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            status = getattr(response, "status", 200)
            response_body = response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        if exc.fp:
            detail = exc.read().decode("utf-8", errors="replace")
        else:
            detail = str(exc)
        raise RuntimeError(
            f"Webhook POST failed with HTTP {exc.code}: {detail}"
        ) from exc
    except URLError as exc:
        raise RuntimeError(f"Webhook POST failed: {exc.reason}") from exc

    if status < 200 or status >= 300:
        raise RuntimeError(
            f"Webhook POST failed with HTTP {status}: {response_body}"
        )

    return {"status": status, "body": response_body}
