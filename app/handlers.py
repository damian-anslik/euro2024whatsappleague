from apscheduler.schedulers.background import BackgroundScheduler
import supabase
import requests
import pandas

import configparser
import functools
import datetime
import logging
import timeit
import copy
import io
import os

# import app.services
import app.auth


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


def get_matches_from_api(
    league_id: str,
    season: str,
    date: datetime.datetime,
    is_international: bool = False,
) -> list[dict]:
    url = f"https://{os.getenv('RAPIDAPI_BASE_URL')}/v3/fixtures"
    headers = {
        "X-RapidAPI-Key": os.getenv("RAPIDAPI_KEY"),
        "X-RapidAPI-Host": os.getenv("RAPIDAPI_BASE_URL"),
    }
    parsed_fixtures = []
    querystring = {
        "date": datetime.datetime(date.year, date.month, date.day).strftime("%Y-%m-%d"),
        "league": league_id,
        "season": season,
    }
    logging.info(
        f"Fetching fixtures for league_id: {league_id}, season: {season}, and date: {date}"
    )
    response = requests.get(url, headers=headers, params=querystring)
    response_data = response.json()["response"]
    for i, fixture in enumerate(response_data):
        fixture_status = fixture["fixture"]["status"]["short"]
        can_user_place_bet = fixture_status in scheduled_match_statuses
        if fixture_status in special_match_statuses:
            if fixture["score"]["fulltime"]["home"] is None:
                # Special status and match has either not started or is in regular time
                home_team_goals = fixture["goals"]["home"]
                away_team_goals = fixture["goals"]["away"]
            else:
                home_team_goals = fixture["score"]["fulltime"]["home"]
                away_team_goals = fixture["score"]["fulltime"]["away"]
        elif fixture_status in (
            extra_time_match_statuses + finished_in_extra_time_match_statuses
        ):
            if fixture["score"]["fulltime"]["home"] is None:
                home_team_goals = fixture["goals"]["home"]
                away_team_goals = fixture["goals"]["away"]
            else:
                home_team_goals = fixture["score"]["fulltime"]["home"]
                away_team_goals = fixture["score"]["fulltime"]["away"]
        else:
            home_team_goals = fixture["goals"]["home"]
            away_team_goals = fixture["goals"]["away"]
        home_team_logo = fixture["teams"]["home"]["logo"]
        away_team_logo = fixture["teams"]["away"]["logo"]
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
                "league_name": fixture["league"]["name"],
                "home_team_name": fixture["teams"]["home"]["name"],
                "away_team_name": fixture["teams"]["away"]["name"],
                "home_team_logo": home_team_logo,
                "away_team_logo": away_team_logo,
                "home_team_goals": home_team_goals,
                "away_team_goals": away_team_goals,
                "updated_at": (
                    datetime.datetime.now(datetime.UTC)
                    + datetime.timedelta(microseconds=i)
                ).isoformat(),  # Add a small delay to ensure that the matches are sorted correctly in case of same timestamp
                "show": False,
            }
        )
    return parsed_fixtures


