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
            home_team_goals = fixture["score"]["fulltime"]["home"]
            away_team_goals = fixture["score"]["fulltime"]["away"]
        else:
            home_team_goals = fixture["goals"]["home"]
            away_team_goals = fixture["goals"]["away"]
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
                "home_team_goals": home_team_goals,
                "away_team_goals": away_team_goals,
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
    response_data = sorted(
        response_data,
        key=lambda x: x["status"] not in finished_match_statuses,
        reverse=True,
    )
    ongoing_or_finished_matches = [
        match["id"] for match in response_data if not match["can_users_place_bets"]
    ]
    if ongoing_or_finished_matches:
        # Get the list of bets for the ongoing matches
        bets = (
            supabase_client.table("bets")
            .select("*, user:sessions(name)")
            .in_("match_id", ongoing_or_finished_matches)
            .execute()
            .data
        )
        # Add the bets on the ongoing matches to the response data)
        for match in response_data:
            match_bets = [bet for bet in bets if bet["match_id"] == match["id"]]
            match_bets.sort(key=lambda x: x["user"]["name"])
            match["bets"] = match_bets
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
    league_id: str,
    season: str,
    date: datetime.datetime,
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
        supabase_client.table("matches")
        .select("*")
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
            supabase_client.table("match_checks")
            .select("*")
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
        todays_matches = get_matches_from_api(league_id, season, date)
        for match in todays_matches:
            match["show"] = show_by_default
        supabase_client.table("matches").upsert(todays_matches).execute()
        # Log that we checked for matches today
        supabase_client.table("match_checks").insert(
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
    updated_matches = get_matches_from_api(league_id, season, date)
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
    matches = (
        supabase_client.table("matches")
        .select("*")
        .eq("show", True)
        .order("timestamp")
        .execute()
        .data
    )
    SHOW_LAST_N_FINISHED_MATCHES = 5
    last_n_finished_matches = [
        match for match in matches if match["status"] in finished_match_statuses
    ][-SHOW_LAST_N_FINISHED_MATCHES:]
    ongoing_matches = [
        match["id"] for match in matches if match["status"] in ongoing_match_statuses
    ]
    users = supabase_client.table("sessions").select("*").execute().data
    bets = supabase_client.table("bets").select("*").execute().data
    bets = [
        bet for bet in bets if bet["match_id"] in [match["id"] for match in matches]
    ]
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
        points_in_last_n_finished_matches = []
        for match in last_n_finished_matches:
            bet = next(
                (bet for bet in user_bets if bet["match_id"] == match["id"]), None
            )
            if bet:
                points_in_last_n_finished_matches.append(
                    calculate_points_for_bet(bet, match)
                )
            else:
                points_in_last_n_finished_matches.append(None)
        standings.append(
            {
                "user_id": user["id"],
                "name": user["name"],
                "points": user_points,
                "potential_points": (
                    potential_points if len(ongoing_matches) != 0 else None
                ),
                "points_in_last_n_finished_matches": points_in_last_n_finished_matches,
            }
        )
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
    # Check if there is less than 5 minutes left for the match to start
    if (
        datetime.datetime.now(datetime.UTC).timestamp()
        - datetime.datetime.fromisoformat(match_data["timestamp"]).timestamp()
        > 5 * 60
    ):
        match_data["can_users_place_bets"] = False
        supabase_client.table("matches").upsert([match_data]).execute()
        raise ValueError(
            "Match about to start - user cannot place a bet on this fixture"
        )
    bet_data = {
        "user_id": user_id,
        "match_id": match_id,
        "predicted_home_goals": predicted_home_goals,
        "predicted_away_goals": predicted_away_goals,
        "updated_at": datetime.datetime.now(datetime.UTC).isoformat(),
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
        predicted_scores_are_the_same = (
            user_already_made_prediction_for_match[0]["predicted_home_goals"]
            == predicted_home_goals
            and user_already_made_prediction_for_match[0]["predicted_away_goals"]
            == predicted_away_goals
        )
        if predicted_scores_are_the_same:
            return user_already_made_prediction_for_match[0]
        bet_data.update({"id": user_already_made_prediction_for_match[0]["id"]})
    bet_creation_response = supabase_client.table("bets").upsert(bet_data).execute()
    return bet_creation_response.data[0]


def get_user_bets(user_id: int) -> list[dict]:
    user_bets = (
        supabase_client.table("bets").select("*").eq("user_id", user_id).execute()
    )
    return user_bets.data


def scheduled_update_function(date: datetime.datetime):
    leagues = supabase_client.table("leagues").select("*").execute().data
    for league in leagues:
        try:
            update_match_data(
                str(league["id"]), league["season"], date, league["show_by_default"]
            )
        except Exception as e:
            logging.error(f"Error updating data for league {league['id']}: {e}")


def get_currently_tracked_leagues() -> list[dict]:
    leagues = supabase_client.table("leagues").select("*").execute().data
    return leagues


def update_tracked_leagues(
    league_id: int, season: str, league_name: str, show: bool
) -> dict:
    league_data = {
        "id": league_id,
        "name": league_name,
        "season": season,
        "show_by_default": show,
    }
    response = supabase_client.table("leagues").upsert(league_data).execute()
    return response.data[0]
