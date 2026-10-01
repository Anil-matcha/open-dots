from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.routers import auth, bots, models, chat, approvals, upload, settings as settings_router, connectors, audit, computers
from app.services.auth_service import auth_service
from app.services.computer_provider import computer_provider
from app.services.storage_service import storage_service

app = FastAPI(
    title="Open Dots API",
    description="Open-source alternative to OpenAI Dots: self-hosted AI workspace API with a configurable inference adapter",
    version="1.0.0"
)

PUBLIC_API_PATHS = {
    "/api/v1/health",
    "/api/v1/auth/status",
    "/api/v1/auth/session",
    "/api/v1/auth/login",
    "/api/v1/auth/logout",
}


@app.middleware("http")
async def require_authentication(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/v1"):
        # Reject absurd bodies before any parsing or buffering happens. This
        # runs before authentication so even public endpoints (notably
        # /api/v1/auth/login) cannot be used for memory exhaustion.
        try:
            content_length = int(request.headers.get("content-length") or 0)
        except ValueError:
            content_length = 0
        if content_length > settings.MAX_REQUEST_BYTES:
            return JSONResponse({"detail": "Request body is too large."}, status_code=413)
    if path.startswith("/api/v1") and request.method != "OPTIONS":
        origin = request.headers.get("origin")
        allowed_origins = {*settings.CORS_ORIGINS, str(request.base_url).rstrip("/")}
        # CORS alone does not stop credentialed requests from changing state.
        if (origin and origin not in allowed_origins) or (
            not origin and request.headers.get("sec-fetch-site") in {"cross-site", "same-site"}
        ):
            return JSONResponse({"detail": "Untrusted request origin."}, status_code=403)
    if (
        request.method == "OPTIONS"
        or not path.startswith("/api/v1")
        or path in PUBLIC_API_PATHS
    ):
        response = await call_next(request)
        if path.startswith("/api/v1/auth/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    user = auth_service.authenticate_request(request)
    if not user:
        return JSONResponse(
            {"detail": "Authentication is required."},
            status_code=401,
            headers={"WWW-Authenticate": "Bearer", "Cache-Control": "no-store"},
        )
    request.state.user = user
    return await call_next(request)

# Wrap authentication so allowed browser clients can read 401 responses.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(bots.router)
app.include_router(models.router)
app.include_router(chat.router)
app.include_router(upload.router)
app.include_router(approvals.router)
app.include_router(settings_router.router)
app.include_router(connectors.router)
app.include_router(audit.router)
app.include_router(computers.router)


@app.get("/api/v1/health")
async def health_check():
    return {
        "status": "online",
        "service": "Open Dots FastAPI Backend",
        "provider": "configured inference endpoint",
        "computer_provider": computer_provider.provider_name,
        "default_model": storage_service.get_settings().get("default_model") or settings.DEFAULT_MODEL
    }
