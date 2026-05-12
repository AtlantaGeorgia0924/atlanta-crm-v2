from fastapi import FastAPI

from app.core.settings import get_settings
from app.presentation.api import router

settings = get_settings()

app = FastAPI(title=settings.project_name)
app.include_router(router, prefix=settings.api_prefix)
