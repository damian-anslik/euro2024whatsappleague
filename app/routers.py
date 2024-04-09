import datetime
import logging
import json

from fastapi import APIRouter, Request, Form, status, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from app import services, auth, models

app_router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@app_router.post("/login")
def login(username: str = Form(...)):
    session_id = auth.get_user_session(username)
    response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    if session_id:
        response.set_cookie(
            key="session_id",
            value=session_id,
            expires=datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=365),
        )
    return response


@app_router.get("/leagues")
def get_leagues() -> list[models.League]:
    with open("config.json", "r") as f:
        config = json.load(f)
    return config["leagues"]


@app_router.post("/leagues")
def update_leagues(league: models.League):
    current_leagues = get_leagues()
    leagues = []
    for current_league in current_leagues:
        if current_league["id"] != league.id:
            leagues.append(current_league)
        else:
            # Update the league
            leagues.append(league.model_dump())
            services.update_match_data(
                league_id=league.id,
                season=league.season,
                date=datetime.datetime.now(datetime.UTC).today(),
                show_by_default=league.show_by_default,
                force_update=True,
            )
            services.update_match_data(
                league_id=league.id,
                season=league.season,
                date=datetime.datetime.now(datetime.UTC).today()
                + datetime.timedelta(days=1),
                show_by_default=league.show_by_default,
                force_update=True,
            )
    with open("config.json", "w") as f:
        json.dump({"leagues": leagues}, f, indent=4)
    return leagues


@app_router.get("/")
def read_root(request: Request):
    session_id = request.cookies.get("session_id", None)
    if not session_id or not auth.check_user_session(session_id):
        # Delete the cookie if the session is not valid
        if "session_id" in request.cookies:
            del request.cookies["session_id"]
        response = templates.TemplateResponse("index.html", {"request": request})
        return response
    league_standings = services.get_current_standings()
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "standings": league_standings,
        },
    )


@app_router.get("/matches")
async def get_matches():
    todays_date = datetime.datetime.now(datetime.UTC).today()
    tomorrows_date = todays_date + datetime.timedelta(days=1)
    todays_matches = services.get_matches_for_given_date(
        date=datetime.datetime(
            todays_date.year,
            todays_date.month,
            todays_date.day,
        ),
    )
    tomorrows_matches = services.get_matches_for_given_date(
        date=datetime.datetime(
            tomorrows_date.year,
            tomorrows_date.month,
            tomorrows_date.day,
        ),
    )
    return {
        "today": todays_matches,
        "tomorrow": tomorrows_matches,
    }


@app_router.get("/bets")
async def bets(request: Request):
    session_id = request.cookies.get("session_id", None)
    if not session_id or not auth.check_user_session(session_id):
        return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    user_bets = services.get_user_bets(user_id=session_id)
    return user_bets


@app_router.post("/bets")
def place_bet(
    request: Request,
    fixture_id: int = Form(...),
    home_goals: int = Form(...),
    away_goals: int = Form(...),
):
    session_id = request.cookies.get("session_id", None)
    if not session_id or not auth.check_user_session(session_id):
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        updated_bet = services.create_user_match_prediction(
            user_id=session_id,
            match_id=fixture_id,
            predicted_home_goals=home_goals,
            predicted_away_goals=away_goals,
        )
        return updated_bet
    except Exception as e:
        logging.error(f"Error placing bet: {e}")
        raise HTTPException(status_code=500, detail=str(e))
