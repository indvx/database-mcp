from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker
import os
import ssl
import logging
from core.config import settings

# Setup basic logger to capture SSL warnings in FastAPI Cloud
logger = logging.getLogger(__name__)

# Build the database connection string from environment variables
SQLALCHEMY_DATABASE_URL = "{}://{}:{}@{}:{}/{}".format(
    settings.db_connection.strip(),
    settings.db_user.strip(),
    settings.db_password.strip(),
    settings.db_host.strip(),      # <--- This fixes the [Errno -2] DNS error!
    str(settings.db_port).strip(),
    settings.db_database.strip(),
)

ssl_context = None

if settings.db_ssl_mode == 'enable':
    ca_cert_content = settings.db_ssl_key
    
    if not ca_cert_content:
        raise ValueError("DB_SSL_KEY environment variable is missing or empty!")
        
    # Clean up whitespace and escaped newlines from the cloud dashboard
    ca_cert_content = ca_cert_content.replace("\\n", "\n").strip()
    
    ssl_context = ssl.create_default_context()
    
    try:
        # Attempt strict validation using the provided string
        ssl_context.load_verify_locations(cadata=ca_cert_content)
        ssl_context.check_hostname = True
        ssl_context.verify_mode = ssl.CERT_REQUIRED
        logger.info("Successfully loaded strict SSL certificate for Aiven.")
    except ssl.SSLError as e:
        # Catch the "no start line" formatting error so the app survives
        logger.warning(f"Failed to parse DB_SSL_KEY: {e}. Falling back to unverified encrypted SSL.")
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"ssl": ssl_context} if ssl_context else {},
    pool_pre_ping=True,
    pool_recycle=3600
)

# Factory for creating new database sessions per request
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

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