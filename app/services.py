import os
import logging
import datetime

import requests
import supabase

from app.models import Match, Bet, BetInDB

supabase_client = supabase.create_client(
    supabase_key=os.getenv("SUPABASE_KEY"),
    supabase_url=os.getenv("SUPABASE_URL"),
)
bets_table = supabase_client.table("bets")
matches_table = supabase_client.table("matches")
scheduled_match_statuses = ["NS", "TBD"]
ongoing_match_statuses = ["1H", "HT", "2H", "ET", "BT", "P", "INT"]
finished_match_statuses = ["FT", "AET", "PEN"]


def get_matches_from_api(
    league_ids: list[str],
    season: str,
    date: datetime.datetime,
) -> list[dict]:
    url = f"https://{os.getenv('RAPIDAPI_BASE_URL')}/v3/fixtures"
    headers = {
        "X-RapidAPI-Key": os.getenv("RAPIDAPI_KEY"),
        "X-RapidAPI-Host": os.getenv("RAPIDAPI_BASE_URL"),
    }
    parsed_fixtures = []
    for league_id in league_ids:
        querystring = {
            "date": date.date().strftime("%Y-%m-%d"),
            "league": league_id,
            "season": season,
        }
        logging.info(f"Fetching fixtures for league_id: {league_id}")
        response = requests.get(url, headers=headers, params=querystring)
        response_data = response.json()["response"]
        for fixture in response_data:
            fixture_status = fixture["fixture"]["status"]["short"]
            can_user_place_bet = fixture_status in scheduled_match_statuses
            parsed_fixtures.append(
                {
                    "id": fixture["fixture"]["id"],
                    "timestamp": datetime.datetime.fromtimestamp(
                        fixture["fixture"]["timestamp"],
                        datetime.UTC,
                    ).isoformat(),
                    "status": fixture_status,
                    "league_id": league_id,
                    "season": season,
                    "can_users_place_bets": can_user_place_bet,
                    "home_team_name": fixture["teams"]["home"]["name"],
                    "away_team_name": fixture["teams"]["away"]["name"],
                    "home_team_logo": fixture["teams"]["home"]["logo"],
                    "away_team_logo": fixture["teams"]["away"]["logo"],
                    "home_team_goals": fixture["goals"]["home"],
                    "away_team_goals": fixture["goals"]["away"],
                    "updated_at": datetime.datetime.now(datetime.UTC).isoformat(),
                }
            )
    return parsed_fixtures


def get_matches_for_given_date(
    date: datetime.datetime,
) -> list[dict]:
    response_data = (
        supabase_client.table("matches")
        .select("*")
        .gt("timestamp", date.isoformat())
        .lt("timestamp", (date + datetime.timedelta(days=1)).isoformat())
        .execute()
        .data
    )
    return response_data


def did_check_for_matches_today(params: str) -> bool:
    response_data = (
        supabase_client.table("match_checks")
        .select("*")
        .eq("params", params)
        .execute()
        .data
    )
    return bool(response_data)


def update_match_data(
    league_ids: list[str],
    season: str,
    date: datetime.datetime,
):
    matches_in_db = get_matches_for_given_date(date)
    if not matches_in_db:
        match_check_string = (
            f"{','.join(league_ids)}-{season}-{date.date().strftime('%Y-%m-%d')}"
        )
        # It is possible that there are no matches on a given date, in this case, we should check if we already checked for matches today
        if did_check_for_matches_today(match_check_string):
            logging.info("No matches in DB, already checked for matches today")
            return
        logging.info("No matches found in the DB, fetching from the API for first time")
        todays_matches = get_matches_from_api(league_ids, season, date)
        supabase_client.table("matches").upsert(todays_matches).execute()
        # Log that we checked for matches today
        supabase_client.table("match_checks").insert(match_check_string).execute()
        return
    # Check if there are ongoing matches
    ongoing_matches = []
    for match in matches_in_db:
        if not (
            datetime.datetime.now(datetime.UTC).timestamp()
            > datetime.datetime.fromisoformat(match["timestamp"]).timestamp()
            and match["status"] not in finished_match_statuses
        ):
            continue
        ongoing_matches.append(match["id"])
    if not ongoing_matches:
        logging.info("No ongoing matches found")
        return
    ongoing_match_league_ids = list(
        set(
            [
                match["league_id"]
                for match in matches_in_db
                if match["id"] in ongoing_matches
            ]
        )
    )
    # If there are ongoing matches, update the fixtures
    logging.info("Updating fixtures")
    date_from_midnight = datetime.datetime(
        date.year, date.month, date.day, 0, 0, 0, tzinfo=datetime.UTC
    )
    todays_matches = get_matches_from_api(
        ongoing_match_league_ids, season, date_from_midnight
    )
    supabase_client.table("matches").upsert(todays_matches).execute()


