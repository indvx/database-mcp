# MySQL MCP Server

A Model Context Protocol (MCP) server providing safe, read-only database exploration tools for LLM agents over HTTP streaming. Built with FastMCP, wrapped in FastAPI for cloud-ready deployments, and powered by SQLAlchemy connection pooling with pre-ping validation and SSL support.

---

## Features

- **Streamable HTTP Transport**: Implements the modern MCP Streamable HTTP transport over ASGI, mounted at `/mcp`.
- **FastAPI Integration & Cloud Ready**: Wrapped in a FastAPI application (`main.py`) with a dedicated `/health` endpoint for cloud orchestrators and zero-config deployment on FastAPI Cloud.
- **Resilient Connection Pooling**: Uses SQLAlchemy `create_engine` with `pool_pre_ping=True` to eliminate stale connection drops (`2006: MySQL server has gone away`) and `READ COMMITTED` isolation level for fresh reads.
- **SSL / Cloud Database Ready**: Supports CA certificate configuration for secure cloud MySQL databases (AWS RDS, PlanetScale, Aiven, Azure).
- **Sensitive Field Protection**: Automatically redacts sensitive database columns (passwords, tokens, api keys, secrets, hashes) so they are never leaked into the model context window.
- **Token Budget Protection**: Heavy columns (BLOBs, long texts, identity document uploads, social links) are excluded by default in `list_records`, with text fields truncated unless explicitly requested.
- **Case-Insensitive Table and Column Discovery**: Normalizes MySQL metadata to handle varying casing in agent queries.

---

## Available MCP Tools

| Tool Name | Description | Key Parameters |
|---|---|---|
| `count_tables` | Returns the total number of tables in the configured database schema. | *None* |
| `get_table_names` | Discovers table names with optional search filtering and pagination. | `search` (optional str), `limit` (int, max 100) |
| `get_fields` | Retrieves non-sensitive column names for a specific table. | `table` (str) |
| `list_records` | Queries records with pagination, ordering, and optional column selection. | `table` (str), `field` (optional str), `value` (optional), `fields` (optional list/str), `limit` (default 15, max 20), `offset` (default 0), `desc` (bool) |
| `count_records_table` | Counts total or matching rows in a table. Handles boolean/tinyint status values (e.g., active=1, inactive=0). | `table` (str), `field` (optional str), `value` (optional) |

---

## Project Structure

```text
.
├── main.py                   # FastAPI application entrypoint with lifespan & health check
├── database.py               # SQLAlchemy Engine with pool_pre_ping, SessionLocal, get_db, get_conn
├── core/
│   └── config.py             # Pydantic Settings loading environment variables
├── mcp_module/
│   ├── server.py             # FastMCP server definition and tool implementations
│   └── client.py             # Async test client for verifying tool calls over HTTP streaming
├── requirements.txt          # Python dependencies
├── .env.example              # Template for environment variables
└── README.md                 # Project documentation
```

---

## Requirements

- Python 3.10+
- MySQL Server (5.7+, 8.0+, or cloud-managed MySQL such as RDS, PlanetScale, Aiven)

---

## Setup & Installation

### 1. Set Up Virtual Environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Environment Variables

Copy `.env.example` to `.env` and fill in your database credentials:

```bash
cp .env.example .env
```

Edit `.env`:

```env
# Database connection settings
DB_CONNECTION='mysql+pymysql'
DB_HOST="localhost"
DB_PORT="3306"
DB_USER="root"
DB_PASSWORD="your_password"
DB_DATABASE="your_database_name"
DB_POOL_SIZE=5

# SSL Configuration (for cloud databases like RDS, PlanetScale, Aiven)
DB_SSL_MODE="disable"
# DB_SSL_KEY=
# DB_SSL_CA_PATH="ca.pem"

# FastMCP Server Configuration
MCP_HOST="0.0.0.0"
MCP_PORT=8001
MCP_SERVER_URL="http://localhost:8001/mcp"
```

---

## Running the Server Locally

### Option A: Using FastAPI CLI (Recommended)

```bash
fastapi dev main.py --port 8001
```

### Option B: Using Uvicorn Directly

```bash
uvicorn main:app --host 0.0.0.0 --port 8001 --reload
```

### Liveness Check

Verify that the server and database connection are operational:

```bash
curl http://localhost:8001/health
```

Expected response:
```json
{
  "status": "healthy",
  "database_connected": true
}
```

---

## Running the Test Client

Run the test client to verify MCP tool discovery and sample queries:

```bash
python mcp_module/client.py
```

To run against a remote or cloud deployment, specify `MCP_SERVER_URL`:

```bash
MCP_SERVER_URL="https://your-cloud-domain.fastapi.cloud/mcp" python mcp_module/client.py
```

---

## Deploying to FastAPI Cloud

### 1. Prerequisites for Cloud Deployment

- Ensure your MySQL database is accessible over the network from the cloud (e.g., AWS RDS, PlanetScale, DigitalOcean Managed Database, or Aiven). `localhost` will not work inside a cloud container.
- If your database requires SSL, set `DB_SSL_MODE="enable"` and provide `DB_SSL_KEY` or the CA certificate.

### 2. Configure Environment Variables in FastAPI Cloud

Set the following environment variables in your FastAPI Cloud project settings:
- `DB_CONNECTION`: `mysql+pymysql`
- `DB_HOST`
- `DB_PORT`: `3306`
- `DB_USER`
- `DB_PASSWORD`
- `DB_DATABASE`
- `DB_POOL_SIZE`: `5`
- `DB_SSL_MODE`: `enable` (if required)

### 3. Deploy

Deploy using the FastAPI CLI:

```bash
fastapi deploy
```

FastAPI Cloud will automatically:
1. Detect `main.py` and the `app` instance.
2. Install dependencies from `requirements.txt`.
3. Provision an HTTPS endpoint with scale-to-zero capability.
4. Route MCP client requests to `https://<your-app>.fastapi.cloud/mcp`.
