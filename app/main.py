from apscheduler.schedulers.background import BackgroundScheduler
from fastapi.staticfiles import StaticFiles
from fastapi import FastAPI
from dotenv import load_dotenv

import datetime
import logging

from app.routers import app_router
from app.matches.services import scheduled_update_function


def configure_scheduler(update_frequency_mins: int = 5):
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        func=lambda: scheduled_update_function(
            datetime.datetime.now(datetime.UTC).today(),
        ),
        trigger="cron",
        minute=f"*/{update_frequency_mins}",
    )
    scheduler.add_job(
        func=lambda: scheduled_update_function(
            datetime.datetime.now(datetime.UTC).today() + datetime.timedelta(days=1),
        ),
        trigger="cron",
        minute=f"*/{update_frequency_mins}",
    )
    scheduler.add_job(
        func=lambda: scheduled_update_function(
            datetime.datetime.now(datetime.UTC).today() + datetime.timedelta(days=2),
        ),
        trigger="cron",
        minute=f"*/{update_frequency_mins}",
    )
    scheduler.start()


load_dotenv()
logging.basicConfig(level=logging.INFO)
configure_scheduler()
app = FastAPI()
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(app_router)
