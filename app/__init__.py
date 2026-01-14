import os

from flask import Flask, g, session

from app.config import Config
from app.extensions import db, migrate
from app.models import User
from app.utils.encrypt_decrypt import load_env_vars_to_db
from app.blueprints.auth.routes import bp as auth_bp
from app.blueprints.home.routes import bp as home_bp
from app.blueprints.items.routes import bp as items_bp
from app.blueprints.x_api.routes import bp as x_api_bp


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    _ensure_sqlite_path(app)

    db.init_app(app)
    migrate.init_app(app, db)

    with app.app_context():
        load_env_vars_to_db()

    @app.before_request
    def load_user():
        user_id = session.get("user_id")
        g.user = User.query.get(user_id) if user_id else None

    @app.context_processor
    def inject_user():
        return {"user": g.get("user")}

    app.register_blueprint(auth_bp)
    app.register_blueprint(home_bp)
    app.register_blueprint(items_bp)
    app.register_blueprint(x_api_bp)
    app.add_url_rule("/callback", endpoint="callback_root", view_func=app.view_functions["auth.callback"])
    app.add_url_rule("/x/callback", endpoint="callback_x", view_func=app.view_functions["auth.callback"])
    app.add_url_rule(
        "/x/service-account-callback",
        endpoint="callback_x_service",
        view_func=app.view_functions["auth.callback"],
    )

    return app


def _ensure_sqlite_path(app: Flask) -> None:
    db_url = app.config.get("SQLALCHEMY_DATABASE_URI") or ""
    if not db_url.startswith("sqlite:///") or db_url.startswith("sqlite:////"):
        return
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    rel_path = db_url.replace("sqlite:///", "", 1)
    abs_path = os.path.abspath(os.path.join(base_dir, rel_path))
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{abs_path.replace(os.sep, '/')}"
