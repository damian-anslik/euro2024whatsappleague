from fastapi import APIRouter, Request, Form, status, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse

import datetime
import logging

import app.services
import app.auth.services
import app.bets.services

app_router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@app_router.post("/login")
def login(username: str = Form(...)):
    try:
        response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
        session_id = app.services.login_handler(username)
        if session_id:
            response.set_cookie(
                key="session_id",
                value=session_id,
                expires=datetime.datetime.now(datetime.UTC)
                + datetime.timedelta(days=365),
            )
        return response
    except Exception as e:
        logging.error(f"Error logging in: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app_router.get("/")
def read_root(request: Request):
    session_id = request.cookies.get("session_id", None)
    if not session_id or not app.auth.services.check_user_session(session_id):
        # Delete the cookie if the session is not valid
        if "session_id" in request.cookies:
            del request.cookies["session_id"]
        response = templates.TemplateResponse("index.html", {"request": request})
        return response
    standings = app.services.root_handler()
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "standings": standings,
        },
    )


@app_router.get("/matches")
async def get_matches():
    matches = app.services.get_matches_handler()
    return matches


@app_router.get("/bets")
async def get_bets(request: Request):
    session_id = request.cookies.get("session_id", None)
    if not session_id or not app.auth.services.check_user_session(session_id):
        return RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    user_bets = app.services.get_bets_handler(session_id)
    return user_bets


@app_router.post("/bets")
def place_bet(
    request: Request,
    fixture_id: int = Form(...),
    home_goals: int = Form(...),
    away_goals: int = Form(...),
):
    session_id = request.cookies.get("session_id", None)
    if not session_id or not app.auth.services.check_user_session(session_id):
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        updated_bet = app.services.place_bet_handler(
            user_id=session_id,
            match_id=fixture_id,
            predicted_home_goals=home_goals,
            predicted_away_goals=away_goals,
        )
        return updated_bet
    except Exception as e:
        logging.error(f"Error placing bet: {e}")
        raise HTTPException(status_code=500, detail=str(e))
