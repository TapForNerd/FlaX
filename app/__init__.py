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
