import supabase
import gotrue.errors

import os


# class AuthClient:
#     def __init__(self):
#         self.supabase_client = supabase.create_client(
#             supabase_key=os.getenv("SUPABASE_KEY"),
#             supabase_url=os.getenv("SUPABASE_URL"),
#         )

#     def signup(self, email: str, username: str, password: str) -> str:
#         try:
#             signup_response = self.supabase_client.auth.sign_up(
#                 {
#                     "email": email,
#                     "password": password,
#                     "options": {"data": {"username": username}},
#                 }
#             )
#             access_token = signup_response.session.access_token
#             return access_token
#         except gotrue.errors.AuthApiError as e:
#             raise ValueError(e)

#     def login(self, email: str, password: str) -> str:
#         try:
#             login_response = self.supabase_client.auth.sign_in_with_password(
#                 {"email": email, "password": password}
#             )
#             access_token = login_response.session.access_token
#             return access_token
#         except gotrue.errors.AuthApiError as e:
#             raise ValueError(e)

#     def check_user_session(self, access_token: str) -> str:
#         decoded_token = self.supabase_client.auth._decode_jwt(access_token)
#         user_id = decoded_token["sub"]
#         return user_id


supabase_client = supabase.create_client(
    supabase_key=os.getenv("SUPABASE_KEY"),
    supabase_url=os.getenv("SUPABASE_URL"),
)


def signup(email: str, username: str, password: str) -> str:
    try:
        signup_response = supabase_client.auth.sign_up(
            {
                "email": email,
                "password": password,
                "options": {"data": {"username": username}},
            }
        )
        access_token = signup_response.session.access_token
        return access_token
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


def check_user_session(access_token: str) -> str:
    decoded_token = supabase_client.auth._decode_jwt(access_token)
    user_id = decoded_token["sub"]
    return user_id


def send_password_reset_request(email: str):
    supabase_client.auth.reset_password_email(
        email=email, options={"redirect_to": "http://localhost:8000/change-password"}
    )


def change_password(user_id: str, password: str):
    change_password_response = supabase_client.auth.admin.update_user_by_id(
        uid=user_id, attributes={"password": password}
    )
    print(change_password_response.model_dump())
