from __future__ import annotations

from sqlalchemy.orm import scoped_session, sessionmaker

from twtw.session import engine

SessionLocal = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
