import os
from datetime import datetime

from flask import Flask, render_template, request, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager,
    UserMixin,
    login_user,
    login_required,
    logout_user,
    current_user
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix
from sqlalchemy import or_


# ============================================================
# APPLICATION SETUP
# ============================================================

app = Flask(__name__)

# ------------------------------------------------------------
# SECRET KEY
# ------------------------------------------------------------
# For production, set SECRET_KEY in Render Environment Variables.
# A development fallback is provided so the app can still run
# locally without additional configuration.
# ------------------------------------------------------------

app.config["SECRET_KEY"] = os.environ.get(
    "SECRET_KEY",
    "development-secret-key-change-this"
)


# ------------------------------------------------------------
# DATABASE
# ------------------------------------------------------------
# Locally:
#     SQLite database.db
#
# On Render:
#     DATABASE_URL will contain the PostgreSQL connection URL.
# ------------------------------------------------------------

database_url = os.environ.get("DATABASE_URL")

if database_url:
    # Some hosting services may provide postgres://
    # SQLAlchemy expects postgresql:// or postgresql+psycopg2://
    if database_url.startswith("postgres://"):
        database_url = database_url.replace(
            "postgres://",
            "postgresql+psycopg2://",
            1
        )
    elif database_url.startswith("postgresql://"):
        database_url = database_url.replace(
            "postgresql://",
            "postgresql+psycopg2://",
            1
        )

    app.config["SQLALCHEMY_DATABASE_URI"] = database_url

else:
    # Local development database
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///database.db"


app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False


# ------------------------------------------------------------
# SECURITY / SESSION SETTINGS
# ------------------------------------------------------------

# Render + Cloudflare will normally use HTTPS.
# Locally, keep this disabled unless FLASK_ENV is production.
is_production = os.environ.get("FLASK_ENV") == "production"

app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = is_production


# ------------------------------------------------------------
# CLOUDFLARE / RENDER PROXY SUPPORT
# ------------------------------------------------------------

# Allows Flask to correctly understand HTTPS requests when
# sitting behind Render / Cloudflare reverse proxies.
app.wsgi_app = ProxyFix(
    app.wsgi_app,
    x_for=1,
    x_proto=1,
    x_host=1,
    x_port=1
)


# ============================================================
# DATABASE SETUP
# ============================================================

db = SQLAlchemy(app)

login_manager = LoginManager(app)
login_manager.login_view = "login"


# ============================================================
# DATABASE MODELS
# ============================================================

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)

    username = db.Column(
        db.String(50),
        unique=True,
        nullable=False
    )

    password = db.Column(
        db.String(255),
        nullable=False
    )

    stories = db.relationship(
        "Story",
        backref="author",
        lazy=True
    )

    votes = db.relationship(
        "VoteRecord",
        backref="user",
        lazy=True
    )

    messages_sent = db.relationship(
        "Message",
        foreign_keys="Message.sender_id",
        backref="sender",
        lazy=True
    )

    messages_received = db.relationship(
        "Message",
        foreign_keys="Message.receiver_id",
        backref="receiver",
        lazy=True
    )


class Story(db.Model):
    id = db.Column(
        db.Integer,
        primary_key=True
    )

    title = db.Column(
        db.String(100),
        nullable=False
    )

    content = db.Column(
        db.Text,
        nullable=False
    )

    date_posted = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.utcnow
    )

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False
    )

    likes = db.Column(
        db.Integer,
        default=0
    )

    dislikes = db.Column(
        db.Integer,
        default=0
    )

    votes = db.relationship(
        "VoteRecord",
        backref="story",
        cascade="all, delete-orphan",
        lazy=True
    )


class VoteRecord(db.Model):
    id = db.Column(
        db.Integer,
        primary_key=True
    )

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False
    )

    story_id = db.Column(
        db.Integer,
        db.ForeignKey("story.id"),
        nullable=False
    )

    vote_type = db.Column(
        db.String(10),
        nullable=False
    )


class Message(db.Model):
    id = db.Column(
        db.Integer,
        primary_key=True
    )

    sender_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False
    )

    receiver_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id"),
        nullable=False
    )

    body = db.Column(
        db.Text,
        nullable=False
    )

    timestamp = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    is_read = db.Column(
        db.Boolean,
        default=False
    )


# ============================================================
# LOGIN MANAGER
# ============================================================

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# ============================================================
# GLOBAL TEMPLATE CONTEXT
# ============================================================

