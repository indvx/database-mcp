from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker, scoped_session
import os
from core.config import settings
import ssl

# Build the database connection string from environment variables
SQLALCHEMY_DATABASE_URL = "{}://{}:{}@{}:{}/{}".format(
    settings.db_connection,
    settings.db_user,
    settings.db_password,
    settings.db_host,
    settings.db_port,
    settings.db_database,
)
connect_args = {}
ssl_context=None
ca_cert_content = settings.db_ssl_key if settings.db_ssl_key else None
if settings.db_ssl_mode == 'enable':
    if ca_cert_content:
        ca_cert_content = ca_cert_content.replace("\\n", "\n")
        ssl_context = ssl.create_default_context()
        # Load the certificate directly from string data (no file needed!)
        ssl_context.load_verify_locations(cadata=ca_cert_content)
        ssl_context.check_hostname = True
        ssl_context.verify_mode = ssl.CERT_REQUIRED
    else:
        raise ValueError("db_ssl_key environment variable is missing or empty!")

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"ssl": ssl_context} if ssl_context else {},
    pool_pre_ping=True,
    pool_recycle=3600
)

# Factory for creating new database sessions per request
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
# SessionLocal = scoped_session(SessionLocal)
Base = declarative_base()


# FastAPI dependency that provides a clean DB session per request and closes it after
def get_db():
    """Yields a database session and guarantees closure upon request completion."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_engine():
    """Returns the shared SQLAlchemy Engine."""
    return engine


def get_conn():
    """Retrieves a DBAPI connection from the SQLAlchemy engine pool with pre-ping validation."""
    return engine.raw_connection()


def get_cursor(conn, dictionary: bool = False):
    """Returns a cursor compatible with both PyMySQL and MySQL Connector drivers."""
    if dictionary:
        try:
            return conn.cursor(dictionary=True)
        except TypeError:
            import pymysql.cursors
            return conn.cursor(pymysql.cursors.DictCursor)
    return conn.cursor()