def update_match_data(
    league_id: str,
    season: str,
    date: datetime.datetime,
    is_international: bool = False,
    show_by_default: bool = False,
    force_update: bool = False,
):
    logging.info(
        f"Updating match data for date: {date.date().strftime('%Y-%m-%d')}; league_id: {league_id}"
    )
    start_of_day = datetime.datetime(
        date.year, date.month, date.day, 0, 0, 0, tzinfo=datetime.UTC
    )
    end_of_day = datetime.datetime(
        date.year, date.month, date.day, 23, 59, 59, tzinfo=datetime.UTC
    )
    matches_in_db = (
        matches_table.select("*")
        .eq("show", True)
        .eq("league_id", league_id)
        .eq("season", season)
        .gte("timestamp", start_of_day.isoformat())
        .lt("timestamp", end_of_day.isoformat())
        .order("timestamp")
        .execute()
        .data
    )
    if not matches_in_db:
        # Check if we have already checked for matches for the day, if not we will fetch the matches from the API
        already_checked_for_matches = (
            match_checks_table.select("*")
            .eq("league_id", league_id)
            .eq("season", season)
            .eq("date", date.date().strftime("%Y-%m-%d"))
            .execute()
            .data
        )
        if already_checked_for_matches and not force_update:
            logging.info(
                f"No matches in DB for league_id={league_id} and date={date.date().strftime('%Y-%m-%d')}; already checked for matches today"
            )
            return
        logging.info(
            f"No matches found in the DB for league_id={league_id} and date={date.date().strftime('%Y-%m-%d')}; fetching from the API for first time"
        )
        todays_matches = get_matches_from_api(league_id, season, date, is_international)
        for match in todays_matches:
            match["show"] = show_by_default
        matches_table.upsert(todays_matches).execute()
        # Log that we checked for matches today
        match_checks_table.insert(
            {
                "league_id": league_id,
                "season": season,
                "date": date.date().strftime("%Y-%m-%d"),
            }
        ).execute()
        return
    # Only update matches that are shown and are ongoing
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
        logging.info(f"No ongoing matches found for league_id={league_id}")
        return
    logging.info(f"Ongoing matches: {ongoing_matches}; updating fixtures")
    updated_matches = get_matches_from_api(league_id, season, date, is_international)
    updated_data = []
    for match in updated_matches:
        match_in_db = next(
            match_in_db
            for match_in_db in matches_in_db
            if match_in_db["id"] == match["id"]
        )
        match["show"] = match_in_db["show"]
        # Don't update the match in DB already has status finished
        if match_in_db["status"] in finished_match_statuses:
            continue
        # Don't update the match if there is a discrepancy in the status (API returns NS, but match is ongoing)
        if match["status"] in scheduled_match_statuses and match_in_db["status"] in (
            ongoing_match_statuses + finished_match_statuses
        ):
            continue
        updated_data.append(match)
    logging.info(f"Updated data for league_id={league_id}: {updated_data}")
    get_matches_handler.cache_clear()
    get_current_standings.cache_clear()
    matches_table.upsert(updated_data).execute()


def scheduled_update_function(date: datetime.datetime):
    leagues = leagues_table.select("*").eq("update_matches", True).execute().data
    for league in leagues:
        try:
            update_match_data(
                league_id=str(league["id"]),
                season=league["season"],
                date=date,
                is_international=league["is_international"],
                show_by_default=league["show_by_default"],
            )
        except Exception as e:
            logging.error(f"Error updating data for league {league['id']}: {e}")


def configure_scheduler(update_interval_minutes: int = 5):
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        func=lambda: scheduled_update_function(
            datetime.datetime.now(datetime.UTC).today(),
        ),
        trigger="cron",
        minute=f"*/{update_interval_minutes}",
    )
    scheduler.add_job(
        func=lambda: scheduled_update_function(
            datetime.datetime.now(datetime.UTC).today() + datetime.timedelta(days=1),
        ),
        trigger="cron",
        minute=f"*/{update_interval_minutes+1}",
    )
    scheduler.start()


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


def change_user_username(user_id: str, new_username: str):
    return supabase_client.auth.admin.update_user_by_id(
        uid=user_id, attributes={"user_metadata": {"username": new_username}}
    )


