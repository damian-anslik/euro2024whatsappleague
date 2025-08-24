from apscheduler.schedulers.background import BackgroundScheduler
import supabase
import requests
import dotenv
import postgrest.exceptions

import configparser
import logging
import os

try:
    dotenv.load_dotenv(dotenv.find_dotenv())
    config = configparser.ConfigParser()
    config.read("config.ini")
    supabase_client = supabase.create_client(
        supabase_key=os.getenv("SUPABASE_KEY"),
        supabase_url=os.getenv("SUPABASE_URL"),
    )
    bets_table = supabase_client.table(table_name=config.get("database", "bets_table"))
    leagues_table = supabase_client.table(
        table_name=config.get("database", "leagues_table")
    )
    matches_table = supabase_client.table(
        table_name=config.get("database", "matches_table")
    )
    match_checks_table = supabase_client.table(
        table_name=config.get("database", "match_checks_table")
    )
    scheduled_match_statuses = ["NS", "TBD"]
    regular_time_match_statuses = ["1H", "HT", "2H"]
    extra_time_match_statuses = ["ET", "BT", "P", "INT"]
    special_match_statuses = ["INT"]
    ongoing_match_statuses = (
        regular_time_match_statuses + extra_time_match_statuses + special_match_statuses
    )
    finished_in_regular_time_match_statuses = ["FT"]
    finished_in_extra_time_match_statuses = ["AET", "PEN"]
    finished_match_statuses = (
        finished_in_regular_time_match_statuses + finished_in_extra_time_match_statuses
    )
except Exception as e:
    logging.error(f"Error setting up database connection: {e}")
    raise e


def insert_bet(
    user_id: str, match_id: int, predicted_home_goals: int, predicted_away_goals: int
) -> dict:
    bet_data = {
        "user_id": user_id,
        "match_id": match_id,
        "predicted_home_goals": predicted_home_goals,
        "predicted_away_goals": predicted_away_goals,
    }
    try:
        response = bets_table.upsert(bet_data, on_conflict="match_id,user_id").execute()
        return response.data[0]
    except postgrest.exceptions.APIError as e:
        exception_message = e.message
        raise ValueError(exception_message)


def process_fixture(fixture: dict) -> dict:
    fixture_status = fixture["fixture"]["status"]["short"]
    return {
        "id": fixture["fixture"]["id"],
        "start_time": fixture["fixture"]["date"],
        "status": fixture_status,
        "can_users_place_bets": fixture_status in scheduled_match_statuses,
        "home_team_name": fixture["teams"]["home"]["name"],
        "away_team_name": fixture["teams"]["away"]["name"],
        "home_team_logo_url": fixture["teams"]["home"]["logo"],
        "away_team_logo_url": fixture["teams"]["away"]["logo"],
        "home_team_goals": fixture["goals"]["home"],
        "away_team_goals": fixture["goals"]["away"],
    }


def download_fixtures_for_league(league_id: str, season: str):
    request_url = f"https://{os.getenv('RAPIDAPI_BASE_URL')}/v3/fixtures"
    request_headers = {
        "X-RapidAPI-Key": os.getenv("RAPIDAPI_KEY"),
        "X-RapidAPI-Host": os.getenv("RAPIDAPI_BASE_URL"),
    }
    query_params = {
        "league": league_id,
        "season": season,
    }
    response = requests.get(
        url=request_url,
        headers=request_headers,
        params=query_params,
    )
    response_data = response.json()["response"]
    processed_fixtures = [process_fixture(fixture) for fixture in response_data]
    return processed_fixtures


def upsert_fixtures():
    # Get a list of all of the leagues we are tracking
    tracked_leagues = leagues_table.select("*").eq("update_matches", True).execute()
    # For each league, download the fixtures for the current season and upsert them into the database
    for league in tracked_leagues.data:
        newly_downloaded_league_fixture = download_fixtures_for_league(
            league_id=league["league_id"], season=league["season"]
        )
        # Add the foreign key to league.id field
        for fixture in newly_downloaded_league_fixture:
            fixture["league_id"] = league["id"]
        matches_table.upsert_multiple(newly_downloaded_league_fixture, on_conflict="id")


