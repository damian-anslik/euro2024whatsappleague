import os

import supabase


supabase_client = supabase.create_client(
    supabase_key=os.getenv("SUPABASE_KEY"),
    supabase_url=os.getenv("SUPABASE_URL"),
)


def create_user_session(name: str) -> str:
    response_data = (
        supabase_client.table("sessions").insert({"name": name}).execute().data
    )
    session_id = response_data[0]["id"]
    return session_id


def check_user_session(session_id: str) -> bool:
    session = (
        supabase_client.table("sessions")
        .select("*")
        .eq("id", session_id)
        .execute()
        .data
    )
    if not session:
        return False
    return True
