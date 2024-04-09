import logging
import datetime
import json

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler

from app.routers import app_router
from app.services import update_match_data


def scheduled_update_function(date: datetime.datetime):
    with open("config.json", "r") as f:
        config = json.load(f)
    leagues = config["leagues"]
    for league in leagues:
        try:
            update_match_data(
                league["id"], league["season"], date, league["show_by_default"]
            )
        except Exception as e:
            logging.error(f"Error updating data for league {league['id']}: {e}")


def configure_scheduler():
    UPDATE_DATA_EVERY_N_MINUTES = 5
    scheduler = BackgroundScheduler()
    update_todays_matches = lambda: scheduled_update_function(
        datetime.datetime.now(datetime.UTC).today(),
    )
    update_tomorrows_matches = lambda: scheduled_update_function(
        datetime.datetime.now(datetime.UTC).today() + datetime.timedelta(days=1),
    )
    scheduler.add_job(
        func=update_todays_matches,
        trigger="cron",
        minute=f"*/{UPDATE_DATA_EVERY_N_MINUTES}",
    )
    scheduler.add_job(
        func=update_tomorrows_matches,
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
