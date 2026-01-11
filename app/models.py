from datetime import datetime

from sqlalchemy import JSON

from app.extensions import db


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    name = db.Column(db.String(160))
    profile_image = db.Column(db.String(255))
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class UserLinkedAccount(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    owner_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    x_user_id = db.Column(db.String(64), nullable=False)
    username = db.Column(db.String(80), nullable=False)
    name = db.Column(db.String(160))
    profile_image = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (db.UniqueConstraint("owner_user_id", "x_user_id", name="uq_owner_x"),)


class UserOAuthToken(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    owner_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    x_user_id = db.Column(db.String(64), nullable=False)
    access_token = db.Column(db.Text, nullable=False)
    refresh_token = db.Column(db.Text)
    expires_at = db.Column(db.DateTime)
    scope = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (db.UniqueConstraint("owner_user_id", "x_user_id", name="uq_token_owner_x"),)


class Item(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(160), nullable=False)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AppVar(db.Model):
    __tablename__ = "app_vars"
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(190), unique=True, nullable=False)
    value = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ApiRequestLog(db.Model):
    __tablename__ = "api_request_logs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True, index=True)
    method = db.Column(db.String(10), nullable=False)
    url = db.Column(db.Text, nullable=False)
    status_code = db.Column(db.Integer)
    response_body = db.Column(db.Text)
    response_headers = db.Column(JSON)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class XUser(db.Model):
    __tablename__ = "x_users"

    id = db.Column(db.BigInteger, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False)
    description = db.Column(db.Text)
    location = db.Column(db.String(150))
    url = db.Column(db.String(500))
    profile_image_url = db.Column(db.String(500))
    verified = db.Column(db.Boolean, default=False)
    verified_type = db.Column(db.String(30))

    followers_count = db.Column(db.Integer, default=0)
    following_count = db.Column(db.Integer, default=0)
    post_count = db.Column(db.Integer, default=0)
    listed_count = db.Column(db.Integer, default=0)
    like_count = db.Column(db.Integer, default=0)
    media_count = db.Column(db.Integer, default=0)

    pinned_post_id = db.Column(db.BigInteger, db.ForeignKey("x_posts.id"), nullable=True)
    most_recent_post_id = db.Column(db.BigInteger, nullable=True)

    raw_profile_data = db.Column(JSON, nullable=False, default=dict)

    last_updated_at = db.Column(
        db.DateTime(timezone=True),
        server_default=db.func.now(),
        onupdate=db.func.now(),
    )


class XPost(db.Model):
    __tablename__ = "x_posts"

    id = db.Column(db.BigInteger, primary_key=True)
    author_id = db.Column(db.BigInteger, db.ForeignKey("x_users.id"), nullable=False, index=True)
    text = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, index=True)
    lang = db.Column(db.String(10))
    possibly_sensitive = db.Column(db.Boolean, default=False)
    reply_settings = db.Column(db.String(30))
    conversation_id = db.Column(db.BigInteger, index=True)

    repost_count = db.Column(db.Integer, default=0)
    reply_count = db.Column(db.Integer, default=0)
    like_count = db.Column(db.Integer, default=0)
    quote_count = db.Column(db.Integer, default=0)
    bookmark_count = db.Column(db.Integer, default=0)
    impression_count = db.Column(db.Integer, default=0)

    in_reply_to_post_id = db.Column(db.BigInteger, db.ForeignKey("x_posts.id"), nullable=True)

    raw_post_data = db.Column(JSON, nullable=False, default=dict)

    author = db.relationship("XUser", backref="posts", foreign_keys=[author_id])


class AnnotationDomain(db.Model):
    __tablename__ = "annotation_domains"

    id = db.Column(db.String(20), primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text)


class AnnotationEntity(db.Model):
    __tablename__ = "annotation_entities"

    id = db.Column(db.String(50), primary_key=True)
    name = db.Column(db.String(255), nullable=False, index=True)
    description = db.Column(db.Text)


class PostContextAnnotation(db.Model):
    __tablename__ = "post_context_annotations"

    post_id = db.Column(db.BigInteger, db.ForeignKey("x_posts.id"), primary_key=True)
    domain_id = db.Column(db.String(20), db.ForeignKey("annotation_domains.id"), primary_key=True)
    entity_id = db.Column(db.String(50), db.ForeignKey("annotation_entities.id"), primary_key=True)

    post = db.relationship("XPost", backref="context_annotations")
    domain = db.relationship("AnnotationDomain")
    entity = db.relationship("AnnotationEntity")
