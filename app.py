from fastapi import Depends, FastAPI, HTTPException, Query, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, ForeignKey, Text, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship, joinedload, subqueryload, selectinload
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
import json
from dateutil import parser as date_parser
from fastapi.middleware.cors import CORSMiddleware
import firebase_admin
from firebase_admin import credentials, messaging
import pytz
import os
from pathlib import Path

# Set IST timezone
IST = pytz.timezone('Asia/Kolkata')

# Prepare uploads directory (safe before app creation)
Path("uploads/voice").mkdir(parents=True, exist_ok=True)

DATABASE_URL = "sqlite:///./poll_play.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

# Models

class UserDB(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True)
    name = Column(String)
    email = Column(String, unique=True)
    password = Column(String)
    avatar = Column(String)
    isAdmin = Column(Boolean, default=False)
    coins = Column(Integer, default=0)
    dailyAttempts = Column(Integer, default=3)
    lastAttemptDate = Column(DateTime)
    isBanned = Column(Boolean, default=False)
    lastSeen = Column(DateTime, nullable=True)
    mobile = Column(String, nullable=True)
    gender = Column(String, nullable=True)
    bio = Column(Text, nullable=True)
    specializations = Column(Text, nullable=True)
    referralCode = Column(String, unique=True, nullable=True)
    referredBy = Column(String, nullable=True)

class CategoryDB(Base):
    __tablename__ = "categories"
    id = Column(String, primary_key=True)
    name = Column(String)

class PollDB(Base):
    __tablename__ = "polls"
    id = Column(String, primary_key=True)
    title = Column(String)
    description = Column(Text)
    category = Column(String)
    thumbnail = Column(String)
    createdAt = Column(DateTime)
    disableVoiceComments = Column(Boolean, default=False)
    options = relationship("PollOptionDB", back_populates="poll")
    comments = relationship("CommentDB", back_populates="poll")

class PollOptionDB(Base):
    __tablename__ = "poll_options"
    id = Column(String, primary_key=True)
    poll_id = Column(String, ForeignKey('polls.id'))
    text = Column(String)
    imageUrl = Column(String)
    votes = Column(Integer, default=0)
    votedBy = Column(Text, default="[]")
    poll = relationship("PollDB", back_populates="options")

class CommentDB(Base):
    __tablename__ = "comments"
    id = Column(String, primary_key=True)
    poll_id = Column(String, ForeignKey('polls.id'))
    user_id = Column(String, ForeignKey('users.id'))
    text = Column(Text)
    audio_url = Column(String, nullable=True)
    timestamp = Column(DateTime)
    likes = Column(Integer, default=0)
    likedBy = Column(Text, default="[]")
    parent_id = Column(String, ForeignKey('comments.id'), nullable=True)
    flaggedForReview = Column(Boolean, default=False)
    reviewReason = Column(String, nullable=True)
    poll = relationship("PollDB", back_populates="comments")
    user = relationship("UserDB")
    replies = relationship("CommentDB")

class ReportDB(Base):
    __tablename__ = "reports"
    id = Column(String, primary_key=True)
    pollId = Column(String)
    comment_id = Column(String, ForeignKey('comments.id'))
    reportedBy_id = Column(String, ForeignKey('users.id'))
    timestamp = Column(DateTime)
    status = Column(String, default="pending")
    reason = Column(Text, nullable=True)
    comment = relationship("CommentDB")
    reportedBy = relationship("UserDB")

class NotificationDB(Base):
    __tablename__ = "notifications"
    id = Column(String, primary_key=True)
    iconName = Column(String)
    text = Column(String)
    time = Column(String)
    read = Column(Boolean, default=False)

class RedemptionRequestDB(Base):
    __tablename__ = "redemption_requests"
    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey('users.id'))
    amount = Column(Integer)
    paymentDetails = Column(String)
    status = Column(String, default="pending")
    requestedAt = Column(DateTime)
    updatedAt = Column(DateTime, nullable=True)
    adminNotes = Column(Text, nullable=True)
    user = relationship("UserDB")

class GameResultDB(Base):
    __tablename__ = "game_results"
    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey('users.id'))
    targetTime = Column(Float)
    actualTime = Column(Float)
    accuracy = Column(Float)
    coinsWon = Column(Integer)
    playedAt = Column(DateTime)
    user = relationship("UserDB")

class DeviceTokenDB(Base):
    __tablename__ = "device_tokens"
    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey('users.id'))
    token = Column(String, unique=True)
    platform = Column(String)  # ios or android
    createdAt = Column(DateTime, default=lambda: datetime.now(IST))
    user = relationship("UserDB")

class SettingsDB(Base):
    __tablename__ = "settings"
    key = Column(String, primary_key=True)
    value = Column(String)

class AdsStatsDB(Base):
    __tablename__ = "ads_stats"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey('users.id'))
    date = Column(String)  # YYYY-MM-DD (IST)
    watched = Column(Integer, default=0)
    coins = Column(Integer, default=0)
    user = relationship("UserDB")

# Chat/E2E models
class UserPublicKeyDB(Base):
    __tablename__ = "user_public_keys"
    user_id = Column(String, ForeignKey('users.id'), primary_key=True)
    public_jwk = Column(Text)
    updatedAt = Column(DateTime)

class MessageDB(Base):
    __tablename__ = "messages"
    id = Column(String, primary_key=True)
    sender_id = Column(String, ForeignKey('users.id'))
    recipient_id = Column(String, ForeignKey('users.id'))
    ciphertext = Column(Text)
    iv = Column(String)
    createdAt = Column(DateTime)
    delivered = Column(Boolean, default=False)
    readAt = Column(DateTime, nullable=True)
    audioUrl = Column(String, nullable=True)
    audioDuration = Column(Float, default=0.0)

Base.metadata.create_all(bind=engine)

# Initialize Firebase Admin SDK
try:
    # Load Firebase configuration from backend.json only
    import json
    with open("backend.json", "r") as f:
        firebase_config = json.load(f)

    cred = credentials.Certificate(firebase_config)
    firebase_admin.initialize_app(cred)
    print("Firebase initialized successfully with backend.json configuration")
    print(f"Project ID: {firebase_config.get('project_id', 'unknown')}")

except Exception as e:
    print(f"Failed to load Firebase configuration from backend.json: {e}")
    print("Push notifications will not work without proper Firebase configuration")

# Seed default admin
db = SessionLocal()
admin = db.query(UserDB).filter(UserDB.email == "admin@admin.com").first()
if not admin:
    admin = UserDB(
        id="admin-1",
        name="Admin",
        email="admin@admin.com",
        password="admin",  # In production, hash this
        avatar="https://i.pravatar.cc/150?u=admin",
        isAdmin=True,
        coins=9999,
        dailyAttempts=3,
        lastAttemptDate=datetime.now(IST),
        isBanned=False
    )
    db.add(admin)
    db.commit()

# Seed default categories
categories_to_seed = [
    {"id": "cat-tech", "name": "Technology"},
    {"id": "cat-games", "name": "Games"},
    {"id": "cat-lifestyle", "name": "Lifestyle"},
    {"id": "cat-science", "name": "Science"},
    {"id": "cat-food", "name": "Food & Drink"},
    {"id": "cat-travel", "name": "Travel"},
    {"id": "cat-movies", "name": "Movies"},
    {"id": "cat-health", "name": "Health & Wellness"},
    {"id": "cat-music", "name": "Music"},
    {"id": "cat-sports", "name": "Sports"},
    {"id": "cat-education", "name": "Education"},
    {"id": "cat-business", "name": "Business"},
]

for cat_data in categories_to_seed:
    existing_cat = db.query(CategoryDB).filter(CategoryDB.id == cat_data["id"]).first()
    if not existing_cat:
        cat = CategoryDB(id=cat_data["id"], name=cat_data["name"])
        db.add(cat)