def get_current_standings() -> list[dict]:
    matches = supabase_client.table("matches").select("*").execute().data
    ongoing_matches = [
        match["id"] for match in matches if match["status"] in ongoing_match_statuses
    ]
    users = supabase_client.table("sessions").select("*").execute().data
    bets = supabase_client.table("bets").select("*").execute().data
    standings = []
    for user in users:
        user_bets = [bet for bet in bets if bet["user_id"] == user["id"]]
        potential_points = 0
        user_points = 0
        for bet in user_bets:
            fixture = next(
                fixture for fixture in matches if fixture["id"] == bet["match_id"]
            )
            if fixture["status"] in ["FT", "AET", "PEN"]:
                # Exact prediction
                if (
                    bet["predicted_home_goals"] == fixture["home_team_goals"]
                    and bet["predicted_away_goals"] == fixture["away_team_goals"]
                ):
                    user_points += 5
                # Goal difference
                elif (bet["predicted_home_goals"] - bet["predicted_away_goals"]) == (
                    fixture["home_team_goals"] - fixture["away_team_goals"]
                ):
                    user_points += 3
                # Predicted the winner
                elif (
                    (bet["predicted_home_goals"] > bet["predicted_away_goals"])
                    and (fixture["home_team_goals"] > fixture["away_team_goals"])
                ) or (
                    (bet["predicted_home_goals"] < bet["predicted_away_goals"])
                    and (fixture["home_team_goals"] < fixture["away_team_goals"])
                ):
                    user_points += 1
                else:
                    user_points += 0
            # If the fixture is ongoing, calculate the potential points the user can earn
            if bet["match_id"] in ongoing_matches:
                if (
                    bet["predicted_home_goals"] == fixture["home_team_goals"]
                    and bet["predicted_away_goals"] == fixture["away_team_goals"]
                ):
                    potential_points += 5
                # Goal difference
                elif (bet["predicted_home_goals"] - bet["predicted_away_goals"]) == (
                    fixture["home_team_goals"] - fixture["away_team_goals"]
                ):
                    potential_points += 3
                # Predicted the winner
                elif (
                    (bet["predicted_home_goals"] > bet["predicted_away_goals"])
                    and (fixture["home_team_goals"] > fixture["away_team_goals"])
                ) or (
                    (bet["predicted_home_goals"] < bet["predicted_away_goals"])
                    and (fixture["home_team_goals"] < fixture["away_team_goals"])
                ):
                    potential_points += 1
                else:
                    potential_points += 0
        standings.append(
            {
                "user_id": user["id"],
                "name": user["name"],
                "points": user_points,
                "potential_points": (
                    potential_points if len(ongoing_matches) != 0 else None
                ),
            }
        )
    # Sort the standings by points and then alphabetically by name
    standings.sort(key=lambda x: x["name"])
    standings.sort(key=lambda x: x["points"], reverse=True)
    # Rank the standings, take care of ties, for example, if two users have rank 1, the next should be 2
    current_rank = 1
    for i, user in enumerate(standings):
        if i == 0:
            user["rank"] = current_rank
        else:
            previous_user = standings[i - 1]
            if user["points"] == previous_user["points"]:
                user["rank"] = previous_user["rank"]
            else:
                current_rank += 1
                user["rank"] = current_rank
    return standings


def create_user_match_prediction(
    user_id: str,
    match_id: str,
    predicted_home_goals: int,
    predicted_away_goals: int,
) -> dict:
    match_data = (
        supabase_client.table("matches")
        .select("*")
        .eq("id", match_id)
        .execute()
        .data[0]
    )
    if not match_data["can_users_place_bets"]:
        raise ValueError("User cannot place a bet on this fixture")
    # It's possible that the user is trying to place a bet on a fixture that has already started but the fixtures were not updated
    # In this case check the timestamp of the fixture and update the fixtures if necessary
    if (
        datetime.datetime.now(datetime.UTC).timestamp()
        > datetime.datetime.fromisoformat(match_data["timestamp"]).timestamp()
    ):
        logging.info(
            "User is trying to place a bet on an ongoing match, updating fixtures"
        )
        todays_date = datetime.datetime.now(datetime.UTC).today()
        match_date = datetime.datetime(
            todays_date.year, todays_date.month, todays_date.day
        )
        update_match_data(
            league_ids=[match_data["league_id"]],
            season=match_data["season"],
            date=match_date,
        )
        create_user_match_prediction(
            user_id=user_id,
            match_id=match_id,
            predicted_home_goals=predicted_home_goals,
            predicted_away_goals=predicted_away_goals,
        )
    bet = Bet(
        user_id=user_id,
        match_id=match_id,
        predicted_home_goals=predicted_home_goals,
        predicted_away_goals=predicted_away_goals,
    )
    user_already_made_prediction_for_match = (
        supabase_client.table("bets")
        .select("*")
        .eq("user_id", user_id)
        .eq("match_id", match_id)
        .execute()
        .data
    )
    if user_already_made_prediction_for_match:
        bet_data = {
            "id": user_already_made_prediction_for_match[0]["id"],
            **bet.model_dump(),
        }
    else:
        bet_data = bet.model_dump()
    bet_in_db = BetInDB(
        **supabase_client.table("bets").upsert(bet_data).execute().data[0]
    )
    return bet_in_db.model_dump()


def get_user_bets(user_id: int) -> list[dict]:
    user_bets = (
        supabase_client.table("bets").select("*").eq("user_id", user_id).execute()
    )
    return user_bets.data
