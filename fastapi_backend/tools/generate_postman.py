"""Generate a Postman collection from the live OpenAPI schema.

    python tools/generate_postman.py                 # writes docs/postman_collection.json

Regenerate it whenever endpoints change — the collection is derived, never
hand-edited. Swagger (/docs) remains the primary way to try the API; this is
for people who prefer Postman.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.main import app  # noqa: E402

OUTPUT = Path(__file__).resolve().parents[2] / "docs" / "postman_collection.json"

# Requests that need a body Postman can prefill; everything else is derived
# from the schema. Keyed by "METHOD /path".
EXAMPLE_BODIES = {
    "POST /auth/register": {"name": "Ada Lovelace", "email": "ada@example.com", "password": "ChangeMe123!"},
    "POST /auth/login": {"email": "ada@example.com", "password": "ChangeMe123!"},
    "POST /auth/refresh": {"refresh_token": "{{refresh_token}}"},
    "POST /auth/logout": {"refresh_token": "{{refresh_token}}"},
    "POST /cart/add": {"product_id": 1, "quantity": 1},
    "PUT /cart/update": {"product_id": 1, "quantity": 2},
    "POST /notifications/read": {"all": True},
    "POST /dev/emails/read": {"all": True},
    "POST /products": {"name": "New product", "description": "", "category": "electronics",
                       "price": 1999, "stock": 10, "images": []},
    "PUT /products/{product_id}": {"price": 1799, "stock": 25},
}

# Tokens the login request captures, so later requests just work.
LOGIN_TEST_SCRIPT = [
    "// Save the tokens so every other request in this collection is authorised.",
    "if (pm.response.code === 200) {",
    "    const body = pm.response.json();",
    "    pm.collectionVariables.set('access_token', body.access_token);",
    "    pm.collectionVariables.set('refresh_token', body.refresh_token);",
    "}",
]


def _url(path: str, params):
    query = [
        {"key": p["name"], "value": str(p.get("schema", {}).get("default", "")),
         "description": p.get("description", ""), "disabled": not p.get("required", False)}
        for p in params if p.get("in") == "query"
    ]
    segments = [seg for seg in path.strip("/").split("/") if seg]
    return {
        "raw": "{{base_url}}" + path + ("?" + "&".join(f"{q['key']}={q['value']}" for q in query if not q["disabled"]) if any(not q["disabled"] for q in query) else ""),
        "host": ["{{base_url}}"],
        "path": segments,
        "query": query or [],
        "variable": [
            {"key": p["name"], "value": "", "description": p.get("description", "")}
            for p in params if p.get("in") == "path"
        ],
    }


def build_collection() -> dict:
    schema = app.openapi()
    folders = {}

    for path, operations in sorted(schema["paths"].items()):
        for method, operation in operations.items():
            if method not in ("get", "post", "put", "patch", "delete"):
                continue
            tag = (operation.get("tags") or ["Other"])[0]
            key = f"{method.upper()} {path}"
            request = {
                "method": method.upper(),
                "header": [{"key": "Content-Type", "value": "application/json"}] if key in EXAMPLE_BODIES else [],
                "url": _url(path, operation.get("parameters", [])),
                "description": (operation.get("description") or operation.get("summary") or "").strip(),
            }
            if key in EXAMPLE_BODIES:
                request["body"] = {
                    "mode": "raw",
                    "raw": json.dumps(EXAMPLE_BODIES[key], indent=2),
                    "options": {"raw": {"language": "json"}},
                }
            item = {"name": operation.get("summary") or key, "request": request}
            if key == "POST /auth/login":
                item["event"] = [{"listen": "test", "script": {"type": "text/javascript", "exec": LOGIN_TEST_SCRIPT}}]
            folders.setdefault(tag, []).append(item)

    return {
        "info": {
            "name": f"{app.title} API",
            "description": (
                "Generated from the OpenAPI schema by tools/generate_postman.py.\n\n"
                "1. Set `base_url` (default http://127.0.0.1:8000).\n"
                "2. Run **Authentication → Login**; it stores the tokens automatically.\n"
                "3. Every other request inherits Bearer auth from the collection.\n\n"
                "WebSockets can't be represented here: connect a WS client to "
                "{{base_url}}/ws/notifications?token={{access_token}}."
            ),
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "auth": {"type": "bearer", "bearer": [{"key": "token", "value": "{{access_token}}", "type": "string"}]},
        "variable": [
            {"key": "base_url", "value": "http://127.0.0.1:8000"},
            {"key": "access_token", "value": ""},
            {"key": "refresh_token", "value": ""},
        ],
        "item": [{"name": tag, "item": items} for tag, items in sorted(folders.items())],
    }


if __name__ == "__main__":
    collection = build_collection()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(collection, indent=2), encoding="utf-8")
    endpoints = sum(len(folder["item"]) for folder in collection["item"])
    print(f"wrote {OUTPUT} — {endpoints} requests in {len(collection['item'])} folders")
