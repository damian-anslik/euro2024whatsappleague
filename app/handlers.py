import postgrest.exceptions
import supabase
import requests
import dotenv
import bs4

import configparser
import functools
import datetime
import hashlib
import logging
import os

import app.auth

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
    double_points_table = supabase_client.table(
        table_name=config.get("database", "double_points_table")
    )
    match_links_table = supabase_client.table(
        table_name="matchLinks"
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
    user_id: str,
    match_id: int,
    predicted_home_goals: int,
    predicted_away_goals: int,
    use_double_points: bool = False,
) -> dict:
    bet_data = {
        "user_id": user_id,
        "match_id": match_id,
        "predicted_home_goals": predicted_home_goals,
        "predicted_away_goals": predicted_away_goals,
    }
    try:
        # Insert the bet
        response = bets_table.upsert(bet_data, on_conflict="match_id,user_id").execute()
        bet_id = response.data[0]["id"]
        # Calculate how many double points the user has used on other bets
        MAX_NUMBER_DOUBLE_POINTS = config.getint("default", "max_number_wildcards")
        current_double_points = (
            double_points_table.select("bet_id").eq("user_id", user_id).execute().data
        )
        num_double_points_used = len(
            [dp for dp in current_double_points if dp["bet_id"] != bet_id]
        )
        if use_double_points and num_double_points_used >= MAX_NUMBER_DOUBLE_POINTS:
            # Delete the bet that was just inserted/updated to keep data consistent
            bets_table.delete().eq("id", response.data[0]["id"]).execute()
            # Return an error
            raise ValueError(
                f"You have already used your maximum of {MAX_NUMBER_DOUBLE_POINTS} double points."
            )
        # If use_double_points is True and user does not have double_points already enabled for this bet, insert into double_points_table, otherwise delete from double_points_table if it exists
        if use_double_points and not any(
            dp for dp in current_double_points if dp["bet_id"] == bet_id
        ):
            double_points_table.upsert(
                {"bet_id": bet_id, "user_id": user_id}, on_conflict="bet_id,user_id"
            ).execute()
        elif not use_double_points and any(
            dp for dp in current_double_points if dp["bet_id"] == bet_id
        ):
            # Check if there is an existing double points entry for this bet, if so, delete it
            double_points_table.delete().eq("bet_id", bet_id).eq(
                "user_id", user_id
            ).execute()
        # Clear the cache for get_user_bets_handler when a bet is inserted
        get_user_bets_handler.cache_clear()
        calculate_current_standings.cache_clear()
        return {
            **response.data[0],
            "use_double_points": use_double_points,
        }
    except postgrest.exceptions.APIError as e:
        exception_message = e.message
        raise ValueError(exception_message)


