from fastapi import APIRouter, Request, Form, status, HTTPException, Depends
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse

import datetime
import logging

from app import services, auth

app_router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@app_router.get("/signup")
def signup_form(request: Request):
    # Redirect to home if user is already logged in
    access_token = request.cookies.get("access_token", None)
    if access_token:
        response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
        return response
    return templates.TemplateResponse("signup.html", {"request": request})


@app_router.post("/signup")
def signup(
    email: str = Form(...), username: str = Form(...), password: str = Form(...)
):
    try:
        access_token = auth.signup(email, username, password)
        response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
        response.set_cookie(
            key="access_token",
            value=access_token,
            expires=datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=365),
        )
        return response
    except ValueError as e:
        logging.error(f"Error creating user: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logging.exception(e)
        raise HTTPException(
            status_code=500, detail="Something went wrong, please try again."
        )


@app_router.get("/login")
def login_form(request: Request):
    # Redirect to home if user is already logged in
    access_token = request.cookies.get("access_token", None)
    if access_token:
        response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
        return response
    return templates.TemplateResponse("login.html", {"request": request})


@app_router.post("/login")
def login(email: str = Form(...), password: str = Form(...)):
    try:
        access_token = auth.login(email=email, password=password)
        response = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
        response.set_cookie(
            key="access_token",
            value=access_token,
            expires=datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=365),
        )
        return response
    except ValueError as e:
        logging.error(f"Error logging in: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logging.exception(e)
        raise HTTPException(
            status_code=500, detail="Something went wrong, please try again."
        )


@app_router.get("/logout")
def logout(_: Request):
    response = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    response.delete_cookie("access_token")
    return response


@app_router.get("/reset-password")
def reset_password_form(request: Request):
    return templates.TemplateResponse("reset-password.html", {"request": request})


@app_router.post("/reset-password")
def reset_password(email: str = Form(...)):
    try:
        auth.send_password_reset_request(email)
        return {"message": "Password reset link sent to your email."}
    except Exception as e:
        logging.error(f"Error resetting password: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app_router.get("/change-password")
def change_password_form(request: Request):
    return templates.TemplateResponse("change-password.html", {"request": request})


@app_router.post("/change-password")
def change_password(password: str = Form(...), token: str = Form(...)):
    try:
        user_id = auth.check_user_session(token)
        auth.change_password(user_id=user_id, password=password)
        return {"message": "Password changed successfully."}
    except Exception as e:
        logging.error(f"Error changing password: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app_router.get("/")
def read_root(request: Request):
    access_token = request.cookies.get("access_token", None)
    if not access_token:
        response = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
        return response
    try:
        _ = auth.check_user_session(access_token)
        league_standings = services.get_current_standings()
        response = templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "standings": league_standings,
            },
        )
        return response
    except Exception as e:
        logging.exception(e)
        if "access_token" in request.cookies:
            del request.cookies["access_token"]
        response = templates.TemplateResponse("login.html", {"request": request})
        return response


@app_router.get("/rules")
async def get_rules(request: Request):
    return templates.TemplateResponse("rules.html", {"request": request})


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
async def get_user_bets(request: Request):
    access_token = request.cookies.get("access_token", None)
    if not access_token:
        response = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
        return response
    try:
        user_id = auth.check_user_session(access_token)
        user_bets = services.get_user_bets(user_id=user_id)
        return user_bets
    except Exception as e:
        logging.error(f"Error fetching user bets: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app_router.post("/bets")
def place_bet(
    request: Request,
    fixture_id: int = Form(...),
    home_goals: int = Form(...),
    away_goals: int = Form(...),
):
    access_token = request.cookies.get("access_token", None)
    if not access_token:
        response = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
        return response
    try:
        user_id = auth.check_user_session(access_token)
        updated_bet = services.create_user_match_prediction(
            user_id=user_id,
            match_id=fixture_id,
            predicted_home_goals=home_goals,
            predicted_away_goals=away_goals,
        )
        return updated_bet
    except Exception as e:
        logging.exception(e)
        raise HTTPException(status_code=500, detail=str(e))
