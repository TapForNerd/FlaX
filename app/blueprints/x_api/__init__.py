from flask import Blueprint

x_api_bp = Blueprint('x_api', __name__)

from app.blueprints.x_api import routes, commands

# Register the click commands group with the blueprint
x_api_bp.cli.add_command(commands.x_api_cli)