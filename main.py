import contextlib
import os
from dotenv import load_dotenv
from fastapi import FastAPI
from sqlalchemy import text
import uvicorn

load_dotenv()

from database import get_engine, get_db
from mcp_module.server import mcp, app as mcp_app


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    # Coordinate FastMCP session manager lifecycle with FastAPI
    if hasattr(mcp, "session_manager") and hasattr(mcp.session_manager, "run"):
        async with contextlib.AsyncExitStack() as stack:
            await stack.enter_async_context(mcp.session_manager.run())
            yield
    else:
        yield


app = FastAPI(
    title="MySQL MCP Server",
    description="Streamable HTTP FastMCP server providing database inspection tools",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
def health_check():
    """Health check for container probes and cloud deployment status."""
    db_connected = False
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        db_connected = True
    except Exception:
        db_connected = False

    return {
        "status": "healthy",
        "database_connected": db_connected,
    }


# Mount the streamable HTTP FastMCP app under /mcp
app.mount("/mcp", mcp_app)


if __name__ == "__main__":
    from core.config import settings
    uvicorn.run("main:app", host=settings.mcp_host, port=settings.mcp_port, reload=True)