db.commit()

# Pydantic

class User(BaseModel):
    id: str
    name: str
    email: str
    password: str
    avatar: str
    isAdmin: bool = False
    coins: int = 0
    dailyAttempts: int = 3
    lastAttemptDate: str
    isBanned: bool = False
    mobile: Optional[str] = None
    gender: Optional[str] = None
    bio: Optional[str] = None
    specializations: Optional[List[str]] = None
    referralCode: Optional[str] = None
    referredBy: Optional[str] = None

class CommentUser(BaseModel):
    id: str
    name: str
    email: str
    avatar: str

class PollOption(BaseModel):
    id: str
    text: str
    imageUrl: str
    votes: int = 0
    votedBy: List[str] = []

class Comment(BaseModel):
    id: str
    user: CommentUser
    text: str
    audio_url: Optional[str] = None
    timestamp: str
    likes: int = 0
    replies: List['Comment'] = []
    flaggedForReview: bool = False
    reviewReason: Optional[str] = None

Comment.update_forward_refs()

class Poll(BaseModel):
    id: str
    title: str
    description: str
    category: str
    thumbnail: str
    options: List[PollOption]
    comments: List[Comment]
    createdAt: str
    disableVoiceComments: bool = False

class Category(BaseModel):
    id: str
    name: str

class Report(BaseModel):
    id: str
    pollId: str
    comment: Comment
    reportedBy: CommentUser
    timestamp: str
    status: str
    reason: Optional[str] = None

class RedemptionRequest(BaseModel):
    id: str
    user: CommentUser
    amount: int
    paymentDetails: str
    status: str
    requestedAt: str
    updatedAt: Optional[str] = None
    adminNotes: Optional[str] = None

class Notification(BaseModel):
    id: str
    iconName: str
    text: str
    time: str
    read: bool = False

class GameResult(BaseModel):
    id: str
    user: CommentUser
    targetTime: float
    actualTime: float
    accuracy: float
    coinsWon: int
    playedAt: str

class DeviceToken(BaseModel):
    id: str
    user_id: str
    token: str
    platform: str
    createdAt: str

class AdsStats(BaseModel):
    userId: str
    date: str
    watched: int
    coins: int

class RewardBody(BaseModel):
    userId: str
    amount: int = 5

class LoginRequest(BaseModel):
    email: str
    password: str

class ApplyReferralBody(BaseModel):
    referralCode: str
    joinerUserId: str

class CoinValueBody(BaseModel):
    coinValueINR: float

class ReferralRewardsBody(BaseModel):
    referrerCoins: int
    refereeCoins: int

# Chat Pydantic models
class PublicKeyBody(BaseModel):
    publicKeyJwk: Dict[str, Any]

class SendMessageBody(BaseModel):
    id: str
    senderId: str
    recipientId: str
    ciphertextBase64: str
    ivBase64: str
    createdAt: str

class MessageItem(BaseModel):
    id: str
    senderId: str
    recipientId: str
    ciphertextBase64: str
    ivBase64: str
    createdAt: str
    delivered: bool
    readAt: Optional[str] = None
    audioUrl: Optional[str] = None
    audioDuration: Optional[float] = None

class ConversationItem(BaseModel):
    peerId: str
    lastMessageAt: str
    unreadCount: int

# App

app = FastAPI()

# Mount uploads static after app is created
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Helper

def db_to_user(user_db):
    return User(
        id=user_db.id,
        name=user_db.name,
        email=user_db.email,
        password=user_db.password,
        avatar=user_db.avatar,
        isAdmin=user_db.isAdmin,
        coins=user_db.coins,
        dailyAttempts=user_db.dailyAttempts,
        lastAttemptDate=user_db.lastAttemptDate.isoformat(),
        isBanned=user_db.isBanned,
        mobile=user_db.mobile,
        gender=user_db.gender,
        bio=user_db.bio,
        specializations=json.loads(user_db.specializations) if user_db.specializations else None,
        referralCode=user_db.referralCode,
        referredBy=user_db.referredBy,
    )

def db_to_poll(poll_db, db):
    options = []
    for opt in poll_db.options:
        votedBy = json.loads(opt.votedBy)
        options.append(PollOption(id=opt.id, text=opt.text, imageUrl=opt.imageUrl, votes=opt.votes, votedBy=votedBy))
    comments = []
    def build_comments(comment_db):
        user = CommentUser(id=comment_db.user.id, name=comment_db.user.name, email=comment_db.user.email, avatar=comment_db.user.avatar)
        replies = [build_comments(r) for r in db.query(CommentDB).filter(CommentDB.parent_id == comment_db.id).all()]
        return Comment(id=comment_db.id, user=user, text=comment_db.text, audio_url=comment_db.audio_url, timestamp=comment_db.timestamp.isoformat(), likes=comment_db.likes, replies=replies, flaggedForReview=comment_db.flaggedForReview, reviewReason=comment_db.reviewReason)
    top_comments = db.query(CommentDB).filter(CommentDB.poll_id == poll_db.id, CommentDB.parent_id == None).all()
    for c in top_comments:
        comments.append(build_comments(c))
    return Poll(id=poll_db.id, title=poll_db.title, description=poll_db.description, category=poll_db.category, thumbnail=poll_db.thumbnail, options=options, comments=comments, createdAt=poll_db.createdAt.isoformat(), disableVoiceComments=poll_db.disableVoiceComments)

# Endpoints

@app.get("/test-firebase")
def test_firebase():
    """Test Firebase configuration"""
    if not firebase_admin._apps:
        return {
            "status": "error",
            "message": "Firebase not initialized",
            "configured": False
        }

    try:
        # Get the default app
        app = firebase_admin.get_app()
        return {
            "status": "success",
            "message": "Firebase is properly configured",
            "configured": True,
            "project_id": app.project_id if hasattr(app, 'project_id') else "unknown"
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Firebase configuration error: {str(e)}",
            "configured": False
        }

@app.get("/polls", response_model=List[Poll])
def get_polls(db: Session = Depends(get_db)):
    polls_db = db.query(PollDB).all()
    polls = []
    for p in polls_db:
        polls.append(db_to_poll(p, db))
    return polls

# Trending polls for a particular day (default: today, IST)
@app.get("/trending", response_model=List[Poll])
def get_trending(date: Optional[str] = None, db: Session = Depends(get_db)):
    # date in format YYYY-MM-DD; default to today in IST
    if date:
        try:
            target_date = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    else:
        target_date = datetime.now(IST).date()

    polls_db = db.query(PollDB).all()
    todays = []
    for p in polls_db:
        if not p.createdAt:
            continue
        if p.createdAt.astimezone(IST).date() == target_date:
            todays.append(p)

    # Sort by total votes desc
    todays.sort(key=lambda poll: sum(opt.votes or 0 for opt in poll.options), reverse=True)
    return [db_to_poll(p, db) for p in todays]

@app.get("/polls/{poll_id}", response_model=Poll)
def get_poll(poll_id: str, db: Session = Depends(get_db)):
    poll_db = db.query(PollDB).filter(PollDB.id == poll_id).first()
    if not poll_db:
        raise HTTPException(status_code=404, detail="Poll not found")
    return db_to_poll(poll_db, db)

@app.post("/polls", response_model=Poll)
def add_poll(poll: Poll, db: Session = Depends(get_db)):
    poll_db = PollDB(id=poll.id, title=poll.title, description=poll.description, category=poll.category, thumbnail=poll.thumbnail, createdAt=date_parser.parse(poll.createdAt), disableVoiceComments=poll.disableVoiceComments)
    db.add(poll_db)
    for opt in poll.options:
        opt_db = PollOptionDB(id=opt.id, poll_id=poll.id, text=opt.text, imageUrl=opt.imageUrl, votes=opt.votes, votedBy=json.dumps(opt.votedBy))
        db.add(opt_db)
    db.commit()
    return poll