def calculate_bet_points(
    predicted_home_goals: int,
    predicted_away_goals: int,
    actual_home_goals: int,
    actual_away_goals: int,
) -> int:
    if (
        predicted_home_goals == actual_home_goals
        and predicted_away_goals == actual_away_goals
    ):
        return 5
    elif (predicted_home_goals - predicted_away_goals) == (
        actual_home_goals - actual_away_goals
    ):
        return 3
    elif (
        (
            predicted_home_goals > predicted_away_goals
            and actual_home_goals > actual_away_goals
        )
        or (
            predicted_home_goals < predicted_away_goals
            and actual_home_goals < actual_away_goals
        )
        or (
            predicted_home_goals == predicted_away_goals
            and actual_home_goals == actual_away_goals
        )
    ):
        return 1
    else:
        return 0


def list_all_users() -> dict[str, str]:
    # Returns a list of mapping of user_id to user_name
    users = supabase_client.auth.admin.list_users()
    user_id_name_mapping = {}
    for user in users:
        user_id_name_mapping[user.id] = user.user_metadata.get("username")
    return user_id_name_mapping


def calculate_current_standings() -> list[dict]:
    def calculate_user_points(matches_and_bets: list[dict]) -> dict[str, int]:
        # Returns a dictionary mapping user_id to points
        user_points_mapping = {}
        for match in matches_and_bets:
            if match["status"] not in finished_match_statuses:
                continue
            actual_home_goals = match["home_team_goals"]
            actual_away_goals = match["away_team_goals"]
            for bet in match["bets"]:
                user_id = bet["user_id"]
                if user_id not in user_points_mapping:
                    user_points_mapping[user_id] = 0
                predicted_home_goals = bet["predicted_home_goals"]
                predicted_away_goals = bet["predicted_away_goals"]
                points = calculate_bet_points(
                    predicted_home_goals,
                    predicted_away_goals,
                    actual_home_goals,
                    actual_away_goals,
                )
                user_points_mapping[user_id] += points
        return user_points_mapping

    def calculate_user_potential_points(matches_and_bets: list[dict]) -> dict[str, int]:
        # Returns a dictionary mapping user_id to potential points
        user_potential_points_mapping = {}
        for match in matches_and_bets:
            if match["status"] not in regular_time_match_statuses:
                continue
            actual_home_goals = match["home_team_goals"]
            actual_away_goals = match["away_team_goals"]
            for bet in match["bets"]:
                user_id = bet["user_id"]
                if user_id not in user_potential_points_mapping:
                    user_potential_points_mapping[user_id] = 0
                predicted_home_goals = bet["predicted_home_goals"]
                predicted_away_goals = bet["predicted_away_goals"]
                points = calculate_bet_points(
                    predicted_home_goals,
                    predicted_away_goals,
                    actual_home_goals,
                    actual_away_goals,
                )
                user_potential_points_mapping[user_id] += points
        return user_potential_points_mapping

    def calculate_user_points_in_last_n_finished_matches(
        matches_and_bets: list[dict],
        user_ids: list[str],
        n: int = 5,
    ) -> dict[str, list[int]]:
        # Returns a dictionary mapping user_id to a list of points in last n finished matches
        user_points_in_last_n_finished_matches_mapping = {}
        finished_matches = [
            match
            for match in matches_and_bets
            if match["status"] in finished_match_statuses
        ]
        finished_matches.sort(key=lambda x: x["start_time"], reverse=True)
        last_n_finished_matches = finished_matches[:n]
        for match in last_n_finished_matches:
            actual_home_goals = match["home_team_goals"]
            actual_away_goals = match["away_team_goals"]
            # Track which users have placed bets in this match, if user did not place a bet, they get 0 points
            users_who_placed_bets_in_match = []
            for bet in match["bets"]:
                user_id = bet["user_id"]
                users_who_placed_bets_in_match.append(user_id)
                if user_id not in user_points_in_last_n_finished_matches_mapping:
                    user_points_in_last_n_finished_matches_mapping[user_id] = []
                predicted_home_goals = bet["predicted_home_goals"]
                predicted_away_goals = bet["predicted_away_goals"]
                points = calculate_bet_points(
                    predicted_home_goals,
                    predicted_away_goals,
                    actual_home_goals,
                    actual_away_goals,
                )
                user_points_in_last_n_finished_matches_mapping[user_id].append(points)
            users_who_did_not_place_bets_in_match = [
                user_id
                for user_id in user_ids
                if user_id not in users_who_placed_bets_in_match
            ]
            for user_id in users_who_did_not_place_bets_in_match:
                if user_id not in user_points_in_last_n_finished_matches_mapping:
                    user_points_in_last_n_finished_matches_mapping[user_id] = []
                user_points_in_last_n_finished_matches_mapping[user_id].append(0)
        # Reverse the lists so that the most recent match is last
        for user_id in user_points_in_last_n_finished_matches_mapping:
            user_points_in_last_n_finished_matches_mapping[user_id].reverse()
        return user_points_in_last_n_finished_matches_mapping

    matches_and_bets = (
        matches_table.select(
            "id, status, home_team_goals, away_team_goals, start_time, bets(user_id, predicted_home_goals, predicted_away_goals)"
        )
        .eq("show", True)
        .order("start_time", desc=True)
        .execute()
        .data
    )
    users = list_all_users()
    user_ids = list(users.keys())
    user_points_mapping = calculate_user_points(matches_and_bets)
    user_potential_points_mapping = calculate_user_potential_points(matches_and_bets)
    user_points_in_last_n_finished_matches_mapping = (
        calculate_user_points_in_last_n_finished_matches(matches_and_bets, user_ids, 5)
    )
    # Create the standings list
    standings = []
    for user_id in user_ids:
        standings.append(
            {
                "user_id": user_id,
                "name": users.get(user_id, "User: " + user_id),
                "points": user_points_mapping.get(user_id, 0),
                "potential_points": user_potential_points_mapping.get(user_id, 0),
                "points_in_last_n_finished_matches": user_points_in_last_n_finished_matches_mapping.get(
                    user_id, []
                ),
            }
        )
    # Rank the standings by total points + potential points
    standings.sort(key=lambda x: (x["points"] + x["potential_points"]), reverse=True)
    for index, entry in enumerate(standings):
        entry["rank"] = index + 1
    return standings


