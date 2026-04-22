"""
auth.py
Authentication helpers for the Malawi Health Access dashboard.

Set AUTH_ENABLED=true in your environment to require login.
When AUTH_ENABLED is false (default) any username/password passes through,
which is useful for internal deployments behind a VPN or SSO proxy.
"""

import bcrypt
import os
from flask_login import login_user, UserMixin

AUTH_ENABLED = os.getenv("AUTH_ENABLED", "False").lower() in ("true", "1", "yes")


class User(UserMixin):
    def __init__(self, username: str):
        self.id = username


def authenticate(username: str, password: str) -> bool:
    """
    Validate credentials and log the user in via flask-login.

    When AUTH_ENABLED is False, any non-empty username passes immediately.
    When AUTH_ENABLED is True, the password is checked against the bcrypt
    hash stored in the Databricks user-credentials table.
    """
    if not AUTH_ENABLED:
        login_user(User(username))
        return True

    # Lazy import to avoid circular dependency at module load time
    from queries import QueryService
    credential_store = QueryService.get_instance().get_user_credentials()

    salted_password = credential_store.get(username)
    if not salted_password:
        return False

    if bcrypt.checkpw(password.encode("utf-8"), salted_password.encode("utf-8")):
        login_user(User(username))
        return True

    return False