@app.context_processor
def inject_notification_badge():

    if current_user.is_authenticated:

        unread_count = Message.query.filter_by(
            receiver_id=current_user.id,
            is_read=False
        ).count()

        return {
            "unread_messages_count": unread_count
        }

    return {
        "unread_messages_count": 0
    }


# ============================================================
# HOME / STORIES
# ============================================================

@app.route("/")
def home():
    return render_template("home.html")


@app.route("/stories")
def index():

    all_stories = Story.query.order_by(
        Story.likes.desc(),
        Story.date_posted.desc()
    ).all()

    return render_template(
        "index.html",
        stories=all_stories
    )


# ============================================================
# REGISTRATION
# ============================================================

@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        form_username = request.form.get(
            "username",
            ""
        ).strip()

        form_password = request.form.get(
            "password",
            ""
        )

        # Basic validation
        if not form_username or not form_password:
            return "Username and password are required!", 400

        if len(form_username) > 50:
            return "Username is too long!", 400

        if len(form_password) < 6:
            return "Password must be at least 6 characters!", 400

        existing_user = User.query.filter_by(
            username=form_username
        ).first()

        if existing_user:
            return "Username already exists! Try another one."

        # ----------------------------------------------------
        # PASSWORD HASHING
        # ----------------------------------------------------
        # Never store the actual password in the database.
        # ----------------------------------------------------

        hashed_password = generate_password_hash(
            form_password
        )

        new_user = User(
            username=form_username,
            password=hashed_password
        )

        db.session.add(new_user)
        db.session.commit()

        return redirect(url_for("login"))

    return render_template("register.html")


# ============================================================
# LOGIN
# ============================================================

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        form_username = request.form.get(
            "username",
            ""
        ).strip()

        form_password = request.form.get(
            "password",
            ""
        )

        user = User.query.filter_by(
            username=form_username
        ).first()

        if user:

            password_is_valid = False

            # ------------------------------------------------
            # NEW HASHED PASSWORD
            # ------------------------------------------------
            try:
                password_is_valid = check_password_hash(
                    user.password,
                    form_password
                )

            except (ValueError, TypeError):
                password_is_valid = False

            # ------------------------------------------------
            # LEGACY PLAINTEXT PASSWORD SUPPORT
            # ------------------------------------------------
            # If you already have users in your old local
            # database, their passwords were stored as plain
            # text.
            #
            # If the old password matches, automatically
            # convert it to a secure hash.
            # ------------------------------------------------

            if not password_is_valid and user.password == form_password:

                password_is_valid = True

                user.password = generate_password_hash(
                    form_password
                )

                db.session.commit()

            if password_is_valid:

                login_user(user)

                return redirect(url_for("home"))

        return "Invalid login details! Try again."

    return render_template("login.html")


# ============================================================
# CREATE STORY
# ============================================================

@app.route("/create", methods=["GET", "POST"])
@login_required
def create_story():

    if request.method == "POST":

        story_title = request.form.get(
            "title",
            ""
        ).strip()

        story_content = request.form.get(
            "content",
            ""
        ).strip()

        if not story_title or not story_content:
            return "Title and content are required!", 400

        new_story = Story(
            title=story_title,
            content=story_content,
            author=current_user
        )

        db.session.add(new_story)
        db.session.commit()

        return redirect(url_for("index"))

    return render_template("create_story.html")


# ============================================================
# LIKE STORY
# ============================================================

@app.route("/like/<int:story_id>", methods=["POST"])
@login_required
def like_story(story_id):

    story = Story.query.get_or_404(story_id)

    existing_vote = VoteRecord.query.filter_by(
        user_id=current_user.id,
        story_id=story_id
    ).first()

    if existing_vote:

        if existing_vote.vote_type == "like":

            db.session.delete(existing_vote)

            story.likes = max(
                0,
                story.likes - 1
            )

        else:

            existing_vote.vote_type = "like"

            story.likes += 1

            story.dislikes = max(
                0,
                story.dislikes - 1
            )

    else:

        vote = VoteRecord(
            user_id=current_user.id,
            story_id=story_id,
            vote_type="like"
        )

        story.likes += 1

        db.session.add(vote)

    db.session.commit()

    return redirect(url_for("index"))


# ============================================================
# DISLIKE STORY
# ============================================================

