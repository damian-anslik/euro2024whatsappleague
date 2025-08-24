from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
import dotenv

import logging

dotenv.load_dotenv(dotenv.find_dotenv())

from app.routers import app_router, auth_router

logging.basicConfig(level=logging.INFO)
app = FastAPI(title="FastAPI Application", version="1.0.0")
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(app_router, tags=["Application"])
app.include_router(auth_router, tags=["Authentication"])
