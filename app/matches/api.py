import requests

import datetime
import logging
import os

import app.matches.common


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
        can_user_place_bet = (
            fixture_status in app.matches.common.scheduled_match_statuses
        )
        if fixture_status in app.matches.common.special_match_statuses:
            if fixture["score"]["fulltime"]["home"] is None:
                # Special status and match has either not started or is in regular time
                home_team_goals = fixture["goals"]["home"]
                away_team_goals = fixture["goals"]["away"]
            else:
                home_team_goals = fixture["score"]["fulltime"]["home"]
                away_team_goals = fixture["score"]["fulltime"]["away"]
        elif fixture_status in (
            app.matches.common.extra_time_match_statuses
            + app.matches.common.finished_in_extra_time_match_statuses
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
                "league_name": fixture["league"]["name"],
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