@app.put("/polls/{poll_id}", response_model=Poll)
def update_poll(poll_id: str, poll: Poll, db: Session = Depends(get_db)):
    poll_db = db.query(PollDB).filter(PollDB.id == poll_id).first()
    if not poll_db:
        raise HTTPException(status_code=404, detail="Poll not found")
    poll_db.title = poll.title
    poll_db.description = poll.description
    poll_db.category = poll.category
    poll_db.thumbnail = poll.thumbnail
    poll_db.disableVoiceComments = poll.disableVoiceComments
    for opt in poll.options:
        opt_db = db.query(PollOptionDB).filter(PollOptionDB.id == opt.id).first()
        if opt_db:
            opt_db.text = opt.text
            opt_db.imageUrl = opt.imageUrl
            opt_db.votes = opt.votes
            opt_db.votedBy = json.dumps(opt.votedBy)
    db.commit()
    return db_to_poll(poll_db, db)

@app.delete("/polls/{poll_id}")
def delete_poll(poll_id: str, db: Session = Depends(get_db)):
    poll_db = db.query(PollDB).filter(PollDB.id == poll_id).first()
    if not poll_db:
        raise HTTPException(status_code=404, detail="Poll not found")
    db.delete(poll_db)
    db.commit()
    return {"message": "Poll deleted"}

@app.post("/polls/{poll_id}/vote")
def add_vote(poll_id: str, option_id: str = Query(...), user_id: str = Query(...), db: Session = Depends(get_db)):
    poll_db = db.query(PollDB).filter(PollDB.id == poll_id).first()
    if not poll_db:
        raise HTTPException(status_code=404, detail="Poll not found")
    opt_db = db.query(PollOptionDB).filter(PollOptionDB.id == option_id, PollOptionDB.poll_id == poll_id).first()
    if not opt_db:
        raise HTTPException(status_code=404, detail="Option not found")
    votedBy = json.loads(opt_db.votedBy)
    if user_id in votedBy:
        return db_to_poll(poll_db, db)
    votedBy.append(user_id)
    opt_db.votes += 1
    opt_db.votedBy = json.dumps(votedBy)
    # Increment user coins by 1 for this vote (with logging)
    user_db = db.query(UserDB).filter(UserDB.id == user_id).first()
    if user_db:
        try:
            before = int(user_db.coins or 0)
            after = before + 1
            user_db.coins = after
            print(f"[coins] add_vote: user={user_id} before={before} after={after}")
        except Exception as e:
            # fallback to simple increment
            try:
                user_db.coins = (user_db.coins or 0) + 1
                print(f"[coins] add_vote fallback increment for user={user_id}")
            except Exception as e2:
                print(f"[coins] add_vote failed for user={user_id}: {e} / {e2}")
    db.commit()
    return db_to_poll(poll_db, db)

@app.post("/polls/{poll_id}/comments", response_model=Poll)
def add_comment(poll_id: str, comment: Comment, db: Session = Depends(get_db)):
    poll_db = db.query(PollDB).filter(PollDB.id == poll_id).first()
    if not poll_db:
        raise HTTPException(status_code=404, detail="Poll not found")
    
    if poll_db.disableVoiceComments:
        raise HTTPException(status_code=403, detail="Comments are disabled for this poll")
    
    comment_db = CommentDB(id=comment.id, poll_id=poll_id, user_id=comment.user.id, text=comment.text, audio_url=comment.audio_url, timestamp=date_parser.parse(comment.timestamp), likes=comment.likes, likedBy="[]", flaggedForReview=comment.flaggedForReview, reviewReason=comment.reviewReason)
    db.add(comment_db)
    db.commit()
    return db_to_poll(poll_db, db)

@app.post("/polls/{poll_id}/comments/{comment_id}/replies", response_model=Poll)
def add_reply(poll_id: str, comment_id: str, reply: Comment, db: Session = Depends(get_db)):
    poll_db = db.query(PollDB).filter(PollDB.id == poll_id).first()
    if not poll_db:
        raise HTTPException(status_code=404, detail="Poll not found")
    
    if poll_db.disableVoiceComments:
        raise HTTPException(status_code=403, detail="Comments are disabled for this poll")
    
    reply_db = CommentDB(id=reply.id, poll_id=poll_id, user_id=reply.user.id, text=reply.text, audio_url=reply.audio_url, timestamp=date_parser.parse(reply.timestamp), likes=reply.likes, likedBy="[]", parent_id=comment_id, flaggedForReview=reply.flaggedForReview, reviewReason=reply.reviewReason)
    db.add(reply_db)
    db.commit()
    return db_to_poll(poll_db, db)

@app.post("/polls/{poll_id}/comments/{comment_id}/like", response_model=Poll)
def like_comment(poll_id: str, comment_id: str, user_id: str = Query(...), db: Session = Depends(get_db)):
    comment_db = db.query(CommentDB).filter(CommentDB.id == comment_id).first()
    if not comment_db:
        raise HTTPException(status_code=404, detail="Comment not found")
    likedBy = json.loads(comment_db.likedBy)
    if user_id in likedBy:
        # User already liked, so unlike (remove like)
        likedBy.remove(user_id)
        comment_db.likes -= 1
        comment_db.likedBy = json.dumps(likedBy)
        db.commit()
        poll_db = db.query(PollDB).filter(PollDB.id == poll_id).first()
        return db_to_poll(poll_db, db)
    else:
        # User hasn't liked yet, so add like
        likedBy.append(user_id)
        comment_db.likes += 1
        comment_db.likedBy = json.dumps(likedBy)
        db.commit()
        poll_db = db.query(PollDB).filter(PollDB.id == poll_id).first()
        return db_to_poll(poll_db, db)

@app.delete("/polls/{poll_id}/comments/{comment_id}", response_model=Poll)
def delete_comment(poll_id: str, comment_id: str, user_id: str = Query(...), db: Session = Depends(get_db)):
    comment_db = db.query(CommentDB).filter(CommentDB.id == comment_id).first()
    if not comment_db:
        raise HTTPException(status_code=404, detail="Comment not found")
    
    # Check if the user owns this comment
    if comment_db.user_id != user_id:
        raise HTTPException(status_code=403, detail="You can only delete your own comments")
    
    def delete_replies(c_id):
        replies = db.query(CommentDB).filter(CommentDB.parent_id == c_id).all()
        for r in replies:
            delete_replies(r.id)
            db.delete(r)
    delete_replies(comment_id)
    db.delete(comment_db)
    db.commit()
    poll_db = db.query(PollDB).filter(PollDB.id == poll_id).first()
    return db_to_poll(poll_db, db)

@app.post("/reports", response_model=Report)
def report_comment(report: Report, db: Session = Depends(get_db)):
    report_db = ReportDB(id=report.id, pollId=report.pollId, comment_id=report.comment.id, reportedBy_id=report.reportedBy.id, timestamp=date_parser.parse(report.timestamp), status=report.status, reason=report.reason)
    db.add(report_db)
    db.commit()
    return report

@app.post("/categories", response_model=Category)
def add_category(category: Category, db: Session = Depends(get_db)):
    category_db = CategoryDB(id=category.id, name=category.name)
    db.add(category_db)
    db.commit()
    return category

