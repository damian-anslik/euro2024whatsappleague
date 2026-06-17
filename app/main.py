from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
import dotenv

import logging

dotenv.load_dotenv(dotenv.find_dotenv())

from app.routers import app_router, auth_router, admin_router

logging.basicConfig(level=logging.INFO)
app = FastAPI(title="FastAPI Application", version="1.0.0")
app.mount("/static", StaticFiles(directory="app/static"), name="static")

@app.middleware("http")
async def add_cache_control_header(request: Request, call_next):
    response = await call_next(request)
    
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
        
    return response
  
app.include_router(app_router, tags=["Application"])
app.include_router(auth_router, tags=["Authentication"])
app.include_router(admin_router, prefix="/admin", tags=["Admin"])
