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


def get_matches_from_api(
    league_id: str, season: str, date: datetime.datetime
) -> list[dict]:
    url = f"https://{os.getenv('RAPIDAPI_BASE_URL')}/v3/fixtures"
    querystring = {
        "date": date.date().strftime("%Y-%m-%d"),
        "league": league_id,
        "season": season,
    }
    headers = {
        "X-RapidAPI-Key": os.getenv("RAPIDAPI_KEY"),
        "X-RapidAPI-Host": os.getenv("RAPIDAPI_BASE_URL"),
    }
    response = requests.get(url, headers=headers, params=querystring)
    parsed_fixtures = []
    for fixture in response.json()["response"]:
        fixture_status = fixture["fixture"]["status"]["short"]
        can_user_place_bet = fixture_status in ["NS", "TBD"]
        parsed_fixture = Match(
            id=fixture["fixture"]["id"],
            timestamp=datetime.datetime.fromtimestamp(
                fixture["fixture"]["timestamp"],
                datetime.UTC,
            ).isoformat(),
            status=fixture_status,
            can_users_place_bets=can_user_place_bet,
            home_team_name=fixture["teams"]["home"]["name"],
            away_team_name=fixture["teams"]["away"]["name"],
            home_team_logo=fixture["teams"]["home"]["logo"],
            away_team_logo=fixture["teams"]["away"]["logo"],
            home_team_goals=fixture["goals"]["home"],
            away_team_goals=fixture["goals"]["away"],
            updated_at=datetime.datetime.now(datetime.UTC).isoformat(),
        )
        parsed_fixtures.append(parsed_fixture.model_dump())
    return parsed_fixtures


def get_matches(league_id: str, season: str, date: datetime.datetime) -> list[dict]:
    """
    1. Check if the fixtures for the day are already stored in the DB
    2. If not, make a request to the API to get the fixtures for the day
    3. Store the fixtures in the DB
    4. On subsequent requests, check if there are ongoing matches
    5. If there are ongoing matches, update the fixtures in the DB every 5 mins
    6. Return the fixtures sorted by timestamp and whether the user can bet on them
    """
    stored_match_details = (
        supabase_client.table("matches")
        .select("*")
        .gt("timestamp", date.isoformat())
        .lt("timestamp", (date + datetime.timedelta(days=1)).isoformat())
        .execute()
        .data
    )
    if not stored_match_details:
        logging.info("No fixtures found in the DB, fetching from the API")
        todays_matches = get_matches_from_api(league_id, season, date)
        supabase_client.table("matches").upsert(todays_matches).execute()
        todays_matches = sorted(stored_match_details, key=lambda x: x["timestamp"])
        todays_matches = sorted(
            stored_match_details, key=lambda x: x["can_users_place_bets"], reverse=True
        )
        return todays_matches
    parsed_matches = [Match(**match) for match in stored_match_details]
    # Checks if current time is greater than the timestamp of the fixture and the fixture is not yet finished
    has_ongoing_matches = any(
        datetime.datetime.now(datetime.UTC).timestamp()
        > datetime.datetime.fromisoformat(match.timestamp).timestamp()
        and match.status not in ["FT", "PST"]
        for match in parsed_matches
    )
    # Checks if the fixtures were updated in the last 5 mins
    has_update_in_last_5_mins = any(
        datetime.datetime.now(datetime.UTC).timestamp()
        - datetime.datetime.fromisoformat(match.updated_at).timestamp()
        < 60 * 5
        for match in parsed_matches
    )
    if has_ongoing_matches and not has_update_in_last_5_mins:
        logging.info(
            "Has ongoing matches and fixtures were not updated in the last 5 mins"
        )
        # If there are ongoing matches and the fixtures were not updated in the last 5 mins, update the fixtures
        new_match_details = get_matches_from_api(league_id, season, date)
        supabase_client.table("matches").upsert(new_match_details).execute()
        new_match_details = sorted(new_match_details, key=lambda x: x["timestamp"])
        new_match_details = sorted(
            new_match_details, key=lambda x: x["can_users_place_bets"], reverse=True
        )
        return new_match_details
    else:
        logging.info("No ongoing matches or fixtures were updated in the last 5 mins")
        # If there are no ongoing matches or the fixtures were updated in the last 5 mins, return the stored fixtures
        stored_match_details = sorted(
            stored_match_details, key=lambda x: x["timestamp"]
        )
        stored_match_details = sorted(
            stored_match_details, key=lambda x: x["can_users_place_bets"], reverse=True
        )
        return stored_match_details


def get_current_standings() -> list[dict]:
    matches = supabase_client.table("matches").select("*").execute().data
    users = supabase_client.table("sessions").select("*").execute().data
    bets = supabase_client.table("bets").select("*").execute().data
    standings = []
    for user in users:
        user_bets = [bet for bet in bets if bet["user_id"] == user["id"]]
        user_points = 0
        for bet in user_bets:
            fixture = next(
                fixture for fixture in matches if fixture["id"] == bet["match_id"]
            )
            if fixture["status"] == "FT":
                # Exact prediction
                if (
                    bet["predicted_home_goals"] == fixture["home_team_goals"]
                    and bet["predicted_away_goals"] == fixture["away_team_goals"]
                ):
                    user_points += 3
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
        standings.append(
            {"user_id": user["id"], "name": user["name"], "points": user_points}
        )
    standings.sort(key=lambda x: x["points"], reverse=True)
    # # Rank the standings, take care of ties, for example, if two users have rank 1, the next should be 2
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
        return {"error": "Cannot bet on a fixture that has started or finished"}
    bet = Bet(
        user_id=user_id,
        match_id=match_id,
        predicted_home_goals=predicted_home_goals,
        predicted_away_goals=predicted_away_goals,
    )
    bet_in_db = BetInDB(
        **supabase_client.table("bets").upsert(bet.model_dump()).execute().data[0]
    )
    return bet_in_db.model_dump()


def get_user_bets(user_id: int) -> list[dict]:
    user_bets = (
        supabase_client.table("bets").select("*").eq("user_id", user_id).execute()
    )
    return user_bets.data