@app.delete("/categories/{category_id}")
def delete_category(category_id: str, db: Session = Depends(get_db)):
    """Delete a category by ID and all polls within it"""
    category_db = db.query(CategoryDB).filter(CategoryDB.id == category_id).first()
    if not category_db:
        raise HTTPException(status_code=404, detail="Category not found")

    # Get all polls in this category
    polls_to_delete = db.query(PollDB).filter(PollDB.category == category_id).all()

    deleted_polls_count = 0
    for poll_db in polls_to_delete:
        # Delete all comments and their replies for this poll
        def delete_comments_and_replies(poll_id):
            comments = db.query(CommentDB).filter(CommentDB.poll_id == poll_id).all()
            for comment in comments:
                # Delete reports related to this comment
                db.query(ReportDB).filter(ReportDB.comment_id == comment.id).delete()
                # Delete replies recursively
                def delete_replies(comment_id):
                    replies = db.query(CommentDB).filter(CommentDB.parent_id == comment_id).all()
                    for reply in replies:
                        delete_replies(reply.id)
                        db.delete(reply)
                delete_replies(comment.id)
                # Delete the comment itself
                db.delete(comment)

        # Delete all comments and replies for this poll
        delete_comments_and_replies(poll_db.id)

        # Delete all poll options for this poll
        db.query(PollOptionDB).filter(PollOptionDB.poll_id == poll_db.id).delete()

        # Delete the poll itself
        db.delete(poll_db)
        deleted_polls_count += 1

    # Delete the category
    db.delete(category_db)
    db.commit()

    return {
        "message": f"Category and {deleted_polls_count} poll(s) deleted successfully"
    }

def today_ist_date_str() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d")

@app.get("/ads/stats")
def get_ads_stats(user_id: str = Query(...), db: Session = Depends(get_db)):
    """Return today's ad stats for a user (IST)."""
    date_str = today_ist_date_str()
    row = db.query(AdsStatsDB).filter(AdsStatsDB.user_id == user_id, AdsStatsDB.date == date_str).first()
    if not row:
        return {"userId": user_id, "date": date_str, "watched": 0, "coins": 0}
    return {"userId": user_id, "date": row.date, "watched": row.watched, "coins": row.coins}

@app.post("/ads/reward")
def post_ads_reward(body: RewardBody, db: Session = Depends(get_db)):
    """Grant rewarded-ad coins and increment today's watched/coins in a single transaction."""
    user_db = db.query(UserDB).filter(UserDB.id == body.userId).first()
    if not user_db:
        raise HTTPException(status_code=404, detail="User not found")
    date_str = today_ist_date_str()
    try:
        before = int(user_db.coins or 0)
    except Exception:
        before = 0
    grant = max(0, int(body.amount or 0))
    try:
        # Update coins
        user_db.coins = before + grant
        # Upsert stats
        row = db.query(AdsStatsDB).filter(AdsStatsDB.user_id == body.userId, AdsStatsDB.date == date_str).first()
        if not row:
            row = AdsStatsDB(user_id=body.userId, date=date_str, watched=1 if grant > 0 else 0, coins=grant)
            db.add(row)
        else:
            row.watched = int(row.watched or 0) + (1 if grant > 0 else 0)
            row.coins = int(row.coins or 0) + grant
        db.commit()
        print(f"[ads] reward: user={body.userId} +{grant} before={before} after={user_db.coins} date={date_str}")
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to grant reward: {e}")
    # Return updated user and stats
    row = db.query(AdsStatsDB).filter(AdsStatsDB.user_id == body.userId, AdsStatsDB.date == date_str).first()
    return {"success": True, "user": db_to_user(user_db), "stats": {"userId": body.userId, "date": date_str, "watched": row.watched, "coins": row.coins}}

@app.get("/users/{user_id}", response_model=User)
def get_user(user_id: str, db: Session = Depends(get_db)):
    user_db = db.query(UserDB).filter(UserDB.id == user_id).first()
    if not user_db:
        raise HTTPException(status_code=404, detail="User not found")
    return db_to_user(user_db)

@app.get("/users", response_model=List[User])
def get_users(db: Session = Depends(get_db)):
    users_db = db.query(UserDB).all()
    return [db_to_user(u) for u in users_db]

# Settings helpers
def get_setting(db: Session, key: str, default: str | None = None) -> Optional[str]:
    s = db.query(SettingsDB).filter(SettingsDB.key == key).first()
    return s.value if s else default

def set_setting(db: Session, key: str, value: str) -> None:
    s = db.query(SettingsDB).filter(SettingsDB.key == key).first()
    if s:
        s.value = value
    else:
        s = SettingsDB(key=key, value=value)
        db.add(s)
    db.commit()

@app.get("/settings/coin-value")
def get_coin_value(db: Session = Depends(get_db)):
    val = get_setting(db, "coinValueINR", "0")
    try:
        coin_val = float(val) if val is not None else 0.0
    except ValueError:
        coin_val = 0.0
    return {"coinValueINR": coin_val}

@app.put("/settings/coin-value")
def put_coin_value(body: CoinValueBody, db: Session = Depends(get_db)):
    set_setting(db, "coinValueINR", str(body.coinValueINR))
    return {"success": True}

@app.get("/settings/referral-rewards")
def get_referral_rewards(db: Session = Depends(get_db)):
    # Defaults: referee 5, referrer 15
    referrer = get_setting(db, "referralReferrerCoins", "15")
    referee = get_setting(db, "referralRefereeCoins", "5")
    try:
        referrer_i = int(referrer) if referrer is not None else 15
    except ValueError:
        referrer_i = 15
    try:
        referee_i = int(referee) if referee is not None else 5
    except ValueError:
        referee_i = 5
    return {"referrerCoins": referrer_i, "refereeCoins": referee_i}

@app.put("/settings/referral-rewards")
def put_referral_rewards(body: ReferralRewardsBody, db: Session = Depends(get_db)):
    set_setting(db, "referralReferrerCoins", str(body.referrerCoins))
    set_setting(db, "referralRefereeCoins", str(body.refereeCoins))
    return {"success": True}

@app.post("/referral/apply")
def apply_referral(body: ApplyReferralBody, db: Session = Depends(get_db)):
    joiner = db.query(UserDB).filter(UserDB.id == body.joinerUserId).first()
    if not joiner:
        raise HTTPException(status_code=404, detail="Joiner user not found")
    if joiner.referredBy:
        raise HTTPException(status_code=400, detail="Referral already applied for this user")
    # Find referrer by referral code
    referrer = db.query(UserDB).filter(UserDB.referralCode == body.referralCode).first()
    if not referrer:
        raise HTTPException(status_code=404, detail="Invalid referral code")
    if referrer.id == joiner.id:
        raise HTTPException(status_code=400, detail="Cannot refer yourself")

    # Read rewards
    rewards = get_referral_rewards(db)
    referrer_reward = rewards["referrerCoins"]
    referee_reward = rewards["refereeCoins"]

    # Apply atomically
    try:
        try:
            before_joiner = int(joiner.coins or 0)
        except Exception:
            before_joiner = 0
        try:
            before_referrer = int(referrer.coins or 0)
        except Exception:
            before_referrer = 0

        joiner.coins = int(joiner.coins or 0) + int(referee_reward)
        joiner.referredBy = referrer.id
        referrer.coins = int(referrer.coins or 0) + int(referrer_reward)
        db.commit()

        after_joiner = int(joiner.coins or 0)
        after_referrer = int(referrer.coins or 0)
        print(f"[coins] apply_referral: joiner={joiner.id} before={before_joiner} after={after_joiner}; referrer={referrer.id} before={before_referrer} after={after_referrer}")
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to apply referral: {e}")

    return {
        "success": True,
        "referrer": db_to_user(referrer),
        "referee": db_to_user(joiner)
    }

@app.post("/login")
def login(request: LoginRequest, db: Session = Depends(get_db)):
    user_db = db.query(UserDB).filter(UserDB.email == request.email, UserDB.password == request.password).first()
    if not user_db:
        return {"success": False, "message": "Invalid email or password"}
    if user_db.isBanned:
        return {"success": False, "message": "This account has been banned."}
    return {"success": True, "user": db_to_user(user_db)}

