import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8001/mcp")


# Simple test script to verify that the FastMCP server is responding over HTTP streaming
async def main():
    """Connects to the FastMCP server, lists tools, and executes sample queries."""
    print(f"[INFO] Connecting to MCP server at: {SERVER_URL}")
    async with streamable_http_client(SERVER_URL) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            # Verify which tools are discovered
            tools = await session.list_tools()
            print(f"Available tools: {[tool.name for tool in tools.tools]}")

            # Test count tool on the users table
            print("count available database tables...")
            result = await session.call_tool("count_records_table", arguments={"table": "users"})
            print("tables:", result.content)

            # Test list tool on the users table
            print("Example: list records from a table")
            result = await session.call_tool("list_records", arguments={"table": "users"})
            print("records:", result.content)


if __name__ == "__main__":
    asyncio.run(main())
