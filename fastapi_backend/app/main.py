import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import BASE_DIR, settings
from .database import Base, engine
from .routers import (
    admin,
    auth,
    cart,
    checkout,
    dev_emails,
    invoices,
    notifications,
    orders,
    payments,
    products,
)
from .schema_upgrade import upgrade_schema
from .services.notification_service import manager


class ApiPrefixMiddleware:
    

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            path = scope.get("path", "")
            if path == "/api" or path.startswith("/api/"):
                scope = dict(scope)
                scope["path"] = path[4:] or "/"
                raw = scope.get("raw_path")
                if raw:
                    scope["raw_path"] = raw[4:] or b"/"
        await self.app(scope, receive, send)

Base.metadata.create_all(bind=engine)
upgrade_schema(engine)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Capture the server loop so sync endpoints can schedule WebSocket pushes.
    manager.loop = asyncio.get_running_loop()
    yield


tags_metadata = [
    {"name": "Authentication", "description": "Register, login, JWT refresh, and Google/Facebook "
     "social login. Click **Authorize** (top right) and paste the `access_token` to try "
     "protected endpoints."},
    {"name": "Products", "description": "Catalog browsing with filters (category, price range, "
     "stock, search) and sorting. Create/update/delete require the **admin** role."},
    {"name": "Cart", "description": "Per-user cart: add, update quantity, remove, view with "
     "item totals, tax, and grand total."},
    {"name": "Checkout", "description": "Validates the cart, creates the order, and initializes "
     "a Stripe Checkout Session or PaymentIntent."},
    {"name": "Orders", "description": "Order history and lifecycle "
     "(pending → paid → shipped → delivered / cancelled). Status updates require staff/admin."},
    {"name": "Payments", "description": "Stripe webhook, payment tracking per order, and a "
     "mock confirmation endpoint for development without Stripe keys."},
    {"name": "Invoices", "description": "Invoices are issued automatically when a payment "
     "succeeds. Customers see their own; admins see everyone's (`/invoices/all`) and the "
     "role definitions (`/roles`)."},
    {"name": "Notifications", "description": "Order-event notifications (`order_placed`, "
     "`order_confirmed`, `payment_successful`, `payment_failed`, `order_shipped`, "
     "`order_delivered`, `order_cancelled`). `GET /notifications` lists them, "
     "`POST /notifications/read` marks them read. "
     "**Real-time:** connect a WebSocket to `ws://<host>/ws/notifications?token=<access_token>`. "
     "Every message is `{\"event\", \"data\", \"sent_at\"}` with events `notification`, "
     "`order_status_updated`, `cart_updated`, `notifications_read`, `order_deleted`. "
     "(Swagger can't open WebSockets — use the storefront or a WS client.)"},
    {"name": "Development Email", "description": "**Your inbox.** Every order confirmation, "
     "payment success/failure and shipping update sent to you is kept here — so you can read "
     "your mail even if your address is made up or no mail server is configured. "
     "`GET /dev/emails/summary` gives the unread count; `POST /dev/emails/read` marks emails read. "
     "With `EMAIL_BACKEND=smtp` mail is also delivered (SMTP, SendGrid or AWS SES) to Google "
     "accounts, and to local accounts only if `SMTP_SEND_TO_LOCAL_ACCOUNTS=true`."},
    {"name": "Admin", "description": "**Admin only.** Store analytics for the dashboard, the user "
     "directory, and the log of every outgoing email."},
]

app = FastAPI(
    lifespan=lifespan,
    title=settings.APP_NAME,
    version=settings.API_VERSION,
    description=(
        "User-facing APIs: authentication (JWT + Google/Facebook social login), product catalog, "
        "cart, Stripe checkout, orders, payments, invoices, and real-time notifications.\n\n"
        "**Swagger UI**: this page (`/docs`) is the interactive API documentation — "
        "use **Authorize** with a JWT from `POST /auth/login`. ReDoc is at `/redoc`."
    ),
    openapi_tags=tags_metadata,
    swagger_ui_parameters={"persistAuthorization": True, "displayRequestDuration": True},
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(ApiPrefixMiddleware)

app.include_router(auth.router)
app.include_router(products.router)
app.include_router(cart.router)
app.include_router(checkout.router)
app.include_router(orders.router)
app.include_router(payments.router)
app.include_router(invoices.router)
app.include_router(notifications.router)
app.include_router(dev_emails.router)
app.include_router(admin.router)


@app.get("/health", tags=["Health"])
def health():
    return {"service": settings.APP_NAME, "version": settings.API_VERSION, "status": "ok"}


def _api_prefixes(routes) -> set:
    """Every first path segment the API itself owns.

    The SPA catch-all below must not swallow these: an unknown path under one
    of them is a wrong API call and has to answer with JSON, not the
    storefront's HTML shell (which reads as "the API returned HTML").
    Included routers aren't flattened into app.routes — FastAPI keeps each as a
    composite object that holds the real routes on `.original_router` — so walk
    into those rather than only reading top-level paths.
    """
    found = set()
    for route in routes:
        path = getattr(route, "path", None)
        if path:
            segment = path.strip("/").split("/")[0]
            if segment and not segment.startswith("{"):
                found.add(segment)
        nested = getattr(route, "original_router", None) or getattr(route, "routes", None)
        if nested is not None:
            found |= _api_prefixes(getattr(nested, "routes", nested))
    return found


API_PREFIXES = _api_prefixes(app.routes)


def _no_such_endpoint(method: str, full_path: str) -> HTTPException:
    """A 404 that says what's wrong, instead of the bare 'Method Not Allowed'
    a write to an unknown path used to produce (the SPA fallback below only
    answers GET, so POST/PUT/DELETE to a wrong URL looked like a method
    problem rather than a typo)."""
    return HTTPException(
        status_code=404,
        detail=(
            f"No such API endpoint: {method} /{full_path}. "
            "See /docs for the available routes — note that payment confirmation "
            "is POST /payments/confirm/{order_id}."
        ),
    )


FRONTEND_DIST = BASE_DIR.parent / "frontend" / "dist"
if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="spa-assets")

    @app.api_route(
        "/{full_path:path}",
        methods=["POST", "PUT", "PATCH", "DELETE"],
        include_in_schema=False,
    )
    def unknown_write_endpoint(full_path: str, request: Request):
        raise _no_such_endpoint(request.method, full_path)

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path.strip("/").split("/")[0] in API_PREFIXES:
            raise _no_such_endpoint("GET", full_path)
        candidate = FRONTEND_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        # Never let the browser cache the app shell: each build emits new hashed
        # asset filenames, so a stale index.html keeps loading the *old* bundle
        # and the UI silently looks like it never updated.
        return FileResponse(
            FRONTEND_DIST / "index.html",
            headers={"Cache-Control": "no-cache, must-revalidate"},
        )
else:

    @app.get("/", include_in_schema=False)
    def root():
        return {
            "service": settings.APP_NAME,
            "docs": "/docs",
            "hint": "run `npm run build` in frontend/ to serve the storefront here",
        }