@app.post("/signup", response_model=User)
def signup(user: User, db: Session = Depends(get_db)):
    existing = db.query(UserDB).filter(UserDB.email == user.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Email already exists")
    user_db = UserDB(
        id=user.id,
        name=user.name,
        email=user.email,
        password=user.password,
        avatar=user.avatar,
        isAdmin=user.isAdmin,
        coins=user.coins,
        dailyAttempts=user.dailyAttempts,
        lastAttemptDate=date_parser.parse(user.lastAttemptDate),
        isBanned=user.isBanned,
        mobile=user.mobile,
        gender=user.gender,
        bio=user.bio,
        specializations=json.dumps(user.specializations) if user.specializations else None,
        referralCode=user.referralCode,
        referredBy=user.referredBy,
    )
    db.add(user_db)
    db.commit()
    return db_to_user(user_db)

@app.post("/users/{user_id}/coins/increment")
def increment_user_coins(user_id: str, amount: int = Query(1, ge=1), db: Session = Depends(get_db)):
    user_db = db.query(UserDB).filter(UserDB.id == user_id).first()
    if not user_db:
        raise HTTPException(status_code=404, detail="User not found")
    try:
        before = int(user_db.coins or 0)
    except Exception:
        before = 0
    after = before + int(amount)
    user_db.coins = after
    db.commit()
    print(f"[coins] increment: user={user_id} +{amount} before={before} after={after}")
    return {"success": True, "coins": after}

@app.post("/users/{user_id}/coins/decrement")
def decrement_user_coins(user_id: str, amount: int = Query(1, ge=1), db: Session = Depends(get_db)):
    user_db = db.query(UserDB).filter(UserDB.id == user_id).first()
    if not user_db:
        raise HTTPException(status_code=404, detail="User not found")
    try:
        before = int(user_db.coins or 0)
    except Exception:
        before = 0
    if before < amount:
        raise HTTPException(status_code=400, detail=f"Insufficient coins. Current: {before}, required: {amount}")
    after = before - int(amount)
    user_db.coins = after
    db.commit()
    print(f"[coins] decrement: user={user_id} -{amount} before={before} after={after}")
    return {"success": True, "coins": after}

@app.post("/forgot-password")
def forgot_password(email: str):
    return {"success": True, "message": f"If an account exists for {email}, a password reset link has been sent."}

@app.put("/users/{user_id}", response_model=User)
def update_user(user_id: str, user: User, db: Session = Depends(get_db)):
    user_db = db.query(UserDB).filter(UserDB.id == user_id).first()
    if not user_db:
        raise HTTPException(status_code=404, detail="User not found")
    try:
        before_coins = int(user_db.coins or 0)
    except Exception:
        before_coins = 0

    user_db.name = user.name
    user_db.email = user.email
    user_db.password = user.password
    user_db.avatar = user.avatar
    user_db.isAdmin = user.isAdmin
    # Do NOT set coins from client payload to avoid overwriting server-side balance
    user_db.dailyAttempts = user.dailyAttempts
    user_db.lastAttemptDate = date_parser.parse(user.lastAttemptDate)
    user_db.isBanned = user.isBanned
    user_db.mobile = user.mobile
    user_db.gender = user.gender
    user_db.bio = user.bio
    user_db.specializations = json.dumps(user.specializations) if user.specializations else None
    user_db.referralCode = user.referralCode
    user_db.referredBy = user.referredBy

    try:
        after_coins = int(user_db.coins or 0)
    except Exception:
        after_coins = 0
    if before_coins != after_coins:
        print(f"[coins] update_user: user={user_id} before={before_coins} after={after_coins}")

    db.commit()
    return db_to_user(user_db)

@app.delete("/users/{user_id}")
def delete_user(user_id: str, db: Session = Depends(get_db)):
    user_db = db.query(UserDB).filter(UserDB.id == user_id).first()
    if not user_db:
        raise HTTPException(status_code=404, detail="User not found")
    db.delete(user_db)
    db.commit()
    return {"message": "User deleted"}

@app.get("/users/{user_id}/coins")
def get_user_coins(user_id: str, db: Session = Depends(get_db)):
    user_db = db.query(UserDB).filter(UserDB.id == user_id).first()
    if not user_db:
        raise HTTPException(status_code=404, detail="User not found")
    return {"coins": user_db.coins}

@app.post("/users/{user_id}/attempt")
def use_game_attempt(user_id: str, db: Session = Depends(get_db)):
    user_db = db.query(UserDB).filter(UserDB.id == user_id).first()
    if not user_db:
        raise HTTPException(status_code=404, detail="User not found")
    user_db.dailyAttempts -= 1
    user_db.lastAttemptDate = datetime.now(IST)
    db.commit()
    return db_to_user(user_db)

@app.post("/users/{user_id}/refresh-attempts")
def refresh_user_attempts(user_id: str, db: Session = Depends(get_db)):
    user_db = db.query(UserDB).filter(UserDB.id == user_id).first()
    if not user_db:
        raise HTTPException(status_code=404, detail="User not found")
    if (datetime.now(IST) - user_db.lastAttemptDate).days >= 1:
        user_db.dailyAttempts = 3
        user_db.lastAttemptDate = datetime.now(IST)
    db.commit()
    return db_to_user(user_db)

@app.post("/users/{user_id}/ban")
def ban_user(user_id: str, db: Session = Depends(get_db)):
    user_db = db.query(UserDB).filter(UserDB.id == user_id).first()
    if not user_db:
        raise HTTPException(status_code=404, detail="User not found")
    user_db.isBanned = True
    db.commit()
    return db_to_user(user_db)

@app.post("/users/{user_id}/toggle-ban")
def toggle_user_ban(user_id: str, db: Session = Depends(get_db)):
    user_db = db.query(UserDB).filter(UserDB.id == user_id).first()
    if not user_db:
        raise HTTPException(status_code=404, detail="User not found")
    user_db.isBanned = not user_db.isBanned
    db.commit()
    return db_to_user(user_db)

@app.get("/notifications", response_model=List[Notification])
def get_notifications(db: Session = Depends(get_db)):
    notifs = db.query(NotificationDB).all()
    return [Notification(id=n.id, iconName=n.iconName, text=n.text, time=n.time, read=n.read) for n in notifs]

@app.post("/notifications", response_model=Notification)
def send_notification(notif: Notification, db: Session = Depends(get_db)):
    notif_db = NotificationDB(id=notif.id, iconName=notif.iconName, text=notif.text, time=notif.time, read=notif.read)
    db.add(notif_db)
    db.commit()
    return notif

@app.post("/notifications/mark-read")
def mark_all_notifications_as_read(db: Session = Depends(get_db)):
    db.query(NotificationDB).update({"read": True})
    db.commit()
    return {"message": "All notifications marked as read"}

@app.put("/reports/{report_id}", response_model=Report)
def resolve_report(report_id: str, db: Session = Depends(get_db)):
    report_db = db.query(ReportDB).options(selectinload(ReportDB.comment).selectinload(CommentDB.user), selectinload(ReportDB.reportedBy)).filter(ReportDB.id == report_id).first()
    if not report_db:
        raise HTTPException(status_code=404, detail="Report not found")
    if report_db.comment is None or report_db.reportedBy is None:
        raise HTTPException(status_code=404, detail="Report relationships not found")
    report_db.status = "resolved"
    db.commit()
    comment = db_to_comment(report_db.comment, db)
    reportedBy = CommentUser(id=report_db.reportedBy.id, name=report_db.reportedBy.name, email=report_db.reportedBy.email, avatar=report_db.reportedBy.avatar)
    return Report(id=report_db.id, pollId=report_db.pollId, comment=comment, reportedBy=reportedBy, timestamp=report_db.timestamp.isoformat(), status=report_db.status, reason=report_db.reason)

@app.delete("/reports/{report_id}")
def delete_report(report_id: str, db: Session = Depends(get_db)):
    report_db = db.query(ReportDB).filter(ReportDB.id == report_id).first()
    if not report_db:
        raise HTTPException(status_code=404, detail="Report not found")
    db.delete(report_db)
    db.commit()
    return {"message": "Report deleted"}

@app.get("/reports", response_model=List[Report])
def get_reports(db: Session = Depends(get_db)):
    reports_db = db.query(ReportDB).options(selectinload(ReportDB.comment).selectinload(CommentDB.user), selectinload(ReportDB.reportedBy)).all()
    reports = []
    for r in reports_db:
        if r.comment is None or r.reportedBy is None:
            # Skip reports with missing relationships
            continue
        comment = db_to_comment(r.comment, db)
        reportedBy = CommentUser(id=r.reportedBy.id, name=r.reportedBy.name, email=r.reportedBy.email, avatar=r.reportedBy.avatar)
        reports.append(Report(id=r.id, pollId=r.pollId, comment=comment, reportedBy=reportedBy, timestamp=r.timestamp.isoformat(), status=r.status, reason=r.reason))
    return reports

@app.post("/redemption-requests", response_model=RedemptionRequest)
def add_redemption_request(request: RedemptionRequest, db: Session = Depends(get_db)):
    request_db = RedemptionRequestDB(id=request.id, user_id=request.user.id, amount=request.amount, paymentDetails=request.paymentDetails, status=request.status, requestedAt=date_parser.parse(request.requestedAt), updatedAt=date_parser.parse(request.updatedAt) if request.updatedAt else None, adminNotes=request.adminNotes)
    db.add(request_db)
    db.commit()
    # Reload the request with user relationship
    request_db = db.query(RedemptionRequestDB).options(selectinload(RedemptionRequestDB.user)).filter(RedemptionRequestDB.id == request.id).first()
    if request_db and request_db.user:
        user = CommentUser(id=request_db.user.id, name=request_db.user.name, email=request_db.user.email, avatar=request_db.user.avatar)
        return RedemptionRequest(id=request_db.id, user=user, amount=request_db.amount, paymentDetails=request_db.paymentDetails, status=request_db.status, requestedAt=request_db.requestedAt.isoformat(), updatedAt=request_db.updatedAt.isoformat() if request_db.updatedAt else None, adminNotes=request_db.adminNotes)
    else:
        # Fallback if user relationship fails to load
        return request

@app.put("/redemption-requests/{request_id}", response_model=RedemptionRequest)
def update_redemption_request_status(request_id: str, request_data: Dict[str, str], db: Session = Depends(get_db)):
    request_db = db.query(RedemptionRequestDB).options(selectinload(RedemptionRequestDB.user)).filter(RedemptionRequestDB.id == request_id).first()
    if not request_db:
        raise HTTPException(status_code=404, detail="Request not found")
    if request_db.user is None:
        raise HTTPException(status_code=404, detail="User not found for this request")

    new_status = request_data.get("status", request_db.status)
    old_status = request_db.status

    # If status is being changed to "processed" and it wasn't already processed, deduct coins
    if new_status == "processed" and old_status != "processed":
        user_db = db.query(UserDB).filter(UserDB.id == request_db.user_id).first()
        if not user_db:
            raise HTTPException(status_code=404, detail="User account not found")

        # Check if user has enough coins
        if user_db.coins < request_db.amount:
            raise HTTPException(status_code=400, detail=f"User does not have enough coins. Current balance: {user_db.coins}, Required: {request_db.amount}")

        # Deduct coins from user's account
        user_db.coins -= request_db.amount

    # If status is being changed from "processed" to something else, refund coins
    elif old_status == "processed" and new_status != "processed":
        user_db = db.query(UserDB).filter(UserDB.id == request_db.user_id).first()
        if user_db:
            # Refund coins to user's account
            user_db.coins += request_db.amount

    request_db.status = new_status
    request_db.adminNotes = request_data.get("adminNotes", request_db.adminNotes)
    request_db.updatedAt = datetime.now(IST)
    db.commit()
    user = CommentUser(id=request_db.user.id, name=request_db.user.name, email=request_db.user.email, avatar=request_db.user.avatar)
    return RedemptionRequest(id=request_db.id, user=user, amount=request_db.amount, paymentDetails=request_db.paymentDetails, status=request_db.status, requestedAt=request_db.requestedAt.isoformat(), updatedAt=request_db.updatedAt.isoformat(), adminNotes=request_db.adminNotes)

@app.get("/redemption-requests", response_model=List[RedemptionRequest])
def get_redemption_requests(db: Session = Depends(get_db)):
    requests_db = db.query(RedemptionRequestDB).options(selectinload(RedemptionRequestDB.user)).all()
    requests = []
    for req in requests_db:
        if req.user is None:
            # Skip redemption requests with missing users
            continue
        user = CommentUser(id=req.user.id, name=req.user.name, email=req.user.email, avatar=req.user.avatar)
        requests.append(RedemptionRequest(id=req.id, user=user, amount=req.amount, paymentDetails=req.paymentDetails, status=req.status, requestedAt=req.requestedAt.isoformat(), updatedAt=req.updatedAt.isoformat() if req.updatedAt else None, adminNotes=req.adminNotes))
    return requests

def db_to_comment(comment_db, db):
    user = CommentUser(id=comment_db.user.id, name=comment_db.user.name, email=comment_db.user.email, avatar=comment_db.user.avatar)
    replies = [db_to_comment(r, db) for r in db.query(CommentDB).filter(CommentDB.parent_id == comment_db.id).all()]
    return Comment(id=comment_db.id, user=user, text=comment_db.text, audio_url=comment_db.audio_url, timestamp=comment_db.timestamp.isoformat(), likes=comment_db.likes, replies=replies, flaggedForReview=comment_db.flaggedForReview, reviewReason=comment_db.reviewReason)

@app.post("/game-results", response_model=GameResult)
def save_game_result(game_result: GameResult, db: Session = Depends(get_db)):
    game_result_db = GameResultDB(
        id=game_result.id,
        user_id=game_result.user.id,
        targetTime=game_result.targetTime,
        actualTime=game_result.actualTime,
        accuracy=game_result.accuracy,
        coinsWon=game_result.coinsWon,
        playedAt=date_parser.parse(game_result.playedAt)
    )
    db.add(game_result_db)
    
    # Update user's coins if coins were won (with logging)
    if game_result.coinsWon > 0:
        user_db = db.query(UserDB).filter(UserDB.id == game_result.user.id).first()
        if user_db:
            try:
                before = int(user_db.coins or 0)
            except Exception:
                before = 0
            after = before + int(game_result.coinsWon)
            user_db.coins = after
            print(f"[coins] save_game_result: user={game_result.user.id} coinsWon={game_result.coinsWon} before={before} after={after}")
    
    db.commit()
    return game_result

@app.get("/game-results/{user_id}", response_model=List[GameResult])
def get_user_game_results(user_id: str, db: Session = Depends(get_db)):
    game_results_db = db.query(GameResultDB).options(selectinload(GameResultDB.user)).filter(GameResultDB.user_id == user_id).order_by(GameResultDB.playedAt.desc()).all()
    results = []
    for gr in game_results_db:
        if gr.user is None:
            # Skip game results with missing users
            continue
        user = CommentUser(id=gr.user.id, name=gr.user.name, email=gr.user.email, avatar=gr.user.avatar)
        results.append(GameResult(
            id=gr.id,
            user=user,
            targetTime=gr.targetTime,
            actualTime=gr.actualTime,
            accuracy=gr.accuracy,
            coinsWon=gr.coinsWon,
            playedAt=gr.playedAt.isoformat()
        ))
    return results

@app.get("/game-results/{user_id}/today-count")
def get_user_today_game_count(user_id: str, db: Session = Depends(get_db)):
    """Get the count of games played by a user today"""
    # Get today's date in IST (start and end of day)
    now = datetime.now(IST)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)

    # Query for games played today (UTC time)
    today_games_count = db.query(GameResultDB).filter(
        GameResultDB.user_id == user_id,
        GameResultDB.playedAt >= today_start,
        GameResultDB.playedAt < today_end
    ).count()

    return {
        "count": today_games_count,
        "user_id": user_id,
        "date": today_start.date().isoformat(),
        "timezone": "IST"
    }

