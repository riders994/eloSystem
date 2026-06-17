import re
import psycopg2

import pandas as pd

from typing import List, Any
from psycopg2.extras import execute_values
from urllib.parse import urlparse, urlunparse

from ..basics.constants import APPROVED_SQL_FLAVORS, WEEK_STR


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
    If all columns are match columns, conflicting rows are skipped (DO NOTHING).

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

    def quote(name: str) -> str:
        return f'"{name}"'

    qualified_table = f"{quote(schema)}.{quote(table)}"
    col_list = ", ".join(quote(c) for c in all_columns)
    conflict_target = ", ".join(quote(c) for c in match_columns)

    if update_columns:
        update_set = ", ".join(
            f"{quote(c)} = EXCLUDED.{quote(c)}" for c in update_columns
        )
        conflict_action = f"DO UPDATE SET {update_set}"
    else:
        conflict_action = "DO NOTHING"

    sql = f"""
        INSERT INTO {qualified_table} ({col_list})
        VALUES %s
        ON CONFLICT ({conflict_target})
        {conflict_action}
    """

    records = [
        tuple(None if pd.isna(v) else v for v in row)
        for row in df.itertuples(index=False, name=None)
    ]

    with conn.cursor() as cur:
        execute_values(cur, sql, records)
    conn.commit()

    return len(records)

def fstr_matcher(fstr: str, ext: str) -> tuple[str, re.Pattern]:
    """Turn a filename format string into a glob pattern and a regex that
    captures the `{num}` field, so written files can be discovered and
    their season key recovered on load."""
    glob = fstr.format(num='*', ext=ext)
    pattern = (
        re.escape(fstr)
        .replace(re.escape('{num}'), r'(?P<num>.+?)')
        .replace(re.escape('{ext}'), re.escape(ext))
    )
    return glob, re.compile('^' + pattern + '$')

def uri_to_dict(uri: str) -> dict[str, Any]:
    p = urlparse(uri)
    return {
        'dbname': p.path[1:],
        'user': p.username,
        'password': p.password,
        'port': p.port,
        'host': p.hostname
    }


def dict_to_uri(credentials: dict[str, str], dialect: str = "postgresql") -> str:
    """
    Convert a credentials dictionary back into a database URI string.

    Args:
        credentials: Dictionary with keys 'dbname', 'user', 'password', 'port', 'host'
        dialect: Database dialect (default: 'postgresql')

    Returns:
        A database URI string
    """

    netloc = (
        f"{credentials.get('user', '')}:{credentials.get('password', '')}"
        f"@{credentials.get('host', 'localhost')}:{credentials.get('port', 5432)}"
    )
    path = f"/{credentials.get('dbname', '')}"

    return urlunparse((dialect, netloc, path, '', '', ''))

def validate_conn_dict(v: dict[str, Any]) -> bool:
    if v.get('dbname') is None:
        return False
    if v.get('user') is None:
        return False
    if v.get('password') is None:
        return False
    if v.get('port') is None:
        return False
    if v.get('host') is None:
        return False
    if v.get('dialect') not in APPROVED_SQL_FLAVORS:
        return False

    return True

def score_pivot(df: pd.DataFrame) -> pd.DataFrame:
    """Reshape a wide score table into long (tidy) form.

    Input is a table like those in the ratings directory: rows indexed by
    league member, one column per week (``week_0``, ``week_1`` ...), and the
    score in each cell. The result has one row per populated cell, with
    columns ``member``, ``week`` (the integer week number) and ``rating``.

    Args:
        df:          Wide elo table (member index, ``week_{n}`` columns).

    Returns:
        Long-form DataFrame with columns ``member``, ``week``, ``rating``,
        sorted by member then week. Empty cells (NaN) are dropped.
    """
    week_prefix = WEEK_STR.format('')
    week_cols = [c for c in df.columns if str(c).startswith(week_prefix)]

    member_col = df.index.name or 'member'
    long = (
        df[week_cols]
        .rename_axis(member_col)
        .reset_index()
        .melt(id_vars=member_col, var_name='week', value_name='rating')
        .rename(columns={member_col: 'member'})
    )
    long['week'] = long['week'].str.removeprefix(week_prefix).astype(int)
    long = long.dropna(subset=['rating'])

    return long.sort_values(['member', 'week']).reset_index(drop=True)

def score_unpivot(df: pd.DataFrame) -> pd.DataFrame:
    """Reverse of ``score_pivot``: rebuild a wide ratings table from long form.

    Input is a tidy frame with columns ``member``, ``week`` and ``rating``,
    exactly as produced by ``score_pivot``. The result is indexed by member
    with one column per week (``week_0``, ``week_1`` ...) and the rating in
    each cell, matching the layout of the files in the ratings directory.
    Weeks missing for a given member come back as NaN.

    Args:
        df:  Long-form frame with ``member``, ``week``, ``rating`` columns.

    Returns:
        Wide DataFrame indexed by member with ascending ``week_{n}`` columns.
    """
    wide = df.pivot(index='member', columns='week', values='rating')
    wide.columns = [WEEK_STR.format(w) for w in wide.columns]
    # Match the original frames, whose member index carries no name.
    return wide.rename_axis(None)
