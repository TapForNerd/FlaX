from flask import Blueprint, flash, redirect, render_template, request, url_for

from app.extensions import db
from app.models import Item
from app.services.crud import CrudService

bp = Blueprint("items", __name__, url_prefix="/items")
crud = CrudService(Item, db.session)


@bp.route("/")
def index():
    items = crud.list_all()
    return render_template("items/index.html", items=items)


@bp.route("/create", methods=["GET", "POST"])
def create():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        body = request.form.get("body", "").strip()
        if not title or not body:
            flash("Title and body are required.", "danger")
            return render_template("items/form.html", item=None)
        crud.create(title=title, body=body)
        flash("Item created.", "success")
        return redirect(url_for("items.index"))

    return render_template("items/form.html", item=None)


@bp.route("/<int:item_id>/edit", methods=["GET", "POST"])
def edit(item_id):
    item = crud.get(item_id)
    if not item:
        flash("Item not found.", "danger")
        return redirect(url_for("items.index"))

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        body = request.form.get("body", "").strip()
        if not title or not body:
            flash("Title and body are required.", "danger")
            return render_template("items/form.html", item=item)
        crud.update(item, title=title, body=body)
        flash("Item updated.", "success")
        return redirect(url_for("items.index"))

    return render_template("items/form.html", item=item)


@bp.route("/<int:item_id>/delete", methods=["POST"])
def delete(item_id):
    item = crud.get(item_id)
    if not item:
        flash("Item not found.", "danger")
        return redirect(url_for("items.index"))

    crud.delete(item)
    flash("Item deleted.", "success")
    return redirect(url_for("items.index"))