@app.post("/device-tokens", response_model=DeviceToken)
def store_device_token(token_data: DeviceToken, db: Session = Depends(get_db)):
    # Check if token already exists
    existing = db.query(DeviceTokenDB).filter(DeviceTokenDB.token == token_data.token).first()
    if existing:
        # Update if user changed or something, but for now just return
        return DeviceToken(id=existing.id, user_id=existing.user_id, token=existing.token, platform=existing.platform, createdAt=existing.createdAt.isoformat())
    
    token_db = DeviceTokenDB(id=token_data.id, user_id=token_data.user_id, token=token_data.token, platform=token_data.platform, createdAt=date_parser.parse(token_data.createdAt))
    db.add(token_db)
    db.commit()
    return token_data

@app.get("/analytics/polls")
def get_poll_analytics(db: Session = Depends(get_db)):
    """Get analytics data for all polls"""
    polls = db.query(PollDB).options(
        selectinload(PollDB.comments).selectinload(CommentDB.user),
        selectinload(PollDB.options)
    ).all()
    analytics = []
    
    for poll in polls:
        total_votes = sum(option.votes for option in poll.options)
        total_comments = len(poll.comments)
        
        # Count all replies recursively
        def count_replies(comments):
            count = 0
            for comment in comments:
                count += 1
                if comment.replies:
                    count += count_replies(comment.replies)
            return count
        
        total_comments = count_replies(poll.comments)
        
        # Get voter details for each option
        options_analytics = []
        for option in poll.options:
            voters = []
            if option.votedBy:
                voter_ids = json.loads(option.votedBy)
                for voter_id in voter_ids:
                    user = db.query(UserDB).filter(UserDB.id == voter_id).first()
                    if user:
                        voters.append({
                            "id": user.id,
                            "name": user.name,
                            "email": user.email
                        })
            
            options_analytics.append({
                "id": option.id,
                "text": option.text,
                "votes": option.votes,
                "voters": voters
            })
        
        # Get all unique commenters (including those who replied recursively)
        # Load all comments for this poll to ensure we get all replies
        all_comments = db.query(CommentDB).options(selectinload(CommentDB.user)).filter(CommentDB.poll_id == poll.id).all()
        
        commenters_set = set()
        for comment in all_comments:
            user = CommentUser(id=comment.user.id, name=comment.user.name, email=comment.user.email, avatar=comment.user.avatar)
            commenters_set.add((user.id, user.name, user.email, user.avatar))
        
        commenters = [{"id": c[0], "name": c[1], "email": c[2], "avatar": c[3]} for c in commenters_set]
        
        analytics.append({
            "id": poll.id,
            "title": poll.title,
            "category": poll.category,
            "total_votes": total_votes,
            "total_comments": total_comments,
            "created_at": poll.createdAt.isoformat(),
            "options_count": len(poll.options),
            "options": options_analytics,
            "commenters": commenters
        })
    
    return analytics

