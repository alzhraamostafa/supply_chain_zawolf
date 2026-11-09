
from fastapi import FastAPI

from app.core.config import get_settings
from app.api.v1.endpoints.database import router as database_router
from app.api.v1.endpoints.products import router as products_router
from app.api.v1.endpoints.production import router as production_router
# Import the inventory API router.
from app.api.v1.endpoints.inventory import router as inventory_router

# Load validated configuration values.
settings = get_settings()


# Initialize the FastAPI application.
app = FastAPI(
    title=settings.app_name,
    description="Smart Manufacturing Supply Chain Management System",
    version=settings.app_version,
    debug=settings.debug,
)


# Register the versioned database router.
app.include_router(
    database_router,
    prefix="/api/v1",
)

# Register the product endpoints under API version 1.
app.include_router(
    products_router,
    prefix="/api/v1",
)

# Register production calculation endpoints under API version 1.
app.include_router(
    production_router,
    prefix="/api/v1",
)

# Register inventory endpoints under API version 1.
app.include_router(
    inventory_router,
    prefix="/api/v1",
)
# Expose a lightweight endpoint for checking API availability.
@app.get("/api/v1/health", tags=["System"])
def health_check():
    return {
        "status": "ok",
        "application": settings.app_name,
        "version": settings.app_version,
    }
