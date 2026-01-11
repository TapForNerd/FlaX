import click
from flask.cli import AppGroup

from app.blueprints.x_api.helpers import (
    get_my_x_user,
    get_x_user_by_id,
    get_x_user_by_username,
    get_x_users_by_ids,
    get_x_users_by_usernames,
)

# Create a command group for X API tasks
x_api_cli = AppGroup('x-api', help='X API management commands.')

@x_api_cli.command('get-user-by-username')
@click.argument('username')
def get_user_cmd(username):
    """Fetch and print X user details by username."""
    click.echo(f"Fetching X user: {username}...")
    get_x_user_by_username(username)


@x_api_cli.command('get-users-by-usernames')
@click.argument('usernames')
def get_users_cmd(usernames):
    """Fetch and print multiple X users by comma-separated usernames."""
    cleaned = [name.strip() for name in usernames.split(",") if name.strip()]
    click.echo(f"Fetching {len(cleaned)} X users...")
    get_x_users_by_usernames(cleaned)


@x_api_cli.command('get-user-by-id')
@click.argument('user_id')
def get_user_by_id_cmd(user_id):
    """Fetch and print X user details by id."""
    click.echo(f"Fetching X user id: {user_id}...")
    get_x_user_by_id(user_id)


@x_api_cli.command('get-users-by-ids')
@click.argument('user_ids')
def get_users_by_ids_cmd(user_ids):
    """Fetch and print multiple X users by comma-separated ids."""
    cleaned = [item.strip() for item in user_ids.split(",") if item.strip()]
    click.echo(f"Fetching {len(cleaned)} X users...")
    get_x_users_by_ids(cleaned)


@x_api_cli.command('get-my-user')
def get_my_user_cmd():
    """Fetch and print the authenticated X user."""
    click.echo("Fetching authenticated X user...")
    get_my_x_user()
