from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from sqlalchemy import or_

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-super-secret-key-change-this-later'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# --- DATABASE STRUCTURE STAGE ---

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)
    stories = db.relationship('Story', backref='author', lazy=True)
    votes = db.relationship('VoteRecord', backref='user', lazy=True)
    
    messages_sent = db.relationship('Message', foreign_keys='Message.sender_id', backref='sender', lazy=True)
    messages_received = db.relationship('Message', foreign_keys='Message.receiver_id', backref='receiver', lazy=True)

class Story(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    content = db.Column(db.Text, nullable=False)
    date_posted = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    likes = db.Column(db.Integer, default=0)
    dislikes = db.Column(db.Integer, default=0)
    votes = db.relationship('VoteRecord', backref='story', cascade="all, delete-orphan", lazy=True)

class VoteRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    story_id = db.Column(db.Integer, db.ForeignKey('story.id'), nullable=False)
    vote_type = db.Column(db.String(10), nullable=False)

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    body = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    is_read = db.Column(db.Boolean, default=False)

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

@app.context_processor
def inject_notification_badge():
    if current_user.is_authenticated:
        unread_count = Message.query.filter_by(receiver_id=current_user.id, is_read=False).count()
        return dict(unread_messages_count=unread_count)
    return dict(unread_messages_count=0)

# --- WEBPAGE ROUTING LOGIC ---

# 1. NEW: Static Front Landing Page
@app.route('/')
def home():
    return render_template('home.html')

# 2. UPDATED: Dedicated Public Stories Feed
@app.route('/stories')
def index():
    all_stories = Story.query.order_by(Story.likes.desc(), Story.date_posted.desc()).all()
    return render_template('index.html', stories=all_stories)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        form_username = request.form.get('username')
        form_password = request.form.get('password')
        existing_user = User.query.filter_by(username=form_username).first()
        if existing_user:
            return "Username already exists! Try another one."
        new_user = User(username=form_username, password=form_password)
        db.session.add(new_user)
        db.session.commit()
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        form_username = request.form.get('username')
        form_password = request.form.get('password')
        user = User.query.filter_by(username=form_username).first()
        if user and user.password == form_password:
            login_user(user)
            return redirect(url_for('home'))
        else:
            return "Invalid login details! Try again."
    return render_template('login.html')

@app.route('/create', methods=['GET', 'POST'])
@login_required
def create_story():
    if request.method == 'POST':
        story_title = request.form.get('title')
        story_content = request.form.get('content')
        new_story = Story(title=story_title, content=story_content, author=current_user)
        db.session.add(new_story)
        db.session.commit()
        return redirect(url_for('index'))
    return render_template('create_story.html')

@app.route('/like/<int:story_id>', methods=['POST'])
@login_required
def like_story(story_id):
    story = Story.query.get_or_404(story_id)
    existing_vote = VoteRecord.query.filter_by(user_id=current_user.id, story_id=story_id).first()
    if existing_vote:
        if existing_vote.vote_type == 'like':
            db.session.delete(existing_vote)
            story.likes = max(0, story.likes - 1)
        else:
            existing_vote.vote_type = 'like'
            story.likes += 1
            story.dislikes = max(0, story.dislikes - 1)
    else:
        vote = VoteRecord(user_id=current_user.id, story_id=story_id, vote_type='like')
        story.likes += 1
        db.session.add(vote)
    db.session.commit()
    return redirect(url_for('index'))

@app.route('/dislike/<int:story_id>', methods=['POST'])
@login_required
def dislike_story(story_id):
    story = Story.query.get_or_404(story_id)
    existing_vote = VoteRecord.query.filter_by(user_id=current_user.id, story_id=story_id).first()
    if existing_vote:
        if existing_vote.vote_type == 'dislike':
            db.session.delete(existing_vote)
            story.dislikes = max(0, story.dislikes - 1)
        else:
            existing_vote.vote_type = 'dislike'
            story.dislikes += 1
            story.likes = max(0, story.likes - 1)
    else:
        vote = VoteRecord(user_id=current_user.id, story_id=story_id, vote_type='dislike')
        story.dislikes += 1
        db.session.add(vote)
    db.session.commit()
    return redirect(url_for('index'))

@app.route('/send_message/<int:receiver_id>', methods=['GET', 'POST'])
@login_required
def send_message(receiver_id):
    receiver_user = db.session.get(User, receiver_id)
    if not receiver_user:
        return "User not found!", 404
    if receiver_id == current_user.id:
        return "You cannot send a message to yourself!", 400

    if request.method == 'POST':
        message_body = request.form.get('body')
        new_msg = Message(sender_id=current_user.id, receiver_id=receiver_id, body=message_body)
        db.session.add(new_msg)
        db.session.commit()
        return redirect(url_for('inbox', chat_user_id=receiver_id))
    return render_template('send_message.html', receiver=receiver_user)

@app.route('/inbox')
@app.route('/inbox/<int:chat_user_id>')
@login_required
def inbox(chat_user_id=None):
    all_messages = Message.query.filter(or_(Message.sender_id == current_user.id, Message.receiver_id == current_user.id)).all()
    chat_partners_ids = set()
    for msg in all_messages:
        if msg.sender_id != current_user.id: chat_partners_ids.add(msg.sender_id)
        if msg.receiver_id != current_user.id: chat_partners_ids.add(msg.receiver_id)
    active_chat_users = User.query.filter(User.id.in_(chat_partners_ids)).all()
    
    if not chat_user_id and active_chat_users:
        chat_user_id = active_chat_users[0].id
        
    conversation_history = []
    selected_partner = None
    
    if chat_user_id:
        selected_partner = db.session.get(User, chat_user_id)
        conversation_history = Message.query.filter(
            or_(
                ((Message.sender_id == current_user.id) & (Message.receiver_id == chat_user_id)),
                ((Message.sender_id == chat_user_id) & (Message.receiver_id == current_user.id))
            )
        ).order_by(Message.timestamp.asc()).all()
        
        for msg in conversation_history:
            if msg.receiver_id == current_user.id:
                msg.is_read = True
        db.session.commit()

    return render_template('inbox.html', chat_users=active_chat_users, conversation=conversation_history, partner=selected_partner)

@app.route('/delete/<int:story_id>', methods=['POST'])
@login_required
def delete_story(story_id):
    story_to_delete = Story.query.get_or_404(story_id)
    if story_to_delete.author != current_user and current_user.username != 'admin':
        return "You do not have permission to delete this story!", 403
    db.session.delete(story_to_delete)
    db.session.commit()
    return redirect(url_for('index'))

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('home'))



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
