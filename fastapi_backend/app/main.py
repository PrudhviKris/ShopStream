import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .database import Base, engine
from .routers import auth, cart, checkout, notifications, orders, payments, products
from .services.notification_service import manager

Base.metadata.create_all(bind=engine)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Capture the server loop so sync endpoints can schedule WebSocket pushes.
    manager.loop = asyncio.get_running_loop()
    yield


app = FastAPI(
    lifespan=lifespan,
    title=settings.APP_NAME,
    version=settings.API_VERSION,
    description=(
        "User-facing APIs: authentication (JWT + Auth0 social login), product catalog, "
        "cart, Stripe checkout, orders, payments, and real-time notifications."
    ),
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
app.include_router(notifications.router)


@app.get("/", tags=["Health"])
def health():
    return {"service": settings.APP_NAME, "version": settings.API_VERSION, "status": "ok"}