def get_user_bets_handler(user_id: str) -> list[dict]:
    user_bets = bets_table.select("*").eq("user_id", user_id).execute().data
    return user_bets


def get_matches_handler() -> dict[str, list[dict]]:
    matches_and_bets = (
        matches_table.select("*, bets(*)")
        .eq("show", True)
        .order("start_time", desc=True)
        .execute()
        .data
    )
    upcoming_matches = [
        match
        for match in matches_and_bets
        if match["status"] in scheduled_match_statuses
    ]
    # Remove bets from upcoming matches so that users cannot see other users' bets before a match starts
    for match in upcoming_matches:
        match.pop("bets", None)
    # Sort upcoming matches by start_time ascending and then alphabetically by home_team_name
    upcoming_matches.sort(key=lambda x: x["home_team_name"])
    upcoming_matches.sort(key=lambda x: x["start_time"])
    ongoing_matches = [
        match for match in matches_and_bets if match["status"] in ongoing_match_statuses
    ]
    finished_matches = [
        match
        for match in matches_and_bets
        if match["status"] in finished_match_statuses
    ]
    # Sort finished matches by start_time descending
    finished_matches.sort(key=lambda x: x["start_time"], reverse=True)
    SHOW_LAST_N_FINISHED_MATCHES = 10
    if len(finished_matches) > SHOW_LAST_N_FINISHED_MATCHES:
        finished_matches = finished_matches[:SHOW_LAST_N_FINISHED_MATCHES]
    return {
        "upcoming": upcoming_matches,
        "ongoing": ongoing_matches,
        "finished": finished_matches,
    }


if __name__ == "__main__":
    # upsert_fixtures()
    insert_bet("140fdf69-3cbb-4c58-b760-8c7de3635327", 1435555, 1, 4)