@functools.lru_cache(maxsize=1)
def get_matches_handler(
    start_date: datetime.date, num_days_in_future: int = 1
) -> dict[str, list[dict]]:
    future_date = start_date + datetime.timedelta(days=num_days_in_future)
    response_data = (
        matches_table.select("*, bets(*)")
        .eq("show", True)
        .gte(
            "timestamp",
            datetime.datetime(
                start_date.year,
                start_date.month,
                start_date.day,
                0,
                0,
                0,
                tzinfo=datetime.UTC,
            ).isoformat(),
        )
        .lt(
            "timestamp",
            datetime.datetime(
                future_date.year,
                future_date.month,
                future_date.day,
                23,
                59,
                59,
                tzinfo=datetime.UTC,
            ).isoformat(),
        )
        .order("timestamp")
        .execute()
        .data
    )
    users = app.auth.list_users()
    user_id_to_username_map = {
        user.id: user.user_metadata["username"] for user in users
    }
    todays_matches = []
    future_matches = []
    for match in response_data:
        match_date = datetime.datetime.fromisoformat(match["timestamp"])
        if match_date.date() == start_date:
            can_users_place_bets = match["can_users_place_bets"]
            if can_users_place_bets:
                match["bets"] = []
            else:
                for bet in match["bets"]:
                    bet["user"] = {"name": user_id_to_username_map[bet["user_id"]]}
                # Sort match bets alphabetically by username
                match["bets"].sort(key=lambda x: x["user"]["name"])
            todays_matches.append(match)
        else:
            match["bets"] = []
            future_matches.append(match)
    # Sort matches by start time
    todays_matches.sort(key=lambda x: x["timestamp"])
    future_matches.sort(key=lambda x: x["timestamp"])
    # For todays matches, show ongoing matches first, then scheduled matches, finally finished matches
    todays_scheduled_matches = [
        match for match in todays_matches if match["status"] in scheduled_match_statuses
    ]
    todays_ongoing_matches = [
        match for match in todays_matches if match["status"] in ongoing_match_statuses
    ]
    todays_finished_matches = [
        match for match in todays_matches if match["status"] in finished_match_statuses
    ]
    todays_finished_matches.sort(key=lambda x: x["updated_at"])
    todays_matches = (
        todays_ongoing_matches + todays_scheduled_matches + todays_finished_matches
    )
    return {
        "today": todays_matches,
        "tomorrow": future_matches,
    }


@functools.lru_cache(maxsize=1)
def get_current_standings() -> list[dict]:
    matches_and_bets = (
        matches_table.select("*, bets(*)")
        .eq("show", True)
        .order("timestamp")
        .execute()
        .data
    )
    SHOW_LAST_N_FINISHED_MATCHES = 5
    last_n_finished_matches = [
        match
        for match in sorted(matches_and_bets, key=lambda x: x["updated_at"])
        if match["status"] in finished_match_statuses
    ][-SHOW_LAST_N_FINISHED_MATCHES:]
    ongoing_matches = [
        match["id"]
        for match in matches_and_bets
        if match["status"] in ongoing_match_statuses
    ]
    users = app.auth.list_users()
    standings = {
        user.id: {
            "name": user.user_metadata["username"],
            "points": 0,
            "potential_points": 0,
            "points_in_last_n_finished_matches": [None] * SHOW_LAST_N_FINISHED_MATCHES,
            "num_wildcards_remaining": config.getint("default", "max_number_wildcards"),
        }
        for user in users
    }
    for match in matches_and_bets:
        match_status = match["status"]
        if match_status in scheduled_match_statuses:
            continue
        bets = match["bets"]
        if not bets:
            continue
        match_score = {
            "home_team_goals": match["home_team_goals"],
            "away_team_goals": match["away_team_goals"],
        }
        match_id = match["id"]
        for bet in bets:
            user_id = bet["user_id"]
            has_used_wildcard = bet["use_wildcard"]
            if has_used_wildcard:
                standings[user_id]["num_wildcards_remaining"] -= 1
            match_points = calculate_points_for_bet(bet, match_score)
            if match_status in finished_match_statuses:
                standings[user_id]["points"] += match_points * (
                    2 if has_used_wildcard else 1
                )
            if match_id in ongoing_matches:
                standings[user_id]["potential_points"] += match_points * (
                    2 if has_used_wildcard else 1
                )
            if match in last_n_finished_matches:
                index = last_n_finished_matches.index(match)
                standings[user_id]["points_in_last_n_finished_matches"][index] = (
                    match_points * (2 if has_used_wildcard else 1)
                )
    standings = [
        {
            "user_id": user_id,
            "name": standings[user_id]["name"],
            "points": standings[user_id]["points"],
            "potential_points": standings[user_id]["potential_points"],
            "points_in_last_n_finished_matches": standings[user_id][
                "points_in_last_n_finished_matches"
            ],
            "num_wildcards_remaining": standings[user_id]["num_wildcards_remaining"],
        }
        for user_id in standings
    ]
    # Sort the standings by points and then alphabetically by name
    standings.sort(key=lambda x: x["name"])
    standings.sort(
        key=lambda x: x["points"]
        + (x["potential_points"] if x["potential_points"] else 0),
        reverse=True,
    )
    # Rank the standings, take care of ties, for example, if two users have rank 1, the next should be 2
    current_rank = 1
    for i, user in enumerate(standings):
        if i == 0:
            user["rank"] = current_rank
        else:
            previous_user = standings[i - 1]
            if (
                user["points"]
                + (user["potential_points"] if user["potential_points"] else 0)
            ) == (
                previous_user["points"]
                + (
                    previous_user["potential_points"]
                    if previous_user["potential_points"]
                    else 0
                )
            ):
                user["rank"] = previous_user["rank"]
            else:
                current_rank += 1
                user["rank"] = current_rank
    return standings


