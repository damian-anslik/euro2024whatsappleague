from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.routers import app_router
from dotenv import load_dotenv
import logging

load_dotenv()
logging.basicConfig(level=logging.INFO)
app = FastAPI()
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(app_router)
