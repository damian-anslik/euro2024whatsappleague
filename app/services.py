import pycountry
import requests
import supabase
from apscheduler.schedulers.background import BackgroundScheduler

import configparser
import functools
import datetime
import logging
import os

config = configparser.ConfigParser()
config.read("config.ini")
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


def get_flag_url(country_name: str) -> str:
    if "W" in country_name:
        country_name = country_name.replace("W", "")
    country_name = country_name.strip()
    try:
        country = pycountry.countries.search_fuzzy(country_name)
        country_code = country[0].alpha_2
        return f"https://flagsapi.com/{country_code}/flat/64.png"
    except LookupError:
        return None


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
    for fixture in response_data:
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
        # if is_international:
        #     home_team_logo = get_flag_url(fixture["teams"]["home"]["name"])
        #     if home_team_logo is None:
        #         home_team_logo = fixture["teams"]["home"]["logo"]
        #     away_team_logo = get_flag_url(fixture["teams"]["away"]["name"])
        #     if away_team_logo is None:
        #         away_team_logo = fixture["teams"]["away"]["logo"]
        # else:
        #     home_team_logo = fixture["teams"]["home"]["logo"]
        #     away_team_logo = fixture["teams"]["away"]["logo"]
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
                "updated_at": datetime.datetime.now(datetime.UTC).isoformat(),
                "show": False,
            }
        )
    return parsed_fixtures


def scheduled_update_function(date: datetime.datetime):
    leagues = leagues_table.select("*").execute().data
    leagues = [league for league in leagues if league["update_matches"]]
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
    scheduler.add_job(
        func=lambda: scheduled_update_function(
            datetime.datetime.now(datetime.UTC).today() + datetime.timedelta(days=2),
        ),
        trigger="cron",
        minute=f"*/{update_interval_minutes+2}",
    )
    scheduler.start()


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
        .eq("league_id", league_id)
        .eq("season", season)
        .gt("timestamp", start_of_day.isoformat())
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
        updated_data.append(match)
    logging.info(f"Updated data for league_id={league_id}: {updated_data}")
    matches_table.upsert(updated_data).execute()


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


def list_users():
    return supabase_client.auth.admin.list_users()
