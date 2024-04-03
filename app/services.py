import requests
import datetime
import tinydb
import uuid

bets_db = tinydb.TinyDB("bets.json", indent=4)
users_db = tinydb.TinyDB("users.json", indent=4)
fixtures_db = tinydb.TinyDB("fixtures.json", indent=4)


def get_matches_from_api(
    league_id: str, season: str, date: datetime.datetime
) -> list[dict]:
    url = "https://api-football-v1.p.rapidapi.com/v3/fixtures"
    querystring = {
        "date": date.date().strftime("%Y-%m-%d"),
        "league": league_id,
        "season": season,
    }
    headers = {
        "X-RapidAPI-Key": "1b00e2a896msh42da2ffb9f236ffp133ebejsn0ea9e4845de1",
        "X-RapidAPI-Host": "api-football-v1.p.rapidapi.com",
    }
    response = requests.get(url, headers=headers, params=querystring)
    fixtures_updated_at = datetime.datetime.now(datetime.UTC).timestamp()
    parsed_fixtures = []
    for fixture in response.json()["response"]:
        fixture_status = fixture["fixture"]["status"]["short"]
        user_can_bet = fixture_status in ["NS", "TBD"]
        parsed_fixture = {
            "updated_at": fixtures_updated_at,
            "id": fixture["fixture"]["id"],
            "timestamp": fixture["fixture"]["timestamp"],
            "status": fixture["fixture"]["status"]["short"],
            "can_bet": user_can_bet,
            "home_team": fixture["teams"]["home"]["name"],
            "away_team": fixture["teams"]["away"]["name"],
            "home_team_logo": fixture["teams"]["home"]["logo"],
            "away_team_logo": fixture["teams"]["away"]["logo"],
            "home_goals": fixture["goals"]["home"],
            "away_goals": fixture["goals"]["away"],
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
    stored_match_details = fixtures_db.search(
        tinydb.where("timestamp") >= date.timestamp()
        and tinydb.where("timestamp") <= date.timestamp() + 24 * 60 * 60
    )
    if not stored_match_details:
        print("Fetching fixtures from API for the first time")
        todays_matches = get_matches_from_api(league_id, season, date)
        fixtures_db.insert_multiple(todays_matches)
        todays_matches = sorted(stored_match_details, key=lambda x: x["timestamp"])
        todays_matches = sorted(
            stored_match_details, key=lambda x: x["can_bet"], reverse=True
        )
        return todays_matches
    # Checks if current time is greater than the timestamp of the fixture and the fixture is not yet finished
    has_ongoing_matches = any(
        (datetime.datetime.now(datetime.UTC).timestamp() > fixture["timestamp"])
        and (fixture["status"] not in ["FT", "PST"])
        for fixture in stored_match_details
    )
    ALLOW_REQUESTS_EVERY_N_MINS = 5
    # Checks if the fixtures were updated in the last 5 mins
    had_update_in_last_5_mins = any(
        datetime.datetime.now(datetime.UTC).timestamp() - fixture["updated_at"]
        < 60 * ALLOW_REQUESTS_EVERY_N_MINS
        for fixture in stored_match_details
    )
    if has_ongoing_matches and not had_update_in_last_5_mins:
        print("Has ongoing matches and fixtures were not updated in the last 5 mins")
        # If there are ongoing matches and the fixtures were not updated in the last 5 mins, update the fixtures
        new_match_details = get_matches_from_api(league_id, season, date)
        for match_details in new_match_details:
            fixtures_db.upsert(match_details, tinydb.where("id") == match_details["id"])
        new_match_details = sorted(new_match_details, key=lambda x: x["timestamp"])
        new_match_details = sorted(
            new_match_details, key=lambda x: x["can_bet"], reverse=True
        )
        return new_match_details
    else:
        print("No ongoing matches or fixtures were updated in the last 5 mins")
        # If there are no ongoing matches or the fixtures were updated in the last 5 mins, return the stored fixtures
        stored_match_details = sorted(
            stored_match_details, key=lambda x: x["timestamp"]
        )
        stored_match_details = sorted(
            stored_match_details, key=lambda x: x["can_bet"], reverse=True
        )
        return stored_match_details


def get_current_standings() -> list[dict]:
    fixtures = fixtures_db.all()
    users = users_db.all()
    standings = []
    for user in users:
        user_bets = bets_db.search(tinydb.where("user_id") == user["user_id"])
        user_points = 0
        for bet in user_bets:
            fixture = next(
                fixture for fixture in fixtures if fixture["id"] == bet["fixture_id"]
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
            {"user_id": user["user_id"], "name": user["name"], "points": user_points}
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


def place_bet(user_id: str, fixture_id: str, home_goals: int, away_goals: int) -> dict:
    fixture = fixtures_db.get(tinydb.where("id") == fixture_id)
    if fixture["status"] not in ["NS", "TBD"]:
        return {"error": "Cannot bet on a fixture that has started or finished"}
    bet = {
        "user_id": user_id,
        "fixture_id": fixture_id,
        "home_goals": home_goals,
        "away_goals": away_goals,
    }
    bets_db.upsert(
        bet,
        tinydb.where("user_id") == user_id and tinydb.where("fixture_id") == fixture_id,
    )
    return bet


def get_user_bets(user_id: int) -> list[dict]:
    user_bets = bets_db.search(tinydb.where("user_id") == user_id)
    return user_bets


def create_user_session(name: str) -> str:
    session_id = str(uuid.uuid4())
    users_db.insert({"user_id": session_id, "name": name})
    return session_id


def check_user_session(session_id: str) -> bool:
    return bool(users_db.get(tinydb.where("user_id") == session_id))
