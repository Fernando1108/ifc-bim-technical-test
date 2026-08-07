from fastapi import APIRouter
from app.api.routes import health, auth, models

router = APIRouter()

router.include_router(health.router, tags=["health"])
router.include_router(auth.router)
router.include_router(models.router)
