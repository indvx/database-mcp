import sys
import os
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional, Union

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from core.config import settings
from database import get_conn, get_cursor, get_engine


load_dotenv()

MCP_HOST = settings.mcp_host
MCP_PORT = settings.mcp_port
MYSQL_DATABASE = settings.db_database


mcp = FastMCP(
    "mysql-test",
    host=MCP_HOST,
    port=MCP_PORT,
)


MAX_RECORD_LIMIT = 20
MAX_TABLE_LIMIT = 100

# Never expose sensitive columns like credentials or tokens to the LLM agent
SENSITIVE_FIELDS = {
    "password",
    "password_hash",
    "token",
    "access_token",
    "refresh_token",
    "secret",
    "api_key",
    "private_key",
}

# Heavy columns and data types excluded by default in list_records to save token budget
HEAVY_FIELDS = {
    "encrypted_blob",
    "public_key",
    "private_key",
    "resume",
    "profile",
    "about_me",
    "aadhar_card_file",
    "pan_card_file",
    "driving_license_file",
    "reset_token",
    "reset_expires_at",
    "facebook_url",
    "twitter_url",
    "linkedin_url",
    "instagram_url",
    "upwork_profile_url",
    "frontend_skills",
    "backend_skills",
    "address_line1",
    "address_line2",
    "bank_address",
    "emergency_contact1",
    "emergency_contact2",
    "emergency_contact3",
    "aadhar_card_number",
    "pan_card_number",
    "driving_license_number",
    "account_number",
    "ifsc_code",
}

HEAVY_DATA_TYPES = {
    "blob",
    "longblob",
    "mediumblob",
    "tinyblob",
    "longtext",
    "mediumtext",
}

