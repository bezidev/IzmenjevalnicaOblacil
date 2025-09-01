import base64
import os
import time

from sqlalchemy import Column, String, Boolean, Integer, Float, JSON, select, ForeignKey
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import sessionmaker, declarative_base, relationship

DATABASE_CONNECTION = f"sqlite+aiosqlite:///database/database.sqlite3"

engine = create_async_engine(DATABASE_CONNECTION)
connection = async_sessionmaker(engine, expire_on_commit=False)
Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    user_id = Column(String(50), primary_key=True, unique=True)
    email = Column(String(100), unique=True)
    first_name = Column(String(100))
    surname = Column(String(100))
    credits = Column(Integer)
    session_token = Column(String(200), nullable=True, unique=True)
    is_admin = Column(Boolean)
    is_teacher = Column(Boolean, default=False)

class Product(Base):
    __tablename__ = 'products'
    product_id = Column(String(50), primary_key=True, unique=True)
    name = Column(String(100))
    description = Column(String)
    category = Column(String(100))
    size = Column(String(100))
    color = Column(String(25))
    material = Column(String(25))
    brand = Column(String(100))
    default_image_id = Column(String(50))
    archived = Column(Boolean)
    teacher = Column(Boolean)
    limit_to_teachers = Column(Boolean)
    state = Column(Integer)
    draft = Column(Boolean)
    reserved_by_id = Column(String(50))
    reserved_date = Column(Integer)

    published_by = Column(String(50))
    published_at = Column(Integer)
    last_edited_by = Column(String(50))
    last_edited_at = Column(Integer)

class ProductImage(Base):
    __tablename__ = 'product_images'
    image_id = Column(String(50), primary_key=True, unique=True)
    description = Column(String)
    position = Column(Integer)
    product_id = Column(String(50))

class UserSession:
    def __init__(self, user: User, microsoft_token: str, microsoft_token_expiry: int):
        self.user = user
        self.microsoft_token = microsoft_token
        self.microsoft_token_expiry = microsoft_token_expiry

# Lokalni "cache" sessionov, da ne potrebujemo vedno znova zahtevati uporabnika od podatkovne baze
sessions: dict[str, UserSession] = {}

def get_session_user(session_token: str | None) -> UserSession | None:
    if session_token == "" or session_token is None:
        return None

    # Pogledamo v cache, če je uporabnik že tam
    # Če uporabnika ni v cachu, žal moramo uporabnika prisiliti v ponovno prijavo, da pridobimo nov Microsoft auth token.
    user = sessions.get(session_token)
    if user is None:
        return None

    if user.microsoft_token_expiry < time.time():
        return None
    return user

def random_session_token() -> str:
    return base64.b64encode(os.urandom(64)).decode()
