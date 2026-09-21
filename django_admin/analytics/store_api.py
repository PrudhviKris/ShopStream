"""Thin client for the FastAPI store service.

Order status changes go through the API rather than straight to the database
so the customer gets everything they would from the storefront: the
notification, the email, and the live WebSocket update. The admin
authenticates with SERVICE_API_TOKEN (shared via fastapi_backend/.env).

stdlib only — the admin doesn't need `requests` just for this.
"""
import json
import logging
import os
import urllib.error
import urllib.request
from urllib.parse import quote

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 8


class StoreApiUnavailable(RuntimeError):
    """The API couldn't be reached, or refused the request."""


def _base_url() -> str:
    """Where the FastAPI service listens. STORE_API_URL wins; STORE_BASE_URL
    is the same value the admin uses for image previews."""
    url = os.getenv("STORE_API_URL") or os.getenv("STORE_BASE_URL") or "http://127.0.0.1:8000"
    return url.rstrip("/")


def is_configured() -> bool:
    """True when a service token is set — otherwise the API would reject us
    and there is no point trying."""
    return bool(os.getenv("SERVICE_API_TOKEN", "").strip())


def set_order_status(order_id: int, status: str) -> dict:
    """PUT /orders/{id}/status. Returns the updated order, or raises."""
    if not is_configured():
        raise StoreApiUnavailable("SERVICE_API_TOKEN is not set")

    url = f"{_base_url()}/orders/{int(order_id)}/status?status={quote(status)}"
    request = urllib.request.Request(url, method="PUT")
    request.add_header("X-Service-Token", os.environ["SERVICE_API_TOKEN"].strip())
    request.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise StoreApiUnavailable(f"API returned {exc.code}: {detail}") from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise StoreApiUnavailable(f"{exc.__class__.__name__}: {exc}") from exc