def serialize_row(row: dict) -> dict:
    """Converts database values into JSON-serializable primitives and handles length limits."""
    serialized = {}
    for key, val in row.items():
        if isinstance(val, (datetime, date)):
            serialized[key] = val.isoformat()
        elif isinstance(val, timedelta):
            # Format timedelta (MySQL TIME columns) as HH:MM:SS
            total_seconds = int(val.total_seconds())
            hours, remainder = divmod(total_seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            serialized[key] = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        elif isinstance(val, Decimal):
            serialized[key] = float(val)
        elif isinstance(val, bytes):
            decoded = val.decode("utf-8", errors="replace")
            serialized[key] = decoded[:120] + "..." if len(decoded) > 120 else decoded
        elif isinstance(val, str):
            # Preserve rich text bodies (reports, messages, descriptions) up to 2000 chars; truncate metadata at 120
            max_len = 2000 if key.lower() in ("report", "content", "body", "message", "text", "notes", "note", "description") else 120
            serialized[key] = val[:max_len] + "..." if len(val) > max_len else val
        else:
            serialized[key] = val
    return serialized


def success_response(data):
    """Wraps data in standard MCP success response format."""
    return {
        "success": True,
        "data": data,
    }


def error_response(message, **kwargs):
    """Wraps error message in standard MCP error response format."""
    return {
        "success": False,
        "error": message,
        **kwargs,
    }


def table_exists(table: str) -> bool:
    """Check whether a table exists in the configured database."""

    conn = get_conn()
    cur = get_cursor(conn)

    try:
        cur.execute(
            """
            SELECT COUNT(*)
            FROM information_schema.tables
            WHERE table_schema = %s
              AND LOWER(table_name) = LOWER(%s)
            """,
            (
                MYSQL_DATABASE,
                table,
            ),
        )

        return cur.fetchone()[0] > 0

    finally:
        cur.close()
        conn.close()


def validate_table(table: str):
    """Validate table without returning the entire table list. This prevents large MCP responses."""

    if table_exists(table):
        return None

    return error_response(f"Table '{table}' does not exist.")


def get_actual_table_name(table: str) -> Optional[str]:
    """Return the actual table name from MySQL. Useful for case-insensitive table matching."""

    conn = get_conn()
    cur = get_cursor(conn)

    try:
        cur.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = %s
              AND LOWER(table_name) = LOWER(%s)
            LIMIT 1
            """,
            (
                MYSQL_DATABASE,
                table,
            ),
        )

        result = cur.fetchone()

        return result[0] if result else None

    finally:
        cur.close()
        conn.close()


def get_table_fields_raw(table: str):
    """Internal helper. Returns normalized field information from MySQL."""

    conn = get_conn()
    cur = get_cursor(conn, dictionary=True)

    try:
        cur.execute(
            """
            SELECT
                COLUMN_NAME,
                DATA_TYPE,
                IS_NULLABLE,
                COLUMN_KEY
            FROM information_schema.columns
            WHERE table_schema = %s
              AND table_name = %s
            ORDER BY ORDINAL_POSITION
            """,
            (
                MYSQL_DATABASE,
                table,
            ),
        )

        rows = cur.fetchall()

        # Normalize MySQL column names
        fields = []

        for row in rows:
            fields.append(
                {
                    "column_name": row["COLUMN_NAME"],
                    "data_type": row["DATA_TYPE"],
                    "is_nullable": row["IS_NULLABLE"],
                    "column_key": row["COLUMN_KEY"],
                }
            )

        return fields

    finally:
        cur.close()
        conn.close()


def find_field_info(
    available_fields: list[dict],
    requested_field: str,
) -> Optional[dict]:
    """Find field metadata case-insensitively."""
    requested_field = requested_field.lower()

    for field in available_fields:
        if field["column_name"].lower() == requested_field:
            return field

    return None


def find_field(
    available_fields: list[dict],
    requested_field: str,
) -> Optional[str]:
    """Find a field case-insensitively."""
    info = find_field_info(available_fields, requested_field)
    return info["column_name"] if info else None


def build_filter_condition(
    field_info: dict,
    value: Union[str, int, float, bool],
) -> tuple[str, list]:
    """Builds SQL WHERE clause handling boolean/tinyint mappings and text matching."""
    field_name = field_info["column_name"]
    data_type = field_info.get("data_type", "").lower()

    # Normalize boolean and tinyint flags to exact numeric matches
    if data_type in ("tinyint", "boolean"):
        val_str = str(value).strip().lower()
        if val_str in ("1", "true", "yes", "active", "enabled"):
            return f"`{field_name}` = %s", [1]
        if val_str in ("0", "false", "no", "inactive", "disabled"):
            return f"`{field_name}` = %s", [0]
        if val_str.isdigit():
            return f"`{field_name}` = %s", [int(val_str)]

    return f"`{field_name}` LIKE %s", [f"%{value}%"]


@mcp.tool(
    description=(
        "Count total tables in the database. "
        "ALWAYS use this tool when the user asks how many tables are in the database."
    )
)
def count_tables():
    """Count total tables in the database."""
    conn = get_conn()
    cur = get_cursor(conn)

    try:
        cur.execute(
            """
            SELECT COUNT(*)
            FROM information_schema.tables
            WHERE table_schema = %s
            """,
            (MYSQL_DATABASE,),
        )
        total = cur.fetchone()[0]

        return success_response(
            {
                "database": MYSQL_DATABASE,
                "count": total,
            }
        )

    except Exception as e:
        print(f"Error counting tables: {e}", file=sys.stderr)
        return error_response(f"Error counting tables: {e}")

    finally:
        cur.close()
        conn.close()


@mcp.tool(
    description=(
        "Find database tables by name. "
        "Returns table names and total table count. "
        "Use this when discovering tables or searching for specific tables by name."
    )
)
def get_table_names(
    search: Optional[str] = None,
    limit: int = MAX_TABLE_LIMIT,
):
    """Find tables in the database. Examples: get_table_names() get_table_names(search="employee") get_table_names(search="user")"""

    conn = get_conn()
    cur = get_cursor(conn)

    try:
        limit = min(
            max(limit or 1, 1),
            MAX_TABLE_LIMIT,
        )

        query = """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = %s
        """

        params = [MYSQL_DATABASE]

        if search:
            query += """
                AND LOWER(table_name) LIKE LOWER(%s)
            """

            params.append(f"%{search}%")

        query += """
            ORDER BY table_name
            LIMIT %s
        """

        params.append(limit)

        cur.execute(query, params)

        tables = [row[0] for row in cur.fetchall()]

        # Query total count matching criteria so the agent knows the true total table count
        count_query = """
            SELECT COUNT(*)
            FROM information_schema.tables
            WHERE table_schema = %s
        """
        count_params = [MYSQL_DATABASE]
        if search:
            count_query += " AND LOWER(table_name) LIKE LOWER(%s)"
            count_params.append(f"%{search}%")

        cur.execute(count_query, count_params)
        total_count = cur.fetchone()[0]

        return success_response(
            {
                "total_tables": total_count,
                "count": len(tables),
                "tables": tables,
            }
        )

    except Exception as e:
        print(
            f"Error getting tables: {e}",
            file=sys.stderr,
        )

        return error_response(f"Error getting tables: {e}")

    finally:
        cur.close()
        conn.close()


@mcp.tool(
    description=(
        "Get the fields/columns of a specific database table. "
        "Use this after identifying the correct table."
    )
)
def get_fields(table: str):
    """Get columns of a table."""

    try:
        actual_table = get_actual_table_name(table)

        if not actual_table:
            return error_response(f"Table '{table}' does not exist.")

        fields = get_table_fields_raw(actual_table)

        # Return lightweight column names to avoid bloating schema discovery tokens
        field_names = [
            field["column_name"]
            for field in fields
            if field["column_name"].lower() not in SENSITIVE_FIELDS
        ]

        return success_response(
            {
                "table": actual_table,
                "count": len(field_names),
                "fields": field_names,
            }
        )

    except Exception as e:
        print(
            f"Error getting fields: {e}",
            file=sys.stderr,
        )

        return error_response(f"Error getting fields: {e}")


@mcp.tool(
    description=(
        "List records from a database table. "
        "Returns up to 15 records per request. "
        "For boolean/tinyint status columns, 1 represents active/true and 0 represents inactive/false. "
        "When querying wide tables, ALWAYS specify 'fields' with only key summary columns (e.g. id, first_name, last_name, email, role, status) to prevent context token overflow. "
        "Never use limit > 20. "
        "Do not request all pages in a single turn unless explicitly requested by the user. "
        "IMPORTANT: Do NOT use list_records to count how many records or rows exist in a table; use count_records_table instead. The 'count' field here is only the count of records returned in this page, not total table rows."
    )
)
def list_records(
    table: str,
    field: Optional[str] = None,
    value: Optional[Union[str, int, float, bool]] = None,
    fields: Optional[Union[list[str], str]] = None,
    limit: int = 15,
    offset: int = 0,
    desc: bool = False,
):
    try:

        actual_table = get_actual_table_name(table)

        if not actual_table:
            return error_response(f"Table '{table}' does not exist.")

        available_fields = get_table_fields_raw(actual_table)

        if not available_fields:
            return error_response(f"No fields found for table '{actual_table}'.")

        available_field_names = [
            field_data["column_name"] for field_data in available_fields
        ]

        if fields:

            # Allow model to pass either a list ["col1", "col2"] or a string "col1" / "col1, col2"
            if isinstance(fields, str):
                fields = [f.strip() for f in fields.split(",") if f.strip()]

            selected_fields = []
            invalid_fields = []

            for requested_field in fields:

                actual_field = find_field(
                    available_fields,
                    requested_field,
                )

                if not actual_field:
                    invalid_fields.append(requested_field)
                    continue

                # Strip sensitive credentials so the LLM cannot see them
                if actual_field.lower() in SENSITIVE_FIELDS:
                    continue

                selected_fields.append(actual_field)

            if invalid_fields:
                return error_response(
                    f"Fields not found in table "
                    f"'{actual_table}': "
                    f"{', '.join(invalid_fields)}",
                    available_fields=[
                        field_name
                        for field_name in available_field_names
                        if field_name.lower() not in SENSITIVE_FIELDS
                    ],
                )

            if not selected_fields:
                return error_response("No valid fields were selected.")

        else:

            # Default to compact summary columns, excluding heavy blobs, files, and verbose details
            selected_fields = [
                field_data["column_name"]
                for field_data in available_fields
                if field_data["column_name"].lower() not in SENSITIVE_FIELDS
                and field_data["column_name"].lower() not in HEAVY_FIELDS
                and field_data["data_type"].lower() not in HEAVY_DATA_TYPES
                and not field_data["column_name"].lower().endswith(("_file", "_blob", "_image", "_token"))
            ]

            # Fallback to all non-sensitive columns if everything was filtered out
            if not selected_fields:
                selected_fields = [
                    field_data["column_name"]
                    for field_data in available_fields
                    if field_data["column_name"].lower() not in SENSITIVE_FIELDS
                ]

        matched_field_info = None

        if field:

            matched_field_info = find_field_info(
                available_fields,
                field,
            )

            if not matched_field_info:
                return error_response(
                    f"Field '{field}' not found " f"in table '{actual_table}'.",
                    available_fields=[
                        field_name
                        for field_name in available_field_names
                        if field_name.lower() not in SENSITIVE_FIELDS
                    ],
                )

            matched_field = matched_field_info["column_name"]

            if matched_field.lower() in SENSITIVE_FIELDS:
                return error_response(
                    f"Searching by field " f"'{matched_field}' is not allowed."
                )

        order_field = find_field(
            available_fields,
            "id",
        )

        if not order_field:

            if matched_field_info:
                order_field = matched_field_info["column_name"]

            elif selected_fields:
                order_field = selected_fields[0]

        direction = "DESC" if desc else "ASC"

        columns = ", ".join(f"`{column}`" for column in selected_fields)

        query = f"SELECT {columns} " f"FROM `{actual_table}`"

        params = []

        if matched_field_info and value is not None:

            where_sql, where_params = build_filter_condition(
                matched_field_info,
                value,
            )
            query += f" WHERE {where_sql}"
            params.extend(where_params)

        if order_field:

            query += f" ORDER BY `{order_field}` " f"{direction}"

        limit = min(max(limit or 1, 1), MAX_RECORD_LIMIT)
        offset = max(offset or 0, 0)

        # Request limit + 1 so we can check if there are more records without a separate COUNT(*)
        query += " LIMIT %s OFFSET %s"
        params.append(limit + 1)
        params.append(offset)

        conn = get_conn()
        cur = get_cursor(conn, dictionary=True)

        try:
            cur.execute(query, tuple(params))

            rows = cur.fetchall()

            has_more = len(rows) > limit

            rows = rows[:limit]
            serialized_rows = [serialize_row(row) for row in rows]

            next_offset = offset + limit if has_more else None

            return success_response(
                {
                    "table": actual_table,
                    "count": len(serialized_rows),
                    "offset": offset,
                    "limit": limit,
                    "has_more": has_more,
                    "next_offset": next_offset,
                    "data": serialized_rows,
                }
            )

        finally:
            cur.close()
            conn.close()

    except Exception as e:

        print(
            f"Error listing records: {e}",
            file=sys.stderr,
        )

        return error_response(f"Error listing records: {e}")


@mcp.tool(
    description=(
        "Count total records or rows in a database table. "
        "ALWAYS use this tool when the user asks 'how many records', 'how many rows', 'total count', or to count matching items in a table. "
        "Use field and value when counting matching records. "
        "For boolean/tinyint status columns, 1 represents active/true and 0 represents inactive/false."
    )
)
def count_records_table(
    table: str,
    field: Optional[str] = None,
    value: Optional[Union[str, int, float, bool]] = None,
):
    """Count records in a table."""

    try:
        actual_table = get_actual_table_name(table)

        if not actual_table:
            return error_response(f"Table '{table}' does not exist.")

        available_fields = get_table_fields_raw(actual_table)

        matched_field_info = None

        if field:

            matched_field_info = find_field_info(
                available_fields,
                field,
            )

            if not matched_field_info:
                return error_response(
                    f"Field '{field}' not found " f"in table '{actual_table}'.",
                    available_fields=[
                        item["column_name"]
                        for item in available_fields
                        if item["column_name"].lower() not in SENSITIVE_FIELDS
                    ],
                )

            matched_field = matched_field_info["column_name"]

            if matched_field.lower() in SENSITIVE_FIELDS:
                return error_response(
                    f"Searching by field " f"'{matched_field}' is not allowed."
                )

        if matched_field_info and value is not None:

            where_sql, where_params = build_filter_condition(
                matched_field_info,
                value,
            )
            query = (
                f"SELECT COUNT(*) "
                f"FROM `{actual_table}` "
                f"WHERE {where_sql}"
            )
            params = where_params

        else:

            query = f"SELECT COUNT(*) " f"FROM `{actual_table}`"

            params = []

        conn = get_conn()
        cur = get_cursor(conn)

        try:
            cur.execute(
                query,
                params,
            )

            count = cur.fetchone()[0]

            return success_response(
                {
                    "table": actual_table,
                    "count": count,
                }
            )

        finally:
            cur.close()
            conn.close()

    except Exception as e:

        print(
            f"Error counting records: {e}",
            file=sys.stderr,
        )

        return error_response(f"Error counting records: {e}")


@mcp.tool(
    description=(
        "Search records in a database table by keyword, person's name, or search phrase. "
        "ALWAYS use this tool when looking up an individual person, employee, user, or entity by name (e.g. 'Gourav Panchal', 'Panchal', 'Gourav', 'Admin'). "
        "This is a strictly READ-ONLY search operation that executes a SELECT query. It cannot modify or delete data. "
        "Intelligently searches full names (handling first and last names together), phonetic variations (Soundex for alternate spellings like Gaurav/Gourav), emails, and text fields. "
        "Returns the most relevant matching records directly in a single call."
    )
)
def search_records(
    table: str,
    search_term: Optional[str] = None,
    query: Optional[str] = None,
    fields: Optional[Union[list[str], str]] = None,
    limit: int = 10,
):
    """Search records in a table by keyword or entity name. Read-only SELECT operation."""
    try:
        actual_table = get_actual_table_name(table)
        if not actual_table:
            return error_response(f"Table '{table}' does not exist.")

        raw_query = search_term if search_term is not None else query
        clean_query = (raw_query or "").strip()
        if not clean_query:
            return error_response("Search term cannot be empty.")

        available_fields = get_table_fields_raw(actual_table)
        if not available_fields:
            return error_response(f"No fields found for table '{actual_table}'.")

        available_field_names = [f["column_name"] for f in available_fields]
        available_field_names_lower = {f["column_name"].lower(): f["column_name"] for f in available_fields}

        # Resolve selected fields
        if fields:
            if isinstance(fields, str):
                fields = [f.strip() for f in fields.split(",") if f.strip()]
            selected_fields = []
            for rf in fields:
                act = find_field(available_fields, rf)
                if act and act.lower() not in SENSITIVE_FIELDS:
                    selected_fields.append(act)
            if not selected_fields:
                selected_fields = [
                    f["column_name"] for f in available_fields
                    if f["column_name"].lower() not in SENSITIVE_FIELDS
                    and f["column_name"].lower() not in HEAVY_FIELDS
                    and f["data_type"].lower() not in HEAVY_DATA_TYPES
                ]
        else:
            selected_fields = [
                f["column_name"] for f in available_fields
                if f["column_name"].lower() not in SENSITIVE_FIELDS
                and f["column_name"].lower() not in HEAVY_FIELDS
                and f["data_type"].lower() not in HEAVY_DATA_TYPES
                and not f["column_name"].lower().endswith(("_file", "_blob", "_image", "_token"))
            ]
            if not selected_fields:
                selected_fields = [
                    f["column_name"] for f in available_fields
                    if f["column_name"].lower() not in SENSITIVE_FIELDS
                ]

        tokens = [t.strip() for t in clean_query.split() if t.strip()]

        has_first_name = "first_name" in available_field_names_lower
        has_last_name = "last_name" in available_field_names_lower

        first_name_col = available_field_names_lower.get("first_name")
        last_name_col = available_field_names_lower.get("last_name")

        # Discover string/text columns to search
        text_types = {"varchar", "char", "text", "tinytext", "mediumtext"}
        searchable_cols = [
            f["column_name"] for f in available_fields
            if f["data_type"].lower() in text_types
            and f["column_name"].lower() not in SENSITIVE_FIELDS
            and f["column_name"].lower() not in HEAVY_FIELDS
            and not f["column_name"].lower().endswith(("_file", "_blob", "_image", "_token"))
        ]

        where_clauses = []
        where_params = []
        rank_cases = []
        rank_params = []

        # Name search logic with phonetic/soundex tolerance
        if has_first_name and has_last_name:
            fn = f"`{first_name_col}`"
            ln = f"`{last_name_col}`"

            if len(tokens) >= 2:
                t1, t2 = tokens[0], tokens[1]
                name_clause = (
                    f"(CONCAT(COALESCE({fn}, ''), ' ', COALESCE({ln}, '')) LIKE %s "
                    f"OR (({fn} LIKE %s OR SOUNDEX({fn}) = SOUNDEX(%s)) AND ({ln} LIKE %s OR SOUNDEX({ln}) = SOUNDEX(%s))) "
                    f"OR (({ln} LIKE %s OR SOUNDEX({ln}) = SOUNDEX(%s)) AND ({fn} LIKE %s OR SOUNDEX({fn}) = SOUNDEX(%s))))"
                )
                where_clauses.append(name_clause)
                where_params.extend([
                    f"%{clean_query}%",
                    f"%{t1}%", t1, f"%{t2}%", t2,
                    f"%{t1}%", t1, f"%{t2}%", t2,
                ])

                rank_cases.append(f"WHEN CONCAT(COALESCE({fn}, ''), ' ', COALESCE({ln}, '')) LIKE %s THEN 1")
                rank_params.append(f"%{clean_query}%")
                rank_cases.append(
                    f"WHEN (({fn} LIKE %s OR SOUNDEX({fn}) = SOUNDEX(%s)) AND ({ln} LIKE %s OR SOUNDEX({ln}) = SOUNDEX(%s))) THEN 2"
                )
                rank_params.extend([f"%{t1}%", t1, f"%{t2}%", t2])

            else:
                t = tokens[0]
                name_clause = (
                    f"({fn} LIKE %s OR SOUNDEX({fn}) = SOUNDEX(%s) OR {ln} LIKE %s OR SOUNDEX({ln}) = SOUNDEX(%s))"
                )
                where_clauses.append(name_clause)
                where_params.extend([f"%{t}%", t, f"%{t}%", t])

                rank_cases.append(f"WHEN {fn} = %s OR {ln} = %s THEN 1")
                rank_params.extend([t, t])
                rank_cases.append(f"WHEN {fn} LIKE %s OR {ln} LIKE %s THEN 2")
                rank_params.extend([f"%{t}%", f"%{t}%"])
                rank_cases.append(f"WHEN SOUNDEX({fn}) = SOUNDEX(%s) OR SOUNDEX({ln}) = SOUNDEX(%s) THEN 3")
                rank_params.extend([t, t])

        # Also search across other candidate text columns (e.g. email, code, username, title, name)
        other_cols = [c for c in searchable_cols if c.lower() not in ("first_name", "last_name")]
        for col in other_cols[:6]:
            where_clauses.append(f"`{col}` LIKE %s")
            where_params.append(f"%{clean_query}%")

        if not where_clauses:
            return error_response(f"No searchable text columns found in table '{actual_table}'.")

        limit = min(max(limit or 1, 1), MAX_RECORD_LIMIT)
        columns_sql = ", ".join(f"`{c}`" for c in selected_fields)
        where_sql = " OR ".join(where_clauses)

        order_by_sql = ""
        final_params = list(where_params)
        if rank_cases:
            order_by_sql = f"ORDER BY (CASE {' '.join(rank_cases)} ELSE 99 END) ASC"
            final_params.extend(rank_params)

        final_params.append(limit)

        query_sql = f"SELECT {columns_sql} FROM `{actual_table}` WHERE {where_sql} {order_by_sql} LIMIT %s"

        conn = get_conn()
        cur = get_cursor(conn, dictionary=True)
        try:
            cur.execute(query_sql, tuple(final_params))
            rows = cur.fetchall()
            serialized_rows = [serialize_row(row) for row in rows]
            return success_response({
                "table": actual_table,
                "query": clean_query,
                "count": len(serialized_rows),
                "data": serialized_rows,
            })
        finally:
            cur.close()
            conn.close()

    except Exception as e:
        print(f"Error searching records: {e}", file=sys.stderr)
        return error_response(f"Error searching records: {e}")


app = mcp.streamable_http_app()
