import base64
import os

from sqlalchemy import Column, String, Boolean, Integer, Float, JSON, select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.orm import sessionmaker, declarative_base

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
    session_token = Column(String(200), nullable=True, unique=True)
    is_admin = Column(Boolean)

class Product(Base):
    __tablename__ = 'products'
    product_id = Column(String(50), primary_key=True, unique=True)
    name = Column(String(100))
    description = Column(String)
    category = Column(String(100))
    size = Column(String(100))
    default_image_id = Column(String(50))
    archived = Column(Boolean)
    draft = Column(Boolean)

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

# Lokalni "cache" sessionov, da ne potrebujemo vedno znova zahtevati uporabnika od podatkovne baze
sessions: dict[str, User] = {}

async def get_session_user(session_token: str | None) -> User | None:
    if session_token == "" or session_token is None:
        return None

    # Pogledamo v cache, če je uporabnik že tam
    if sessions.get(session_token) is not None:
        return sessions.get(session_token)

    # Uporabnika torej ni v cachu, pogledamo v podatkovno bazo
    async with connection.begin() as session:
        result = (await session.execute(select(User).filter_by(session_token=session_token))).one_or_none()
        if result is None:
            # Takega uporabnika ni v podatkovni bazi
            return None
        else:
            result = result[0]

        # Uporabnik je v podatkovni bazi, dodajmo ga v cache
        sessions[session_token] = result

    return result

def random_session_token() -> str:
    return base64.b64encode(os.urandom(64)).decode()
