import datetime
import pathlib
import json

import app.matches.services
import app.auth.services
import app.bets.services


def login_handler(username: str):
    session_id = app.auth.services.get_user_session(username)
    return session_id


def root_handler() -> list[dict]:
    matches = app.matches.services.get_matches()
    finished_matches = matches["finished"]
    ongoing_matches = matches["ongoing"]
    league_standings = app.bets.services.get_current_standings(
        finished_matches=finished_matches,
        ongoing_matches=ongoing_matches,
    )
    return league_standings


def get_matches_handler() -> dict:
    dates = [
        datetime.datetime.now(datetime.UTC).today(),
        datetime.datetime.now(datetime.UTC).today() + datetime.timedelta(days=1),
    ]
    todays_matches = app.matches.services.get_matches(dates[0])
    tomorrows_matches = app.matches.services.get_matches(dates[1])
    todays_ongoing_or_finished_matches = (
        todays_matches["finished"] + todays_matches["ongoing"]
    )
    todays_ongoing_or_finished_match_ids = [
        match["id"] for match in todays_ongoing_or_finished_matches
    ]
    if len(todays_ongoing_or_finished_matches) > 0:
        bets = app.bets.services.get_match_bets(todays_ongoing_or_finished_match_ids)
        # Add the bets information onto ongoing or finished matches
        for match in todays_matches["ongoing"]:
            match_bets = [bet for bet in bets if bet["match_id"] == match["id"]]
            match_bets.sort(key=lambda x: x["user"]["name"])
            match["bets"] = match_bets
        for match in todays_matches["finished"]:
            match_bets = [bet for bet in bets if bet["match_id"] == match["id"]]
            match_bets.sort(key=lambda x: x["user"]["name"])
            match["bets"] = match_bets
    # Order matches by status
    finished_matches = todays_matches["finished"]
    finished_matches.sort(key=lambda match: match["timestamp"])
    ongoing_matches = todays_matches["ongoing"]
    ongoing_matches.sort(key=lambda match: match["timestamp"])
    scheduled_matches = todays_matches["scheduled"]
    scheduled_matches.sort(key=lambda match: match["timestamp"])
    todays_matches = ongoing_matches + scheduled_matches + finished_matches
    tomorrows_matches = sorted(
        tomorrows_matches["scheduled"], key=lambda x: x["timestamp"]
    )
    response = {
        "today": todays_matches,
        "tomorrow": tomorrows_matches,
    }
    return response


def get_bets_handler(user_id: str) -> dict:
    user_bets = app.bets.services.get_user_bets(user_id)
    return user_bets


def place_bet_handler(
    user_id: str, match_id: str, predicted_home_goals: int, predicted_away_goals: int
):
    match_details = app.matches.services.get_match_details(match_id)
    if not match_details["can_users_place_bets"]:
        raise ValueError("Bets for this match are closed")
    if (
        datetime.datetime.now(datetime.UTC).timestamp()
        - datetime.datetime.fromisoformat(match_details["timestamp"]).timestamp()
        > 5 * 60
    ):
        # TODO Update the match details to show that the match is closed for bets
        raise ValueError("Bets for this match are closed")
    bet = app.bets.services.create_user_match_prediction(
        user_id, match_id, predicted_home_goals, predicted_away_goals
    )
    return bet


with open(pathlib.Path(__file__).parent.joinpath("config.json")) as f:
    scheduler_config = json.load(f)["scheduler"]
app.matches.services.configure_scheduler(
    update_frequency_mins=scheduler_config["update_matches_every_n_mins"],
    num_days_to_update=scheduler_config["num_days_to_fetch"],
)