def upsert_fixtures(force: bool = False) -> list[dict]:
    def process_fixture(fixture: dict) -> dict:
        fixture_status = fixture["fixture"]["status"]["short"]
        match_start_time = datetime.datetime.fromisoformat(fixture["fixture"]["date"])
        # Users can only place bets if the match is scheduled and the start time is in the future
        if (fixture_status not in scheduled_match_statuses) or (
            fixture_status in scheduled_match_statuses
            and match_start_time <= datetime.datetime.now(datetime.timezone.utc)
        ):
            can_users_place_bets = False
        else:
            can_users_place_bets = True
        return {
            "id": fixture["fixture"]["id"],
            "start_time": fixture["fixture"]["date"],
            "status": fixture_status,
            "can_users_place_bets": can_users_place_bets,
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

    # Get a list of all of the leagues we are tracking
    tracked_leagues = leagues_table.select("*").eq("update_matches", True).execute()
    # If not Force, we only want to download fixtures if there are ongoing matches
    if not force:
        previously_downloaded_fixtures = matches_table.select("*").execute().data
        # Check if there are any ongoing matches, e.g. matches that have status in ongoing_match_statuses or matches that are scheduled to start now
        ongoing_matches = [
            match
            for match in previously_downloaded_fixtures
            if match["status"] in ongoing_match_statuses
            or (
                match["status"] in scheduled_match_statuses
                and datetime.datetime.fromisoformat(match["start_time"])
                <= datetime.datetime.now(datetime.timezone.utc)
            )
        ]
        if len(ongoing_matches) == 0:
            return {
                "total_fixtures_upserted": 0,
                "fixture_ids": [],
            }
    all_upserted_fixtures = []
    for league in tracked_leagues.data:
        newly_downloaded_league_fixture = download_fixtures_for_league(
            league_id=league["league_id"], season=league["season"]
        )
        # Add the foreign key to league.id field
        for fixture in newly_downloaded_league_fixture:
            fixture["league_id"] = league["id"]
        upsert_response = matches_table.upsert(
            newly_downloaded_league_fixture, on_conflict="id"
        ).execute()
        all_upserted_fixtures.extend(upsert_response.data)
    response_data = {
        "total_fixtures_upserted": len(all_upserted_fixtures),
        "fixture_ids": [f["id"] for f in all_upserted_fixtures],
    }
    # Clear the cache for get_matches_handler and calculate_current_standings when fixtures are upserted
    get_matches_handler.cache_clear()
    calculate_current_standings.cache_clear()
    return response_data


@functools.lru_cache(maxsize=100)
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


@functools.lru_cache(maxsize=1)
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
                has_double_points = len(bet.get("doublePoints", [])) > 0
                if has_double_points:
                    points *= 2
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
                has_double_points = len(bet.get("doublePoints", [])) > 0
                if has_double_points:
                    points *= 2
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
                has_double_points = len(bet.get("doublePoints", [])) > 0
                if has_double_points:
                    points *= 2
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

    def calculate_num_double_points_used(matches_and_bets: list[dict]) -> dict[str, int]:
        user_double_points_mapping = {}
        for match in matches_and_bets:
            if match["status"] in scheduled_match_statuses:
                continue
            for bet in match["bets"]:
                if len(bet.get("doublePoints", []))==0:
                    continue
                user_id = bet["user_id"]
                if user_id not in user_double_points_mapping:
                    user_double_points_mapping[user_id] = 0
                user_double_points_mapping[user_id] += 1
        return user_double_points_mapping

    matches_and_bets = (
        matches_table.select(
            "id, status, home_team_goals, away_team_goals, start_time, bets(user_id, predicted_home_goals, predicted_away_goals, doublePoints(*))"
        )
        .eq("show", True)
        .order("start_time", desc=True)
        .execute()
        .data
    )
    users = {
        user.id: user.user_metadata.get("username") for user in app.auth.list_users()
    }
    user_ids = list(users.keys())
    user_points_mapping = calculate_user_points(matches_and_bets)
    user_potential_points_mapping = calculate_user_potential_points(matches_and_bets)
    user_points_in_last_n_finished_matches_mapping = (
        calculate_user_points_in_last_n_finished_matches(matches_and_bets, user_ids, 5)
    )
    user_double_points_mapping = calculate_num_double_points_used(matches_and_bets)
    # Create the standings list
    num_double_points_allowed = config.getint("default", "max_number_wildcards")
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
                "num_double_points_remaining": num_double_points_allowed - user_double_points_mapping.get(user_id, 0),
            }
        )
    # Rank the standings by total points + potential points
    standings.sort(key=lambda x: (-(x["points"] + x["potential_points"]), x["name"].lower()), reverse=False)
    for index, entry in enumerate(standings):
        entry["rank"] = index + 1
    return standings


@functools.lru_cache(maxsize=100)
def get_user_bets_handler(user_id: str) -> list[dict]:
    user_bets = (
        bets_table.select("*", "doublePoints(*)").eq("user_id", user_id).execute().data
    )
    processed_user_bets = []
    for bet in user_bets:
        use_double_points = len(bet.get("doublePoints", [])) > 0
        bet.pop("doublePoints", None)
        processed_user_bets.append(
            {
                **bet,
                "use_double_points": use_double_points,
            }
        )
    return processed_user_bets


