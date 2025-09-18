import gotrue.errors
import supabase

import functools
import os

import app.handlers

supabase_client = supabase.create_client(
    supabase_key=os.getenv("SUPABASE_KEY"),
    supabase_url=os.getenv("SUPABASE_URL"),
)


@functools.lru_cache(maxsize=1)
def list_users():
    users_in_db = supabase_client.auth.admin.list_users()
    return users_in_db


def check_user_session(access_token: str) -> str:
    if "." in access_token:
        decoded_token = supabase_client.auth._decode_jwt(access_token)
        user_id = decoded_token["sub"]
    else:
        # If user is attempting to recover their password
        decoded_token = supabase_client.auth.verify_otp(
            {
                "token_hash": access_token,
                "type": "recovery",
            }
        )
        user_id = decoded_token.user.id
    return user_id


def signup(email: str, username: str, password: str) -> str:
    try:
        # Check username is available
        is_username_taken = any(
            [
                user.user_metadata["username"] == username
                for user in supabase_client.auth.admin.list_users()
            ]
        )
        if is_username_taken:
            raise ValueError("Username is already taken")
        supabase_client.auth.sign_up(
            {
                "email": email,
                "password": password,
                "options": {"data": {"username": username}},
            }
        )
        list_users.cache_clear()
        app.handlers.calculate_current_standings.cache_clear()
        app.handlers.get_matches_handler.cache_clear()
    except gotrue.errors.AuthApiError as e:
        raise ValueError(e)


def login(email: str, password: str) -> str:
    try:
        login_response = supabase_client.auth.sign_in_with_password(
            {"email": email, "password": password}
        )
        access_token = login_response.session.access_token
        return access_token
    except gotrue.errors.AuthApiError as e:
        raise ValueError(e)


def send_password_reset_request(email: str):
    supabase_client.auth.reset_password_email(
        email=email,
        options={
            "redirect_to": "https://euro2024whatsappleague.up.railway.app/change-password"
        },
    )


def change_password(user_id: str, password: str):
    change_password_response = supabase_client.auth.admin.update_user_by_id(
        uid=user_id, attributes={"password": password}
    )
    print(change_password_response.model_dump())


def update_username(user_id: str, new_username: str):
    # Check username is available
    is_username_taken = any(
        [
            user.user_metadata["username"] == new_username
            for user in supabase_client.auth.admin.list_users()
        ]
    )
    if is_username_taken:
        raise ValueError("Username is already taken")
    supabase_client.auth.admin.update_user_by_id(
        uid=user_id, attributes={"user_metadata": {"username": new_username}}
    )
    list_users.cache_clear()
    app.handlers.calculate_current_standings.cache_clear()
    app.handlers.get_matches_handler.cache_clear()
