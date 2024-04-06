import logging
import datetime
import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler

from app.routers import app_router
from app.services import update_match_data


def configure_scheduler(league_ids: list[str], season: str):
    UPDATE_DATA_EVERY_N_MINUTES = 5
    scheduler = BackgroundScheduler()
    update_todays_matches = lambda: update_match_data(
        league_ids,
        season,
        datetime.datetime.now(datetime.UTC).today(),
    )
    update_tomorrows_matches = lambda: update_match_data(
        league_ids,
        season,
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
configure_scheduler(
    league_ids=os.getenv("LEAGUE_IDS").split(","),
    season=os.getenv("LEAGUE_SEASON"),
)
app = FastAPI()
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(app_router)
