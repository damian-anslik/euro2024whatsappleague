import logging
import datetime

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler

from app.routers import app_router
from app.services import scheduled_update_function


def configure_scheduler():
    UPDATE_DATA_EVERY_N_MINUTES = 5
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        func=lambda: scheduled_update_function(
            datetime.datetime.now(datetime.UTC).today(),
        ),
        trigger="cron",
        minute=f"*/{UPDATE_DATA_EVERY_N_MINUTES}",
    )
    scheduler.add_job(
        func=lambda: scheduled_update_function(
            datetime.datetime.now(datetime.UTC).today() + datetime.timedelta(days=1),
        ),
        trigger="cron",
        minute=f"*/{UPDATE_DATA_EVERY_N_MINUTES}",
    )
    scheduler.add_job(
        func=lambda: scheduled_update_function(
            datetime.datetime.now(datetime.UTC).today() + datetime.timedelta(days=2),
        ),
        trigger="cron",
        minute=f"*/{UPDATE_DATA_EVERY_N_MINUTES}",
    )
    scheduler.start()


load_dotenv()
logging.basicConfig(level=logging.INFO)
configure_scheduler()
app = FastAPI()
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(app_router)
