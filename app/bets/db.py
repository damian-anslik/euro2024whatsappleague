import supabase

import os

supabase_client = supabase.create_client(
    supabase_key=os.getenv("SUPABASE_KEY"),
    supabase_url=os.getenv("SUPABASE_URL"),
)


def get_users() -> list[dict]:
    request = supabase_client.table("sessions").select("*")
    response = request.execute()
    users = response.data
    return users


def get_bets() -> list[dict]:
    request = supabase_client.table("bets").select("*")
    response = request.execute()
    bets = response.data
    return bets


def get_user_bets(user_id: int) -> list[dict]:
    request = supabase_client.table("bets").select("*").eq("user_id", user_id)
    response = request.execute()
    user_bets = response.data
    return user_bets


def get_match_bets(match_ids: list[int]) -> list[dict]:
    request = (
        supabase_client.table("bets")
        .select("*, user:sessions(name)")
        .in_("match_id", match_ids)
    )
    response = request.execute()
    match_bets = response.data
    return match_bets


def check_user_has_made_bet(user_id: int, match_id: int) -> bool:
    request = (
        supabase_client.table("bets")
        .select("*")
        .eq("user_id", user_id)
        .eq("match_id", match_id)
    )
    response = request.execute()
    user_bets = response.data
    return bool(user_bets)


def create_bet(bet_data: dict) -> dict:
    request = supabase_client.table("bets").upsert(bet_data)
    response = request.execute()
    bet_creation_response = response.data[0]
    return bet_creation_response
