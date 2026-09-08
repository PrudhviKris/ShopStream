import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .database import Base, engine
from .routers import auth, cart, checkout, invoices, notifications, orders, payments, products
from .services.notification_service import manager

Base.metadata.create_all(bind=engine)


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
    {"name": "Notifications", "description": "Notification inbox plus real-time push over "
     "`ws://<host>/ws/notifications?token=<access_token>`."},
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

app.include_router(auth.router)
app.include_router(products.router)
app.include_router(cart.router)
app.include_router(checkout.router)
app.include_router(orders.router)
app.include_router(payments.router)
app.include_router(invoices.router)
app.include_router(notifications.router)


@app.get("/", tags=["Health"])
def health():
    return {"service": settings.APP_NAME, "version": settings.API_VERSION, "status": "ok"}
