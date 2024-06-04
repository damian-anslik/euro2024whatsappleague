from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

import logging

from app.routers import app_router


load_dotenv()
logging.basicConfig(level=logging.INFO)
app = FastAPI(
    docs_url=None,
)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(app_router)
