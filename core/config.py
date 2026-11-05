from typing import Optional
from pydantic import Field, AliasChoices
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment or .env file."""

    # Server settings
    mcp_host: str = Field(default="0.0.0.0", validation_alias=AliasChoices("mcp_host", "MCP_HOST"))
    mcp_port: int = Field(default=8001, validation_alias=AliasChoices("mcp_port", "MCP_PORT"))

    # Database settings
    db_connection: str = Field(default="mysql+pymysql", validation_alias=AliasChoices("db_connection", "DB_CONNECTION"))
    db_host: str = Field(default="localhost", validation_alias=AliasChoices("db_host", "DB_HOST", "MYSQL_HOST"))
    db_port: int = Field(default=3306, validation_alias=AliasChoices("db_port", "DB_PORT", "MYSQL_PORT"))
    db_user: str = Field(default="root", validation_alias=AliasChoices("db_user", "DB_USER", "MYSQL_USER"))
    db_password: str = Field(default="", validation_alias=AliasChoices("db_password", "DB_PASSWORD", "MYSQL_PASSWORD"))
    db_database: str = Field(default="", validation_alias=AliasChoices("db_database", "DB_DATABASE", "db_name", "MYSQL_DATABASE"))
    db_pool_size: int = Field(default=5, validation_alias=AliasChoices("db_pool_size", "DB_POOL_SIZE", "MYSQL_POOL_SIZE"))

    # SSL settings
    db_ssl_mode: str = Field(default="disable", validation_alias=AliasChoices("db_ssl_mode", "DB_SSL_MODE"))
    db_ssl_key: Optional[str] = Field(default=None, validation_alias=AliasChoices("db_ssl_key", "DB_SSL_KEY"))
    db_ssl_ca_path: str = Field(default="ca.pem", validation_alias=AliasChoices("db_ssl_ca_path", "DB_SSL_CA_PATH"))

    # Direct database URL override
    database_url: Optional[str] = Field(default=None, validation_alias=AliasChoices("database_url", "DATABASE_URL"))

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
