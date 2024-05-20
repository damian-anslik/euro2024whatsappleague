import supabase

import datetime
import os

supabase_client = supabase.create_client(
    supabase_key=os.getenv("SUPABASE_KEY"),
    supabase_url=os.getenv("SUPABASE_URL"),
)


def get_leagues() -> list[dict]:
    response = supabase_client.table("leagues").select("*").execute()
    return response.data


def get_matches(
    league_id: str = None,
    season: str = None,
    start_time: datetime.datetime = None,
    end_time: datetime.datetime = None,
) -> list[dict]:
    request = supabase_client.table("matches").select("*")
    if league_id:
        request = request.eq("league_id", league_id)
    if season:
        request = request.eq("season", season)
    if start_time:
        request = request.gt("timestamp", start_time.isoformat())
    if end_time:
        request = request.lt("timestamp", end_time.isoformat())
    response = request.execute()
    return response.data


def get_match(match_id: str) -> dict:
    request = supabase_client.table("matches").select("*").eq("id", match_id)
    response = request.execute()
    return response.data[0]


def upsert_matches(matches: list[dict]) -> None:
    request = supabase_client.table("matches")
    request = request.upsert(matches)
    response = request.execute()


def get_match_checks(
    league_id: str, season: str, date: datetime.datetime
) -> list[dict]:
    request = supabase_client.table("match_checks").select("*")
    request = request.eq("league_id", league_id)
    request = request.eq("season", season)
    request = request.eq("date", date.strftime("%Y-%m-%d"))
    response = request.execute()
    return response.data


def insert_match_check(league_id: str, season: str, date: datetime.datetime) -> None:
    request = supabase_client.table("match_checks")
    request = request.insert(
        {
            "league_id": league_id,
            "season": season,
            "date": date.strftime("%Y-%m-%d"),
        }
    )
    response = request.execute()
