import supabase

import configparser
import datetime
import datetime
import os

import app.services

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


def get_matches_for_given_date(
    date: datetime.datetime,
) -> list[dict]:
    # TODO We can just do one call for two days, and the filter data locally, instead of two calls
    response_data = (
        matches_table.select("*")
        .gte(
            "timestamp",
            datetime.datetime(
                date.year, date.month, date.day, 0, 0, 0, tzinfo=datetime.UTC
            ).isoformat(),
        )
        .lt(
            "timestamp",
            datetime.datetime(
                date.year, date.month, date.day, 23, 59, 59, tzinfo=datetime.UTC
            ).isoformat(),
        )
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
        users = supabase_client.auth.admin.list_users()
        users_data = {user.id: user.user_metadata["username"] for user in users}
        user_bets = (
            bets_table.select("*")
            .in_("match_id", ongoing_or_finished_matches)
            .execute()
            .data
        )
        for bet in user_bets:
            user_id = bet["user_id"]
            bet["user"] = {"name": users_data[user_id]}
        # Add the bets on the ongoing matches to the response data
        for match in response_data:
            match_bets = [bet for bet in user_bets if bet["match_id"] == match["id"]]
            match_bets.sort(key=lambda x: x["user"]["name"])
            match["bets"] = match_bets
    return response_data


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
        for match in matches_and_bets
        if match["status"] in finished_match_statuses
    ][-SHOW_LAST_N_FINISHED_MATCHES:]
    ongoing_matches = [
        match["id"]
        for match in matches_and_bets
        if match["status"] in ongoing_match_statuses
    ]
    users = app.services.list_users()
    standings = {
        user.id: {
            "name": user.user_metadata["username"],
            "points": 0,
            "potential_points": 0,
            "points_in_last_n_finished_matches": [None] * SHOW_LAST_N_FINISHED_MATCHES,
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
            match_points = app.services.calculate_points_for_bet(bet, match_score)
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
    # Check if there is less than 5 minutes left for the match to start
    if (
        datetime.datetime.now(datetime.UTC).timestamp()
        - datetime.datetime.fromisoformat(match_data["timestamp"]).timestamp()
        > 5 * 60
    ):
        match_data["can_users_place_bets"] = False
        matches_table.upsert([match_data]).execute()
        raise ValueError(
            "Match has started - you can no longer place bets on this match"
        )
    bet_data = {
        "use_wildcard": use_wildcard,
        "user_id": user_id,
        "match_id": match_id,
        "predicted_home_goals": predicted_home_goals,
        "predicted_away_goals": predicted_away_goals,
        "updated_at": datetime.datetime.now(datetime.UTC).isoformat(),
    }
    user_already_made_prediction_for_match = (
        bets_table.select("*")
        .eq("user_id", user_id)
        .eq("match_id", match_id)
        .execute()
        .data
    )
    max_user_wildcards = config.getint("default", "max_number_wildcards")
    user_used_wildcards = (
        bets_table.select("*")
        .eq("user_id", user_id)
        .eq("use_wildcard", True)
        .execute()
        .data
    )
    if len(user_used_wildcards) >= max_user_wildcards and use_wildcard:
        raise ValueError("You have already used all your point boosters")
    if user_already_made_prediction_for_match:
        predicted_scores_are_the_same = (
            user_already_made_prediction_for_match[0]["predicted_home_goals"]
            == predicted_home_goals
            and user_already_made_prediction_for_match[0]["predicted_away_goals"]
            == predicted_away_goals
            and user_already_made_prediction_for_match[0]["use_wildcard"]
            == use_wildcard
        )
        if predicted_scores_are_the_same:
            return user_already_made_prediction_for_match[0]
        bet_data.update({"id": user_already_made_prediction_for_match[0]["id"]})
    bet_creation_response = bets_table.upsert(bet_data).execute()
    return bet_creation_response.data[0]


def get_user_bets(user_id: int) -> tuple[list[dict], int]:
    max_user_wildcards = config.getint("default", "max_number_wildcards")
    user_bets = bets_table.select("*").eq("user_id", user_id).execute()
    user_wildcards_used = len([bet for bet in user_bets.data if bet["use_wildcard"]])
    num_wildcards_remaining = max_user_wildcards - user_wildcards_used
    return user_bets.data, num_wildcards_remaining


if config.getboolean("scheduler", "enabled"):
    app.services.configure_scheduler(
        update_interval_minutes=config.getint("scheduler", "update_interval_minutes")
    )
