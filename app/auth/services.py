import os

import supabase


supabase_client = supabase.create_client(
    supabase_key=os.getenv("SUPABASE_KEY"),
    supabase_url=os.getenv("SUPABASE_URL"),
)


def create_user_session(name: str) -> str:
    session_id = (
        supabase_client.table("sessions").insert({"name": name}).execute().data[0]["id"]
    )
    return session_id


def get_user_session(name: str) -> str:
    if ":" in name:
        username = name.split(":")[0]
        id = name.split(":")[1]
        existing_session = (
            supabase_client.table("sessions")
            .select("*")
            .eq("id", id)
            .eq("name", username)
            .execute()
            .data
        )
        if existing_session:
            return id
        else:
            new_session_id = create_user_session(username)
            return new_session_id
    else:
        new_session_id = create_user_session(name)
        return new_session_id


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