@app.get("/analytics/polls/{poll_id}")
def get_poll_detailed_analytics(poll_id: str, db: Session = Depends(get_db)):
    """Get detailed analytics for a specific poll"""
    poll = db.query(PollDB).options(
        selectinload(PollDB.comments).selectinload(CommentDB.user),
        selectinload(PollDB.options)
    ).filter(PollDB.id == poll_id).first()
    if not poll:
        raise HTTPException(status_code=404, detail="Poll not found")
    
    total_votes = sum(option.votes for option in poll.options)
    
    # Count all replies recursively
    def count_replies(comments):
        count = 0
        for comment in comments:
            count += 1
            if comment.replies:
                count += count_replies(comment.replies)
        return count
    
    total_comments = count_replies(poll.comments)
    
    # Get voter details for each option
    options_analytics = []
    for option in poll.options:
        voters = []
        if option.votedBy:
            voter_ids = json.loads(option.votedBy)
            for voter_id in voter_ids:
                user = db.query(UserDB).filter(UserDB.id == voter_id).first()
                if user:
                    voters.append({
                        "id": user.id,
                        "name": user.name,
                        "email": user.email
                    })
        
        options_analytics.append({
            "id": option.id,
            "text": option.text,
            "votes": option.votes,
            "voters": voters
        })
    
    # Get all unique commenters (including those who replied recursively)
    # Load all comments for this poll to ensure we get all replies
    all_comments = db.query(CommentDB).options(selectinload(CommentDB.user)).filter(CommentDB.poll_id == poll.id).all()
    
    commenters_set = set()
    for comment in all_comments:
        user = CommentUser(id=comment.user.id, name=comment.user.name, email=comment.user.email, avatar=comment.user.avatar)
        commenters_set.add((user.id, user.name, user.email, user.avatar))
    
    commenters = [{"id": c[0], "name": c[1], "email": c[2], "avatar": c[3]} for c in commenters_set]
    
    return {
        "id": poll.id,
        "title": poll.title,
        "description": poll.description,
        "category": poll.category,
        "thumbnail": poll.thumbnail,
        "total_votes": total_votes,
        "total_comments": total_comments,
        "created_at": poll.createdAt.isoformat(),
        "options": options_analytics,
        "commenters": commenters
    }

@app.post("/send-push-notification")
def send_push_notification(notification_data: Dict[str, str], db: Session = Depends(get_db)):
    """Send push notification to all registered device tokens using FCM"""
    title = notification_data.get("title", "PollPlay Notification")
    body = notification_data.get("body", "")

    if not body.strip():
        raise HTTPException(status_code=400, detail="Notification body cannot be empty")

    # Get all device tokens
    device_tokens = db.query(DeviceTokenDB).all()

    if not device_tokens:
        return {"message": "No device tokens found", "sent_count": 0}

    if not firebase_admin._apps:
        raise HTTPException(status_code=500, detail="Firebase not initialized. Please configure Firebase credentials.")

    sent_count = 0
    failed_count = 0
    failed_tokens = []

    # Send notifications one by one
    for token_record in device_tokens:
        try:
            message = messaging.Message(
                notification=messaging.Notification(
                    title=title,
                    body=body,
                ),
                token=token_record.token,
            )

            if token_record.platform.lower() == "android":
                message.android = messaging.AndroidConfig(
                    priority="high",
                    notification=messaging.AndroidNotification(
                        channel_id="default",
                        priority="high",
                        default_sound=True,
                        default_vibrate_timings=True,
                    ),
                )
            elif token_record.platform.lower() == "ios":
                message.apns = messaging.APNSConfig(
                    payload=messaging.APNSPayload(
                        aps=messaging.Aps(
                            alert=messaging.ApsAlert(
                                title=title,
                                body=body,
                            ),
                            badge=1,
                            sound="default",
                        ),
                    ),
                )

            response = messaging.send(message)
            sent_count += 1
            print(f"Notification sent successfully to {token_record.token}")

        except Exception as e:
            failed_count += 1
            failed_tokens.append({
                "token": token_record.token,
                "platform": token_record.platform,
                "error": str(e)
            })
            print(f"Failed to send notification to {token_record.token}: {e}")

    # Log results
    print(f"Push notification sent: {title}")
    print(f"Total tokens: {len(device_tokens)}")
    print(f"Successful sends: {sent_count}")
    print(f"Failed sends: {failed_count}")

    if failed_tokens:
        print("Failed tokens:", failed_tokens)

    return {
        "message": f"Notification sent to {sent_count} devices successfully",
        "sent_count": sent_count,
        "failed_count": failed_count,
        "total_tokens": len(device_tokens)
    }