@functools.lru_cache(maxsize=1)
def get_matches_handler(
    show_matches_n_days_ahead: int = 7, show_matches_n_days_behind: int = 2
) -> dict[str, list[dict]]:
    # Only show matches that are in dates between now - show_matches_n_days_behind and now + show_matches_n_days_ahead
    matches_and_bets = (
        matches_table.select("*, bets(*, doublePoints(id)), leagues(name), matchLinks(url)")
        .eq("show", True)
        .gte(
            "start_time",
            (
                datetime.datetime.now(datetime.timezone.utc)
                - datetime.timedelta(hours=show_matches_n_days_behind * 24)
            ).isoformat(),
        )
        .lt(
            "start_time",
            (
                datetime.datetime.now(datetime.timezone.utc)
                + datetime.timedelta(hours=show_matches_n_days_ahead * 24)
            ).isoformat(),
        )
        .order("start_time", desc=True)
        .execute()
        .data
    )
    # List all users
    users = {
        user.id: user.user_metadata.get("username") for user in app.auth.list_users()
    }
    # Remove bets from upcoming matches so that users cannot see other users' bets before a match starts
    upcoming_matches = [
        match
        for match in matches_and_bets
        if match["status"] in scheduled_match_statuses
    ]
    for match in upcoming_matches:
        match.pop("bets", None)
    # Sort upcoming matches by start_time ascending and then alphabetically by home_team_name
    upcoming_matches.sort(key=lambda x: x["home_team_name"])
    upcoming_matches.sort(key=lambda x: x["start_time"])
    ongoing_matches = [
        match for match in matches_and_bets if match["status"] in ongoing_match_statuses
    ]
    for match in ongoing_matches:
        if "bets" not in match:
            continue
        for bet in match["bets"]:
            bet["user"] = {"name": users.get(bet["user_id"], "User: " + bet["user_id"])}
    # Sort finished matches by start_time descending
    finished_matches = [
        match
        for match in matches_and_bets
        if match["status"] in finished_match_statuses
    ]
    for match in finished_matches:
        match.pop("matchLinks", None)
    for match in finished_matches:
        if "bets" not in match:
            continue
        for bet in match["bets"]:
            bet["user"] = {"name": users.get(bet["user_id"], "User: " + bet["user_id"])}
    finished_matches.sort(key=lambda x: x["start_time"], reverse=True)
    return {
        "ongoing": ongoing_matches,
        "upcoming": upcoming_matches,
        "finished": finished_matches,
    }


def upsert_fixture_links():
    response = requests.get("https://www.redditsoccerstreams.name/")
    response_html = bs4.BeautifulSoup(response.text, features="html.parser")
    matches_and_links = {}
    for tr in response_html.find("table").find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) == 3:
            match = tds[1].get_text(strip=True)
            match_hash = hashlib.sha256(match.encode()).hexdigest()
            team_names = match.split(" vs ", maxsplit=1)
            if len(team_names) != 2:
                continue
            home_team_name = team_names[0]
            away_team_name = team_names[1]
            if match_hash not in matches_and_links:
                matches_and_links[match_hash] = {
                    "home_team_name": home_team_name,
                    "away_team_name": away_team_name,
                    "links": [],
                }
            link = tds[2].find("a")["href"] if tds[2].find("a") else None
            if link is None:
                continue
            matches_and_links[match_hash]["links"].append(link)
    for _, details in matches_and_links.items():
        home_team_name = details["home_team_name"]
        away_team_name = details["away_team_name"]
        matches = matches_table.select("id").eq("home_team_name", home_team_name).eq("away_team_name", away_team_name).execute().data
        if len(matches)==0:
            continue
        match_id = matches[0]["id"]
        for link in details["links"]:
            match_links_table.upsert(
                {"match_id": match_id, "url": link}, on_conflict="match_id,url"
            ).execute()
        
