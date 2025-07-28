import atexit
from dotenv import load_dotenv
import json
import os
import psycopg
from psycopg.errors import Diagnostic
from typing import Any


load_dotenv()

con = psycopg.connect(os.environ.get("DB_URL"))
atexit.register(con.close)
with con.cursor() as cur:
    for key in ["anthropic_api_key", "openai_api_key"]:
        cur.execute(
            "select set_config(%s, %s, false)",
            ("ai." + key.lower(), os.environ[key.upper()]),
        )


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


def get_schema_description() -> str:
    with con.cursor() as cur:
        cur.execute("""
            select string_agg
            ( ai._render_semantic_catalog_table
                ( o.id
                , o.classid
                , o.objid
                )
            , E'\n'
            order by o.id
            )
            from ai.semantic_catalog_obj o
            where o.objtype = 'table'
        """)
        tables = cur.fetchone()[0]
        cur.execute("""
            select string_agg
            ( ai._render_semantic_catalog_view
                ( o.id
                , o.classid
                , o.objid
                )
            , E'\n'
            order by o.id
            )
            from ai.semantic_catalog_obj o
            where o.objtype = 'view'
        """)
        views = cur.fetchone()[0]
    return f"{tables}\n{views}"




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


def generate_sql(
    question: str,
) -> tuple[str, None | list[dict[str, Any]], None | dict[str, Any]]:
    with con.cursor() as cur:
        cur.execute("select ai.text_to_sql(%s)", (question,))
        query: str = cur.fetchone()[0]
    results, error = get_results(query)
    return query, results, error