# =============================
# Chat/E2E encryption endpoints
# =============================

@app.put("/users/{user_id}/public-key")
def put_public_key(user_id: str, body: PublicKeyBody, db: Session = Depends(get_db)):
    user = db.query(UserDB).filter(UserDB.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    existing = db.query(UserPublicKeyDB).filter(UserPublicKeyDB.user_id == user_id).first()
    now = datetime.now(IST)
    as_text = json.dumps(body.publicKeyJwk)
    if existing:
        existing.public_jwk = as_text
        existing.updatedAt = now
    else:
        db.add(UserPublicKeyDB(user_id=user_id, public_jwk=as_text, updatedAt=now))
    db.commit()
    return {"success": True}

@app.get("/users/{user_id}/public-key")
def get_public_key(user_id: str, db: Session = Depends(get_db)):
    rec = db.query(UserPublicKeyDB).filter(UserPublicKeyDB.user_id == user_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Public key not found")
    try:
        jwk = json.loads(rec.public_jwk)
    except Exception:
        jwk = rec.public_jwk
    return {"publicKeyJwk": jwk, "updatedAt": rec.updatedAt.isoformat() if rec.updatedAt else None}

@app.post("/messages")
def send_message(body: SendMessageBody, db: Session = Depends(get_db)):
    # Validate users
    if not db.query(UserDB).filter(UserDB.id == body.senderId).first():
        raise HTTPException(status_code=404, detail="Sender not found")
    if not db.query(UserDB).filter(UserDB.id == body.recipientId).first():
        raise HTTPException(status_code=404, detail="Recipient not found")

    created_at = date_parser.parse(body.createdAt)
    msg = MessageDB(
        id=body.id,
        sender_id=body.senderId,
        recipient_id=body.recipientId,
        ciphertext=body.ciphertextBase64,
        iv=body.ivBase64,
        createdAt=created_at,
        delivered=True,
        readAt=None,
    )
    db.add(msg)
    db.commit()
    return {"success": True}

@app.get("/conversations/{user_id}", response_model=List[ConversationItem])
def list_conversations(user_id: str, db: Session = Depends(get_db)):
    # Fetch peers where user is sender or recipient
    sent = db.query(MessageDB.recipient_id.label("peer"))\
        .filter(MessageDB.sender_id == user_id)
    received = db.query(MessageDB.sender_id.label("peer"))\
        .filter(MessageDB.recipient_id == user_id)

    peers = set([row.peer for row in sent.union_all(received).all()])

    items: List[ConversationItem] = []
    for peer in peers:
        last = db.query(MessageDB).filter(
            ((MessageDB.sender_id == user_id) & (MessageDB.recipient_id == peer)) |
            ((MessageDB.sender_id == peer) & (MessageDB.recipient_id == user_id))
        ).order_by(MessageDB.createdAt.desc()).first()
        if not last:
            continue
        unread = db.query(MessageDB).filter(
            (MessageDB.recipient_id == user_id) & (MessageDB.sender_id == peer) & (MessageDB.readAt == None)
        ).count()
        items.append(ConversationItem(
            peerId=peer,
            lastMessageAt=last.createdAt.isoformat(),
            unreadCount=unread,
        ))
    # Sort by lastMessageAt desc
    items.sort(key=lambda x: x.lastMessageAt, reverse=True)
    return items

@app.get("/messages/thread", response_model=List[MessageItem])
def get_thread(userA: str = Query(...), userB: str = Query(...), after: Optional[str] = None, limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db)):
    q = db.query(MessageDB).filter(
        ((MessageDB.sender_id == userA) & (MessageDB.recipient_id == userB)) |
        ((MessageDB.sender_id == userB) & (MessageDB.recipient_id == userA))
    )
    if after:
        try:
            after_dt = date_parser.parse(after)
            q = q.filter(MessageDB.createdAt > after_dt)
        except Exception:
            pass
    msgs = q.order_by(MessageDB.createdAt.asc()).limit(limit).all()
    result: List[MessageItem] = []
    for m in msgs:
        result.append(MessageItem(
            id=m.id,
            senderId=m.sender_id,
            recipientId=m.recipient_id,
            ciphertextBase64=m.ciphertext,
            ivBase64=m.iv,
            createdAt=m.createdAt.isoformat(),
            delivered=bool(m.delivered),
            readAt=m.readAt.isoformat() if m.readAt else None,
            audioUrl=m.audioUrl,
            audioDuration=m.audioDuration,
        ))
    return result

@app.post("/messages/{message_id}/read")
def mark_message_read(message_id: str, db: Session = Depends(get_db)):
    m = db.query(MessageDB).filter(MessageDB.id == message_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="Message not found")
    if not m.readAt:
        m.readAt = datetime.now(IST)
        db.commit()
    return {"success": True, "readAt": m.readAt.isoformat() if m.readAt else None}

# Presence endpoints
@app.post("/presence/ping")
def presence_ping(user_id: str = Query(...), db: Session = Depends(get_db)):
    u = db.query(UserDB).filter(UserDB.id == user_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    u.lastSeen = datetime.now(IST)
    db.commit()
    return {"success": True}

@app.get("/presence/{user_id}")
def presence_status(user_id: str, db: Session = Depends(get_db)):
    u = db.query(UserDB).filter(UserDB.id == user_id).first()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    now = datetime.now(IST)
    online = False
    if u.lastSeen:
        online = (now - u.lastSeen) <= timedelta(minutes=2)
    return {"userId": user_id, "online": online, "lastSeen": u.lastSeen.isoformat() if u.lastSeen else None}

# Voice message upload
@app.post("/messages/voice")
def upload_voice_message(
    id: str = Form(...),
    senderId: str = Form(...),
    recipientId: str = Form(...),
    createdAt: str = Form(...),
    duration: float = Form(0.0),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    # Validate users
    sender = db.query(UserDB).filter(UserDB.id == senderId).first()
    if not sender:
        raise HTTPException(status_code=404, detail="Sender not found")
    if not db.query(UserDB).filter(UserDB.id == recipientId).first():
        raise HTTPException(status_code=404, detail="Recipient not found")
    # Save file with extension based on content type
    ct = (file.content_type or '').lower()
    ext = '.webm'
    if 'mp4' in ct or 'm4a' in ct:
        ext = '.m4a'
    elif 'mpeg' in ct or ct.endswith('/mp3'):
        ext = '.mp3'
    elif 'ogg' in ct or 'opus' in ct:
        ext = '.ogg'
    safe_name = f"{id}{ext}"
    out_path = Path("uploads/voice") / safe_name
    with open(out_path, "wb") as f:
        f.write(file.file.read())
    # Create message row
    msg = MessageDB(
        id=id,
        sender_id=senderId,
        recipient_id=recipientId,
        ciphertext="",  # not used for voice
        iv="",
        createdAt=date_parser.parse(createdAt),
        delivered=True,
        readAt=None,
        audioUrl=f"/uploads/voice/{safe_name}",
        audioDuration=duration,
    )
    db.add(msg)
    db.commit()
    return {"success": True, "audioUrl": msg.audioUrl, "audioDuration": msg.audioDuration}
