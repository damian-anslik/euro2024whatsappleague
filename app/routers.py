from fastapi import APIRouter, Request, Form, status
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
import datetime

from app import services

app_router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@app_router.post("/session")
def create_session(username: str = Form(...)):
    session_id = services.create_user_session(username)
    response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        key="session_id",
        value=session_id,
        expires=datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=365),
    )
    return response


@app_router.get("/")
def read_root(request: Request):
    session_id = request.cookies.get("session_id", None)
    if not session_id or not services.check_user_session(session_id):
        response = templates.TemplateResponse("index.html", {"request": request})
        response.delete_cookie("session_id")
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
async def get_matches(request: Request):
    session_id = request.cookies.get("session_id", None)
    if not session_id or not services.check_user_session(session_id):
        return templates.TemplateResponse("index.html", {"request": request})
    leagues = {
        "Premier League": {
            "id": "39",
            "season": "2023",
        },
        "Bundesliga": {
            "id": "78",
            "season": "2023",
        },
        "Euro 2024": {
            "id": "4",
            "season": "2024",
        },
    }
    match_date = datetime.datetime.today()
    id, season = leagues.get("Premier League").values()
    matches = services.get_matches(
        league_id=id,
        season=season,
        date=match_date,
    )
    return matches


@app_router.get("/bets")
async def bets(request: Request):
    session_id = request.cookies.get("session_id", None)
    if not session_id or not services.check_user_session(session_id):
        return templates.TemplateResponse("index.html", {"request": request})
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
    if not session_id:
        return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    services.place_bet(
        user_id=session_id,
        match_id=fixture_id,
        home_goals=home_goals,
        away_goals=away_goals,
    )
    return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
