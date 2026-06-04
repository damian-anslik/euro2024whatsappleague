import gotrue.errors
import supabase

import functools
import jwt
import os

import app.handlers


if not os.getenv("SUPABASE_ADMIN_KEY") or not os.getenv("SUPABASE_URL"):
    raise ValueError("SUPABASE_ADMIN_KEY and SUPABASE_URL must be set in environment variables")
supabase_admin_client = supabase.create_client(
    supabase_key=os.getenv("SUPABASE_ADMIN_KEY"),
    supabase_url=os.getenv("SUPABASE_URL"),
)
if not os.getenv("SUPABASE_ANON_KEY") or not os.getenv("SUPABASE_URL"):
    raise ValueError("SUPABASE_ANON_KEY and SUPABASE_URL must be set in environment variables")
supabase_public_client = supabase.create_client(
    supabase_key=os.getenv("SUPABASE_ANON_KEY"),
    supabase_url=os.getenv("SUPABASE_URL"),
)


@functools.lru_cache(maxsize=1)
def list_users():
    return supabase_admin_client.auth.admin.list_users()


def check_user_session(access_token: str) -> str:
    if "." in access_token:
        # Decodes and verifies the cryptographic signature locally
        jwt_secret = os.environ.get("SUPABASE_JWT_SECRET")
        decoded_token = jwt.decode(
            access_token,
            key=jwt_secret, 
            algorithms=["HS256"],
            options={"verify_aud": False} 
        )
        user_id = decoded_token["sub"]
    else:
        # If user is attempting to recover their password
        response = supabase_public_client.auth.verify_otp(
            {
                "token_hash": access_token,
                "type": "recovery",
            }
        )
        user_id = response.user.id
    return user_id


def signup(email: str, username: str, password: str) -> str:
    try:
        # Check username is available
        users = list_users()
        is_username_taken = any(
            [
                user.user_metadata["username"] == username
                for user in users
            ]
        )
        if is_username_taken:
            raise ValueError("Username is already taken")
        supabase_public_client.auth.sign_up(
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
        login_response = supabase_public_client.auth.sign_in_with_password(
            {"email": email, "password": password}
        )
        access_token = login_response.session.access_token
        return access_token
    except gotrue.errors.AuthApiError as e:
        raise ValueError(e)


def send_password_reset_request(email: str):
    supabase_public_client.auth.reset_password_email(
        email=email
    )


def change_password(user_id: str, password: str):
    change_password_response = supabase_admin_client.auth.admin.update_user_by_id(
        uid=user_id, attributes={"password": password}
    )
    print(change_password_response.model_dump())


def update_username(user_id: str, new_username: str):
    # Check username is available
    users = list_users()
    for user in users:
        if user.id == user_id:
            current_username = user.user_metadata.get("username", None)
            break
    if not current_username:
        raise ValueError("User not found")
    if new_username == current_username:
        raise ValueError("New username is the same as current username")
    is_username_taken = any(
        [
            user.user_metadata["username"] == new_username
            for user in users
        ]
    )
    if is_username_taken:
        raise ValueError("Username is already taken")
    supabase_admin_client.auth.admin.update_user_by_id(
        uid=user_id, attributes={"user_metadata": {"username": new_username}}
    )
    list_users.cache_clear()
    app.handlers.calculate_current_standings.cache_clear()
    app.handlers.get_matches_handler.cache_clear()


def update_email(user_id: str, new_email: str):
    # Check email is available
    users = list_users()
    for user in users:
        if user.id == user_id:
            current_email = user.email
            break
    if not current_email:
        raise ValueError("User not found")
    if new_email == current_email:
        raise ValueError("New email is the same as current email")
    is_email_taken = any(
        [
            user.email == new_email
            for user in users
        ]
    )
    if is_email_taken:
        raise ValueError("Email is already taken")
    supabase_admin_client.auth.admin.update_user_by_id(
        uid=user_id, attributes={"email": new_email}
    )
    list_users.cache_clear()