import os
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv not needed on Render (env vars set directly)

from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import cloudinary
import cloudinary.uploader

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-in-production")

# ── Database config ──────────────────────────────────────────────────────────
# Locally uses SQLite; on Render it will use the DATABASE_URL env variable.
DATABASE_URL = os.environ.get("DATABASE_URL") or "sqlite:///stickynote.db"
# Render gives a postgres:// URL; SQLAlchemy needs postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# ── Cloudinary config ─────────────────────────────────────────────────────────
cloudinary.config(
    cloud_name=os.environ.get("CLOUDINARY_CLOUD_NAME"),
    api_key=os.environ.get("CLOUDINARY_API_KEY"),
    api_secret=os.environ.get("CLOUDINARY_API_SECRET"),
)

# ── Models ────────────────────────────────────────────────────────────────────
pin_tags = db.Table(
    "pin_tags",
    db.Column("pin_id", db.Integer, db.ForeignKey("pin.id"), primary_key=True),
    db.Column("tag_id", db.Integer, db.ForeignKey("tag.id"), primary_key=True),
)


class Pin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.Text, nullable=False)
    url = db.Column(db.Text)
    image_url = db.Column(db.Text)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    tags = db.relationship("Tag", secondary=pin_tags, backref="pins", lazy="subquery")


class Tag(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.Text, unique=True, nullable=False)


# ── Helpers ───────────────────────────────────────────────────────────────────
def get_or_create_tags(tag_string):
    """Parse comma-separated tag string and return Tag objects."""
    tags = []
    for name in [t.strip().lower() for t in tag_string.split(",") if t.strip()]:
        tag = Tag.query.filter_by(name=name).first()
        if not tag:
            tag = Tag(name=name)
            db.session.add(tag)
        tags.append(tag)
    return tags


# ── Routes ────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    tag_filter = request.args.get("tag")
    search = request.args.get("q", "").strip()

    query = Pin.query

    if tag_filter:
        query = query.filter(Pin.tags.any(Tag.name == tag_filter))

    if search:
        like = f"%{search}%"
        query = query.filter(
            db.or_(Pin.title.ilike(like), Pin.notes.ilike(like), Pin.url.ilike(like))
        )

    pins = query.order_by(Pin.created_at.desc()).all()
    all_tags = Tag.query.order_by(Tag.name).all()
    return render_template("index.html", pins=pins, all_tags=all_tags,
                           tag_filter=tag_filter, search=search)


@app.route("/pin/new", methods=["GET", "POST"])
def new_pin():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        if not title:
            flash("Title is required.", "error")
            return redirect(url_for("new_pin"))

        image_url = None

        # Handle image upload to Cloudinary
        image_file = request.files.get("image_file")
        if image_file and image_file.filename:
            result = cloudinary.uploader.upload(image_file)
            image_url = result.get("secure_url")

        # Fall back to pasted URL if no file uploaded
        if not image_url:
            image_url = request.form.get("image_url", "").strip() or None

        pin = Pin(
            title=title,
            url=request.form.get("url", "").strip() or None,
            image_url=image_url,
            notes=request.form.get("notes", "").strip() or None,
        )

        tag_string = request.form.get("tags", "")
        pin.tags = get_or_create_tags(tag_string)

        db.session.add(pin)
        db.session.commit()
        flash("Pin saved!", "success")
        return redirect(url_for("index"))

    return render_template("pin_form.html", pin=None, action="new")


@app.route("/pin/<int:pin_id>")
def view_pin(pin_id):
    pin = Pin.query.get_or_404(pin_id)
    return render_template("pin_detail.html", pin=pin)


@app.route("/pin/<int:pin_id>/edit", methods=["GET", "POST"])
def edit_pin(pin_id):
    pin = Pin.query.get_or_404(pin_id)

    if request.method == "POST":
        pin.title = request.form.get("title", "").strip()
        if not pin.title:
            flash("Title is required.", "error")
            return redirect(url_for("edit_pin", pin_id=pin_id))

        pin.url = request.form.get("url", "").strip() or None
        pin.notes = request.form.get("notes", "").strip() or None

        image_file = request.files.get("image_file")
        if image_file and image_file.filename:
            result = cloudinary.uploader.upload(image_file)
            pin.image_url = result.get("secure_url")
        elif request.form.get("image_url", "").strip():
            pin.image_url = request.form.get("image_url").strip()

        tag_string = request.form.get("tags", "")
        pin.tags = get_or_create_tags(tag_string)

        db.session.commit()
        flash("Pin updated!", "success")
        return redirect(url_for("view_pin", pin_id=pin.id))

    return render_template("pin_form.html", pin=pin, action="edit")


@app.route("/pin/<int:pin_id>/delete", methods=["POST"])
def delete_pin(pin_id):
    pin = Pin.query.get_or_404(pin_id)
    db.session.delete(pin)
    db.session.commit()
    flash("Pin deleted.", "success")
    return redirect(url_for("index"))


# ── Init DB & run ─────────────────────────────────────────────────────────────
with app.app_context():
    db.create_all()

if __name__ == "__main__":
    app.run(debug=True)
