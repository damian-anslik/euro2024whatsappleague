import os
import time
import logging
import datetime

import requests
import supabase

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
            "date": datetime.datetime(date.year, date.month, date.day).strftime(
                "%Y-%m-%d"
            ),
            "league": league_id,
            "season": season,
        }
        logging.info(f"Fetching fixtures for league_id: {league_id}")
        response = requests.get(url, headers=headers, params=querystring)
        response_data = response.json()["response"]
        for fixture in response_data:
            print(response_data)
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
                    "show": False,
                }
            )
    return parsed_fixtures


def get_matches_for_given_date(
    date: datetime.datetime,
) -> list[dict]:
    start_of_day = datetime.datetime(
        date.year, date.month, date.day, 0, 0, 0, tzinfo=datetime.UTC
    )
    end_of_day = datetime.datetime(
        date.year, date.month, date.day, 23, 59, 59, tzinfo=datetime.UTC
    )
    response_data = (
        supabase_client.table("matches")
        .select("*")
        .gt("timestamp", start_of_day.isoformat())
        .lt("timestamp", end_of_day.isoformat())
        .order("timestamp")
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
    logging.info(
        f"Updating match data for date: {date.date().strftime('%Y-%m-%d')}; league_ids: {league_ids}"
    )
    matches_in_db = get_matches_for_given_date(date)
    if not matches_in_db:
        match_check_string = (
            f"{','.join(league_ids)}-{season}-{date.date().strftime('%Y-%m-%d')}"
        )
        # It is possible that there are no matches on a given date, in this case, we should check if we already checked for matches today
        if did_check_for_matches_today(match_check_string):
            logging.info(
                f"No matches in DB for league_ids={league_ids}; already checked for matches today"
            )
            return
        logging.info(
            f"No matches found in the DB for league_ids={league_ids}; fetching from the API for first time"
        )
        todays_matches = get_matches_from_api(league_ids, season, date)
        supabase_client.table("matches").upsert(todays_matches).execute()
        # Log that we checked for matches today
        supabase_client.table("match_checks").insert(match_check_string).execute()
        return
    # Only update matches that are shown and are ongoing
    shown_matches = [match for match in matches_in_db if match["show"]]
    ongoing_matches = []
    for match in shown_matches:
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
    logging.info(f"Ongoing matches: {ongoing_matches}")
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
    logging.info(f"Updating fixtures for league_ids: {ongoing_match_league_ids}")
    todays_matches = get_matches_from_api(ongoing_match_league_ids, season, date)
    updated_data = []
    # The API will return all matches, even the ones we don't want to show, show is set to False by default, so we need to update the show field for the matches we want to show
    for match in todays_matches:
        match_in_db = next(
            match_in_db
            for match_in_db in matches_in_db
            if match_in_db["id"] == match["id"]
        )
        match["show"] = match_in_db["show"]
        updated_data.append(match)
    supabase_client.table("matches").upsert(updated_data).execute()


def calculate_points_for_bet(bet_data: dict, match_data: dict) -> int:
    # Exact prediction
    if (
        bet_data["predicted_home_goals"] == match_data["home_team_goals"]
        and bet_data["predicted_away_goals"] == match_data["away_team_goals"]
    ):
        return 5
    # Goal difference
    elif (bet_data["predicted_home_goals"] - bet_data["predicted_away_goals"]) == (
        match_data["home_team_goals"] - match_data["away_team_goals"]
    ):
        return 3
    # Predicted the winner
    elif (
        (bet_data["predicted_home_goals"] > bet_data["predicted_away_goals"])
        and (match_data["home_team_goals"] > match_data["away_team_goals"])
    ) or (
        (bet_data["predicted_home_goals"] < bet_data["predicted_away_goals"])
        and (match_data["home_team_goals"] < match_data["away_team_goals"])
    ):
        return 1
    return 0


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
        user_points = 0
        potential_points = 0
        for bet in user_bets:
            fixture = next(
                fixture for fixture in matches if fixture["id"] == bet["match_id"]
            )
            if fixture["status"] in finished_match_statuses:
                user_points += calculate_points_for_bet(bet, fixture)
            # If the fixture is ongoing, calculate the potential points the user can earn
            if bet["match_id"] in ongoing_matches:
                potential_points += calculate_points_for_bet(bet, fixture)
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
    has_match_potentially_started = (
        datetime.datetime.now(datetime.UTC).timestamp()
        > datetime.datetime.fromisoformat(match_data["timestamp"]).timestamp()
    )
    if has_match_potentially_started:
        logging.info(
            "User is trying to place a bet on a what may be an ongoing match, updating fixtures"
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
    bet_data = {
        "user_id": user_id,
        "match_id": match_id,
        "predicted_home_goals": predicted_home_goals,
        "predicted_away_goals": predicted_away_goals,
    }
    user_already_made_prediction_for_match = (
        supabase_client.table("bets")
        .select("*")
        .eq("user_id", user_id)
        .eq("match_id", match_id)
        .execute()
        .data
    )
    if user_already_made_prediction_for_match:
        bet_data.update({"id": user_already_made_prediction_for_match[0]["id"]})
    bet_creation_response = supabase_client.table("bets").upsert(bet_data).execute()
    return bet_creation_response.data[0]


def get_user_bets(user_id: int) -> list[dict]:
    user_bets = (
        supabase_client.table("bets").select("*").eq("user_id", user_id).execute()
    )
    return user_bets.data
