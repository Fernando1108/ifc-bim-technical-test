from fastapi import APIRouter
from app.api.routes import health, auth

router = APIRouter()

router.include_router(health.router, tags=["health"])
router.include_router(auth.router)
