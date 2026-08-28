"""
اتصال به دیتابیس (SQLite) + Session + تابع init_db (اجباری - تغییر ندهید).
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

import config

DATABASE_URL = f"sqlite:///{config.DB_PATH}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def init_db() -> None:
    """
    ساخت تمام جدول‌های دیتابیس در صورت عدم وجود.
    این تابع باید هنگام استارت main.py فراخوانی شود.
    """
    from database import models  # noqa: F401  (اطمینان از ثبت مدل‌ها روی Base)

    Base.metadata.create_all(bind=engine)


def get_session():
    """یک Session جدید SQLAlchemy برمی‌گرداند. بستن آن بر عهده‌ی فراخواننده است."""
    return SessionLocal()
