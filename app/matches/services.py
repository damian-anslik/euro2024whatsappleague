from apscheduler.schedulers.background import BackgroundScheduler

import datetime
import logging

import app.matches.common
import app.matches.api
import app.matches.db


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
    start_time = datetime.datetime(
        date.year, date.month, date.day, 0, 0, 0, tzinfo=datetime.UTC
    )
    end_time = datetime.datetime(
        date.year, date.month, date.day, 23, 59, 59, tzinfo=datetime.UTC
    )
    matches_in_db = app.matches.db.get_matches(league_id, season, start_time, end_time)
    if not matches_in_db:
        # Check if we have already checked for matches for the day, if not we will fetch the matches from the API
        already_checked_for_matches = app.matches.db.get_match_checks(
            league_id,
            season,
            date,
        )
        if already_checked_for_matches and not force_update:
            logging.info(
                f"No matches in DB for league_id={league_id} and date={date.date().strftime('%Y-%m-%d')}; already checked for matches today"
            )
            return
        logging.info(
            f"No matches found in the DB for league_id={league_id} and date={date.date().strftime('%Y-%m-%d')}; fetching from the API for first time"
        )
        todays_matches = app.matches.api.get_matches_from_api(league_id, season, date)
        for match in todays_matches:
            match["show"] = show_by_default
        app.matches.db.upsert_matches(todays_matches)
        app.matches.db.insert_match_check(league_id, season, date)
        return
    # Only update matches that are shown and are ongoing
    shown_matches = [match for match in matches_in_db if match["show"]]
    ongoing_matches = []
    for match in shown_matches:
        if not (
            datetime.datetime.now(datetime.UTC).timestamp()
            > datetime.datetime.fromisoformat(match["timestamp"]).timestamp()
            and match["status"] not in app.matches.common.finished_match_statuses
        ):
            continue
        ongoing_matches.append(match["id"])
    if not ongoing_matches:
        logging.info(f"No ongoing matches found for league_id={league_id}")
        return
    logging.info(f"Ongoing matches: {ongoing_matches}; updating fixtures")
    updated_matches = app.matches.api.get_matches_from_api(league_id, season, date)
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
    app.matches.db.upsert_matches(updated_data)


def scheduled_update_function(date: datetime.datetime):
    leagues = app.matches.db.get_leagues()
    for league in leagues:
        try:
            update_match_data(
                str(league["id"]), league["season"], date, league["show_by_default"]
            )
        except Exception as e:
            logging.error(f"Error updating data for league {league['id']}: {e}")


def get_matches(
    date: datetime.datetime = None,
) -> dict[str, list[dict]]:
    if date:
        start_time = datetime.datetime(
            date.year, date.month, date.day, 0, 0, 0, tzinfo=datetime.UTC
        )
        end_time = datetime.datetime(
            date.year, date.month, date.day, 23, 59, 59, tzinfo=datetime.UTC
        )
        response_data = app.matches.db.get_matches(
            start_time=start_time,
            end_time=end_time,
        )
    else:
        response_data = app.matches.db.get_matches()
    response_data = sorted(
        response_data,
        key=lambda x: x["status"] not in app.matches.common.finished_match_statuses,
        reverse=True,
    )
    finished_matches = [
        match
        for match in response_data
        if match["status"] in app.matches.common.finished_match_statuses
    ]
    finished_matches.sort(key=lambda match: match["timestamp"])
    ongoing_matches = [
        match
        for match in response_data
        if match["status"] in app.matches.common.ongoing_match_statuses
    ]
    scheduled_matches = [
        match
        for match in response_data
        if match["status"] in app.matches.common.scheduled_match_statuses
    ]
    response = {
        "finished": finished_matches,
        "ongoing": ongoing_matches,
        "scheduled": scheduled_matches,
    }
    return response


def get_match_details(match_id: int) -> dict:
    match = app.matches.db.get_match(match_id)
    return match


def configure_scheduler(update_frequency_mins: int = 5, num_days_to_update: int = 3):
    scheduler = BackgroundScheduler()
    for i in range(num_days_to_update):
        scheduler.add_job(
            func=lambda: scheduled_update_function(
                datetime.datetime.now(datetime.UTC).today()
                + datetime.timedelta(days=i),
            ),
            trigger="cron",
            minute=f"*/{update_frequency_mins+i}",  # Distribute requests to be in different minutes - max 30 requests per minute
        )
    scheduler.start()