@functools.lru_cache(maxsize=20)
def get_user_bets(user_id: int) -> tuple[list[dict], int]:
    max_user_wildcards = config.getint("default", "max_number_wildcards")
    user_bets = bets_table.select("*").eq("user_id", user_id).execute()
    user_wildcards_used = len([bet for bet in user_bets.data if bet["use_wildcard"]])
    num_wildcards_remaining = max_user_wildcards - user_wildcards_used
    return user_bets.data, num_wildcards_remaining


def create_user_match_prediction(
    user_id: str,
    match_id: str,
    predicted_home_goals: int,
    predicted_away_goals: int,
    use_wildcard: bool = False,
) -> dict:
    match_data = matches_table.select("*").eq("id", match_id).execute().data[0]
    if not match_data["can_users_place_bets"]:
        raise ValueError("User cannot place a bet on this fixture")
    if (
        datetime.datetime.now(datetime.UTC).timestamp()
        >= datetime.datetime.fromisoformat(match_data["timestamp"]).timestamp()
    ):
        match_data["can_users_place_bets"] = False
        matches_table.upsert([match_data]).execute()
        get_matches_handler.cache_clear()
        raise ValueError(
            "Match has started - you can no longer place bets on this match"
        )
    existing_user_prediction = (
        bets_table.select("*")
        .eq("user_id", user_id)
        .eq("match_id", match_id)
        .execute()
        .data
    )
    max_num_wildcards = config.getint("default", "max_number_wildcards")
    user_bets_with_wildcards = (
        bets_table.select("*")
        .eq("user_id", user_id)
        .eq("use_wildcard", True)
        .execute()
        .data
    )
    if not existing_user_prediction:
        # If the user has not made a prediction for this match, we will create a new prediction
        # First check if the user has used all their wildcards, if they have, we will not allow them to use a wildcard
        num_remaining_wildcards = max_num_wildcards - len(user_bets_with_wildcards)
        if use_wildcard and num_remaining_wildcards == 0:
            raise ValueError("You have used all your point boosters")
        # Otherwise, we will create a new prediction
        bet_data = {
            "use_wildcard": use_wildcard,
            "user_id": user_id,
            "match_id": match_id,
            "predicted_home_goals": predicted_home_goals,
            "predicted_away_goals": predicted_away_goals,
            "updated_at": datetime.datetime.now(datetime.UTC).isoformat(),
        }
        bet_creation_response = bets_table.upsert(bet_data).execute()
        get_user_bets.cache_clear()
        return bet_creation_response.data[0]
    # No need to update the prediction if the user has already made the same prediction
    scores_are_same = (
        existing_user_prediction[0]["predicted_home_goals"] == predicted_home_goals
        and existing_user_prediction[0]["predicted_away_goals"] == predicted_away_goals
    )
    if scores_are_same:
        if existing_user_prediction[0]["use_wildcard"] == use_wildcard:
            return existing_user_prediction[0]
        # If the user has changed their mind about using a wildcard, we will update the prediction
        # Check if the user has used all their wildcards, if they have, we will not allow them to use a wildcard
        num_remaining_wildcards = max_num_wildcards - len(user_bets_with_wildcards)
        if use_wildcard and num_remaining_wildcards == 0:
            raise ValueError("You have used all your point boosters")
        bet_data = {
            "use_wildcard": use_wildcard,
            "updated_at": datetime.datetime.now(datetime.UTC).isoformat(),
        }
        updated_bet = (
            bets_table.update(bet_data)
            .eq("id", existing_user_prediction[0]["id"])
            .execute()
            .data[0]
        )
        get_user_bets.cache_clear()
        return updated_bet
    # Handle case where the scores are different, and the user may have changed their mind about using a wildcard
    is_match_one_of_wildcard_matches = match_id in [
        bet["match_id"] for bet in user_bets_with_wildcards
    ]
    num_remaining_wildcards = max_num_wildcards - len(user_bets_with_wildcards)
    if is_match_one_of_wildcard_matches:
        num_remaining_wildcards += 1
    if use_wildcard and num_remaining_wildcards == 0:
        raise ValueError("You have used all your point boosters")
    bet_data = {
        "use_wildcard": use_wildcard,
        "predicted_home_goals": predicted_home_goals,
        "predicted_away_goals": predicted_away_goals,
        "updated_at": datetime.datetime.now(datetime.UTC).isoformat(),
    }
    updated_bet = (
        bets_table.update(bet_data)
        .eq("id", existing_user_prediction[0]["id"])
        .execute()
        .data[0]
    )
    get_user_bets.cache_clear()
    return updated_bet


