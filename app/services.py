import requests
import datetime
import supabase
import logging
import os

supabase_client = supabase.create_client(
    supabase_key=os.getenv("SUPABASE_KEY"),
    supabase_url=os.getenv("SUPABASE_URL"),
)
bets_table = supabase_client.table("bets")
sessions_table = supabase_client.table("sessions")
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
        parsed_fixture = {
            "id": fixture["fixture"]["id"],
            "timestamp": datetime.datetime.fromtimestamp(
                fixture["fixture"]["timestamp"]
            ).isoformat(),
            "status": fixture["fixture"]["status"]["short"],
            "can_users_place_bets": can_user_place_bet,
            "home_team_name": fixture["teams"]["home"]["name"],
            "away_team_name": fixture["teams"]["away"]["name"],
            "home_team_logo": fixture["teams"]["home"]["logo"],
            "away_team_logo": fixture["teams"]["away"]["logo"],
            "home_team_goals": fixture["goals"]["home"],
            "home_team_goals": fixture["goals"]["away"],
        }
        parsed_fixtures.append(parsed_fixture)
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
    # Checks if current time is greater than the timestamp of the fixture and the fixture is not yet finished
    has_ongoing_matches = any(
        (
            datetime.datetime.now(datetime.UTC).timestamp()
            > datetime.datetime.fromisoformat(match["timestamp"]).timestamp()
        )
        and (match["status"] not in ["FT", "PST"])
        for match in stored_match_details
    )
    ALLOW_REQUESTS_EVERY_N_MINS = 5
    # Checks if the fixtures were updated in the last 5 mins
    had_update_in_last_5_mins = any(
        datetime.datetime.now(datetime.UTC).timestamp()
        - datetime.datetime.fromisoformat(fixture["updated_at"]).timestamp()
        < 60 * ALLOW_REQUESTS_EVERY_N_MINS
        for fixture in stored_match_details
    )
    if has_ongoing_matches and not had_update_in_last_5_mins:
        logging.info(
            "Has ongoing matches and fixtures were not updated in the last 5 mins"
        )
        # If there are ongoing matches and the fixtures were not updated in the last 5 mins, update the fixtures
        new_match_details = get_matches_from_api(league_id, season, date)
        for match_details in new_match_details:
            supabase_client.table("matches").upsert(match_details).execute()
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
    standings = []
    for user in users:
        user_bets = get_user_bets(user["id"])
        user_points = 0
        for bet in user_bets:
            fixture = next(
                fixture for fixture in matches if fixture["id"] == bet["match_id"]
            )
            if fixture["status"] == "FT":
                # Exact prediction
                if (
                    bet["home_goals"] == fixture["home_goals"]
                    and bet["away_goals"] == fixture["away_goals"]
                ):
                    user_points += 3
                # Goal difference
                elif (bet["home_goals"] - bet["away_goals"]) == (
                    fixture["home_goals"] - fixture["away_goals"]
                ):
                    user_points += 3
                # Predicted the winner
                elif (
                    (bet["home_goals"] > bet["away_goals"])
                    and (fixture["home_goals"] > fixture["away_goals"])
                ) or (
                    (bet["home_goals"] < bet["away_goals"])
                    and (fixture["home_goals"] < fixture["away_goals"])
                ):
                    user_points += 1
                else:
                    user_points += 0
        standings.append(
            {"user_id": user["id"], "name": user["name"], "points": user_points}
        )
    standings.sort(key=lambda x: x["points"], reverse=True)
    # Rank the standings, take care of ties
    for i, user in enumerate(standings):
        if i == 0:
            user["rank"] = 1
        else:
            previous_user = standings[i - 1]
            if user["points"] == previous_user["points"]:
                user["rank"] = previous_user["rank"]
            else:
                user["rank"] = i + 1
    return standings


def place_bet(user_id: str, match_id: str, home_goals: int, away_goals: int) -> dict:
    match_data = (
        supabase_client.table("matches")
        .select("*")
        .eq("id", match_id)
        .execute()
        .data[0]
    )
    if not match_data["can_users_place_bets"]:
        return {"error": "Cannot bet on a fixture that has started or finished"}
    bet = {
        "user_id": user_id,
        "match_id": match_id,
        "predicted_home_goals": home_goals,
        "predicted_away_goals": away_goals,
    }
    supabase_client.table("bets").upsert(bet).execute()
    return bet


def get_user_bets(user_id: int) -> list[dict]:
    user_bets = (
        supabase_client.table("bets").select("*").eq("user_id", user_id).execute()
    )
    return user_bets.data


def create_user_session(name: str) -> str:
    response_data = (
        supabase_client.table("sessions").insert({"name": name}).execute().data
    )
    session_id = response_data[0]["id"]
    return session_id


def check_user_session(session_id: str) -> bool:
    session = (
        supabase_client.table("sessions")
        .select("*")
        .eq("id", session_id)
        .execute()
        .data
    )
    if not session:
        return False
    return True
