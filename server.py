"""
server.py
Flask server with flask-login authentication support.

Required environment variables:
    SECRET_KEY   — Flask session secret (any random string, keep private)

Optional environment variables:
    AUTH_ENABLED — Set to "true" to enforce login (default: "False")
"""

import os
from flask import Flask
from flask_login import LoginManager
from auth import User

server = Flask(__name__)
server.secret_key = os.getenv("SECRET_KEY", "malawi-health-access-dev-key")

login_manager = LoginManager()
login_manager.login_view = "/login"
login_manager.init_app(server)


@login_manager.user_loader
def load_user(user_id: str) -> User:
    return User(user_id)