def update_user_name(user_id: str, new_username: str) -> dict:
    user = supabase_client.auth.admin.update_user_by_id(
        uid=user_id, attributes={"user_metadata": {"username": new_username}}
    )
    return user


def convert_json_to_excel(data: dict) -> io.BytesIO:
    matches = []
    bets = []
    for match_and_bet in data:
        match_bets = match_and_bet["bets"]
        bets.extend(match_bets)
        # Match data is everything except the bets
        match_data = copy.deepcopy(match_and_bet)
        del match_data["bets"]
        matches.append(match_data)
    matches_df = pandas.DataFrame(matches)
    bets_df = pandas.DataFrame(bets)
    output = io.BytesIO()
    with pandas.ExcelWriter(output, engine="openpyxl") as writer:
        matches_df.to_excel(writer, sheet_name="matches", index=False)
        bets_df.to_excel(writer, sheet_name="bets", index=False)
    output.seek(0)
    return output


def download_historical_data(is_excel: bool = False) -> dict | io.BytesIO:
    historical_matches_and_bets = (
        matches_table.select("*, bets(*)")
        .eq("show", True)
        .eq("can_users_place_bets", False)
        .order("timestamp")
        .execute()
    )
    users = app.auth.list_users()
    user_id_to_username_map = {
        user.id: user.user_metadata["username"] for user in users
    }
    for match in historical_matches_and_bets.data:
        for bet in match["bets"]:
            bet["username"] = user_id_to_username_map[bet["user_id"]]
    if is_excel:
        return convert_json_to_excel(historical_matches_and_bets.data)
    return historical_matches_and_bets.data


if config.getboolean("scheduler", "enabled"):
    configure_scheduler(
        update_interval_minutes=config.getint("scheduler", "update_interval_minutes")
    )
