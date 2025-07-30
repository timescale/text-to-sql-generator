import atexit
from dotenv import load_dotenv
import json
import os
from pgai.semantic_catalog.gen_sql import fetch_database_context_alt
import psycopg
from psycopg.errors import Diagnostic
from typing import Any


load_dotenv()

con = psycopg.connect(os.environ.get("DB_URL"))
atexit.register(con.close)


def diag_to_dict(diagnostic: Diagnostic) -> dict[str, Any]:
    d = {
        "result": "the query produced an error",
        "severity": diagnostic.severity,
        "severity_nonlocalized": diagnostic.severity_nonlocalized,
        "sqlstate": diagnostic.sqlstate,
        "message_primary": diagnostic.message_primary,
        "message_detail": diagnostic.message_detail,
        "message_hint": diagnostic.message_hint,
        "statement_position": diagnostic.statement_position,
        "internal_position": diagnostic.internal_position,
        "internal_query": diagnostic.internal_query,
        "context": diagnostic.context,
        "schema_name": diagnostic.schema_name,
        "table_name": diagnostic.table_name,
        "column_name": diagnostic.column_name,
        "datatype_name": diagnostic.datatype_name,
        "constraint_name": diagnostic.constraint_name,
        "source_file": diagnostic.source_file,
        "source_line": diagnostic.source_line,
        "source_function": diagnostic.source_function,
    }
    return {k: v for k, v in d.items() if v is not None}


def execute_query(query: str) -> tuple[str, bool]:
    query = query.rstrip(";")
    with con.cursor() as cursor:
        try:
            cursor.execute(f"""select json_agg(to_json(x)) from ({query}) x""")
            return json.dumps(cursor.fetchone()[0]), True
        except psycopg.Error as err:
            con.rollback()
            return json.dumps(diag_to_dict(err.diag)), False


async def get_schema_description() -> str:
    async with await psycopg.AsyncConnection.connect(os.environ.get("DB_URL")) as conn:
        ctx = await fetch_database_context_alt(conn, conn, 1, None, None, None)
        return "\n".join(
            list(ctx.rendered_objects.values())
            + list(ctx.rendered_facts.values())
            + list(ctx.rendered_sql_examples.values())
        )


def get_results(
    query: str,
) -> tuple[None | list[dict[str, Any]], None | dict[str, Any]]:
    with con.cursor() as cur:
        query = query.rstrip("; \n")
        try:
            cur.execute(f"""
                with x as ({query})
                select json_agg(to_json(x))
                from (select * from x limit 10) x
            """)
            return cur.fetchone()[0], None
        except psycopg.Error as err:
            return None, diag_to_dict(err.diag)