@app.route("/dislike/<int:story_id>", methods=["POST"])
@login_required
def dislike_story(story_id):

    story = Story.query.get_or_404(story_id)

    existing_vote = VoteRecord.query.filter_by(
        user_id=current_user.id,
        story_id=story_id
    ).first()

    if existing_vote:

        if existing_vote.vote_type == "dislike":

            db.session.delete(existing_vote)

            story.dislikes = max(
                0,
                story.dislikes - 1
            )

        else:

            existing_vote.vote_type = "dislike"

            story.dislikes += 1

            story.likes = max(
                0,
                story.likes - 1
            )

    else:

        vote = VoteRecord(
            user_id=current_user.id,
            story_id=story_id,
            vote_type="dislike"
        )

        story.dislikes += 1

        db.session.add(vote)

    db.session.commit()

    return redirect(url_for("index"))


# ============================================================
# SEND MESSAGE
# ============================================================

@app.route(
    "/send_message/<int:receiver_id>",
    methods=["GET", "POST"]
)
@login_required
def send_message(receiver_id):

    receiver_user = db.session.get(
        User,
        receiver_id
    )

    if not receiver_user:
        return "User not found!", 404

    if receiver_id == current_user.id:
        return "You cannot send a message to yourself!", 400

    if request.method == "POST":

        message_body = request.form.get(
            "body",
            ""
        ).strip()

        if not message_body:
            return "Message cannot be empty!", 400

        new_msg = Message(
            sender_id=current_user.id,
            receiver_id=receiver_id,
            body=message_body
        )

        db.session.add(new_msg)
        db.session.commit()

        return redirect(
            url_for(
                "inbox",
                chat_user_id=receiver_id
            )
        )

    return render_template(
        "send_message.html",
        receiver=receiver_user
    )


# ============================================================
# INBOX / MESSAGES
# ============================================================

@app.route("/inbox")
@app.route("/inbox/<int:chat_user_id>")
@login_required
def inbox(chat_user_id=None):

    all_messages = Message.query.filter(
        or_(
            Message.sender_id == current_user.id,
            Message.receiver_id == current_user.id
        )
    ).all()

    chat_partners_ids = set()

    for msg in all_messages:

        if msg.sender_id != current_user.id:
            chat_partners_ids.add(msg.sender_id)

        if msg.receiver_id != current_user.id:
            chat_partners_ids.add(msg.receiver_id)

    active_chat_users = User.query.filter(
        User.id.in_(chat_partners_ids)
    ).all()

    if not chat_user_id and active_chat_users:
        chat_user_id = active_chat_users[0].id

    conversation_history = []
    selected_partner = None

    if chat_user_id:

        selected_partner = db.session.get(
            User,
            chat_user_id
        )

        if selected_partner:

            conversation_history = Message.query.filter(
                or_(
                    (
                        (Message.sender_id == current_user.id) &
                        (Message.receiver_id == chat_user_id)
                    ),
                    (
                        (Message.sender_id == chat_user_id) &
                        (Message.receiver_id == current_user.id)
                    )
                )
            ).order_by(
                Message.timestamp.asc()
            ).all()

            for msg in conversation_history:

                if msg.receiver_id == current_user.id:
                    msg.is_read = True

            db.session.commit()

    return render_template(
        "inbox.html",
        chat_users=active_chat_users,
        conversation=conversation_history,
        partner=selected_partner
    )


# ============================================================
# DELETE STORY
# ============================================================

@app.route("/delete/<int:story_id>", methods=["POST"])
@login_required
def delete_story(story_id):

    story_to_delete = Story.query.get_or_404(
        story_id
    )

    if (
        story_to_delete.author != current_user
        and current_user.username != "admin"
    ):
        return "You do not have permission to delete this story!", 403

    db.session.delete(story_to_delete)
    db.session.commit()

    return redirect(url_for("index"))


# ============================================================
# LOGOUT
# ============================================================

@app.route("/logout")
@login_required
def logout():

    logout_user()

    return redirect(url_for("home"))


# ============================================================
# ABOUT
# ============================================================

@app.route("/about")
def about():

    return render_template("about.html")


# ============================================================
# DATABASE INITIALIZATION
# ============================================================

def initialize_database():

    with app.app_context():
        db.create_all()


# ============================================================
# LOCAL DEVELOPMENT
# ============================================================

if __name__ == "__main__":

    initialize_database()

    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=True
    )
else:
    # When running through Gunicorn, initialize the database
    # when the application is loaded.
    initialize_database()