from fastapi import FastAPI
from app.api.router import router


def create_app() -> FastAPI:
    application = FastAPI(
        title="IFC BIM Technical Test API",
        version="0.1.0",
    )
    application.include_router(router, prefix="/api/v1")
    return application


app = create_app()
