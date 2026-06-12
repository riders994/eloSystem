import psycopg2
from psycopg2.extras import execute_values
import pandas as pd
from typing import List


def upsert_dataframe(
    conn: psycopg2.extensions.connection,
    df: pd.DataFrame,
    table: str,
    match_columns: List[str],
    schema: str = "public",
) -> int:
    """
    Upsert rows from a DataFrame into a Postgres table.

    Rows where all `match_columns` values match an existing row are updated.
    Rows with no match are inserted.

    Args:
        conn:           An open psycopg2 connection.
        df:             DataFrame whose columns match the target table.
        table:          Target table name.
        match_columns:  Columns used to identify existing rows (i.e. the conflict target).
        schema:         Postgres schema (default: "public").

    Returns:
        Number of rows processed.

    Raises:
        ValueError: If `match_columns` contains columns not present in the DataFrame.
        psycopg2.Error: On any database error; the connection is not closed by this function.
    """
    if df.empty:
        return 0

    missing = set(match_columns) - set(df.columns)
    if missing:
        raise ValueError(f"match_columns not found in DataFrame: {missing}")

    all_columns = list(df.columns)
    update_columns = [c for c in all_columns if c not in match_columns]

    if not update_columns:
        raise ValueError(
            "All DataFrame columns are in match_columns — nothing to update."
        )

    # Quoted identifiers guard against reserved words and mixed-case names.
    def quote(name: str) -> str:
        return f'"{name}"'

    qualified_table = f"{quote(schema)}.{quote(table)}"
    col_list = ", ".join(quote(c) for c in all_columns)
    conflict_target = ", ".join(quote(c) for c in match_columns)
    update_set = ", ".join(
        f"{quote(c)} = EXCLUDED.{quote(c)}" for c in update_columns
    )

    sql = f"""
        INSERT INTO {qualified_table} ({col_list})
        VALUES %s
        ON CONFLICT ({conflict_target})
        DO UPDATE SET {update_set}
    """

    # Convert to a list of plain tuples; NaN → None so psycopg2 maps to NULL.
    records = [
        tuple(None if pd.isna(v) else v for v in row)
        for row in df.itertuples(index=False, name=None)
    ]

    with conn.cursor() as cur:
        execute_values(cur, sql, records)
    conn.commit()

    return len(records)