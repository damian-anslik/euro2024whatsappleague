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


def signup(email: str, username: str, password: str):
    # 1. Local formatting validation
    if "@" not in email or "." not in email:
        raise ValueError("Invalid email address")
    cleaned_username = username.strip()
    if not cleaned_username:
        raise ValueError("Username cannot be empty")
    # 2. Fast-fail local uniqueness check
    for user in list_users():
        if user.email == email:
            raise ValueError("Email is already taken")
        existing_username = user.user_metadata.get("username", "").strip()
        if existing_username == cleaned_username:
            raise ValueError("Username is already taken")
    # 3. Network call
    try:
        supabase_public_client.auth.sign_up(
            {
                "email": email,
                "password": password,
                "options": {"data": {"username": cleaned_username}},
            }
        )
        # Invalidate caches to reflect the new user system-wide
        list_users.cache_clear()
        app.handlers.calculate_current_standings.cache_clear()
        app.handlers.get_matches_handler.cache_clear() 
    except gotrue.errors.AuthApiError as e:
        raise ValueError(f"Signup failed: {e}") from e


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
    cleaned_new_username = new_username.strip()
    if not cleaned_new_username:
        raise ValueError("Username cannot be empty")
    # Fast-fail local check
    for user in list_users():
        existing_username = user.user_metadata.get("username", "").strip()
        if existing_username == cleaned_new_username:
            if user.id == user_id:
                raise ValueError("New username is the same as current username")
            raise ValueError("Username is already taken")
    # Proceed with network call
    supabase_admin_client.auth.admin.update_user_by_id(
        uid=user_id, attributes={"user_metadata": {"username": cleaned_new_username}}
    )
    list_users.cache_clear()
    app.handlers.calculate_current_standings.cache_clear()
    app.handlers.get_matches_handler.cache_clear()


def update_email(user_id: str, new_email: str):
    cleaned_new_email = new_email.strip()
    if "@" not in cleaned_new_email or "." not in cleaned_new_email:
        raise ValueError("Invalid email address")
    # Fast-fail local check
    for user in list_users():
        if user.email and user.email.strip() == cleaned_new_email:
            if user.id == user_id:
                raise ValueError("New email is the same as current email")
            raise ValueError("Email is already taken")
    # Proceed with network call
    supabase_admin_client.auth.admin.update_user_by_id(
        uid=user_id, attributes={"email": cleaned_new_email}
    )
    list_users.cache_clear()