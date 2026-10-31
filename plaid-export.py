#!/usr/bin/env python3
"""Export selected SQLite columns to CSV using config/CSVExportConfig.yaml."""

import argparse
import csv
import os
import re
import sqlite3
import sys
from typing import Any, Dict, List, Optional

import yaml

import transactionsdb

IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
ORDER_BY = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)(?:\s+(asc|desc))?$", re.IGNORECASE)

DEFAULT_EXPORT_CONFIG = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "config", "CSVExportConfig.yaml"
)

SAMPLE_EXPORT_CONFIG = """\
# Columns written by plaid-export.py, in this order.
# Add, remove, or reorder names to change the CSV.
# A name must already exist on the SQLite table.
# Set enabled: false to skip a table.

tables:
  transactions:
    enabled: true
    file: transactions.csv
    # Omit rows that plaid-sync has marked archived.
    exclude_archived: true
    order_by:
      - date desc
      - transaction_id asc
    columns:
      - date
      - name
      - merchant_name
      - amount
      - iso_currency_code
      - pending
      - payment_channel
      - category
      - pfc_primary
      - pfc_detailed
      - account_id
      - transaction_id

  balances:
    enabled: false
    file: balances.csv
    order_by:
      - date desc
      - account_id asc
    columns:
      - date
      - account_id
      - account_type
      - balance_current
      - balance_available
      - balance_limit
      - currency_code
"""


def parse_options():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Export SQLite tables to CSV. Columns, order, and which tables "
            "are written come from a YAML config (default: the transactions table)."
        ),
        epilog="""\
examples:
  uv run python .\\plaid-export.py -e .\\config\\CSVExportConfig.yaml -ce
  uv run python .\\plaid-export.py -d .\\sandbox.db -e .\\config\\CSVExportConfig.yaml
  uv run python .\\plaid-export.py -d .\\sandbox.db -e .\\config\\CSVExportConfig.yaml -o .\\transactions.csv
  uv run python .\\plaid-export.py -d .\\sandbox.db -t transactions
""",
    )
    parser.add_argument(
        "-d",
        "--database",
        dest="dbfile",
        help="Path to the plaid-sync SQLite database (required unless -ce)",
        metavar="DB_FILE",
    )
    parser.add_argument(
        "-e",
        "--export-config",
        dest="export_config",
        default=DEFAULT_EXPORT_CONFIG,
        help="YAML file listing tables and columns to export",
        metavar="YAML_FILE",
    )
    parser.add_argument(
        "-ce",
        "--create-export-config",
        dest="create_export_config",
        action="store_true",
        help="Write a sample YAML export config to the path given by -e, then exit",
    )
    parser.add_argument(
        "-o",
        "--output",
        dest="output",
        default=".",
        help=(
            "Directory for the CSV files, or a .csv path when exporting one table. "
            "Defaults to the current directory."
        ),
        metavar="PATH",
    )
    parser.add_argument(
        "-t",
        "--table",
        dest="tables",
        action="append",
        help="Export only this table (repeatable). Must be enabled in the YAML.",
        metavar="TABLE",
    )
    return parser.parse_args()


def write_sample_export_config(path: str) -> None:
    if os.path.exists(path):
        raise ValueError(f"Refusing to overwrite existing file: {path}")
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(SAMPLE_EXPORT_CONFIG)


def load_export_config(path: str) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict) or not isinstance(data.get("tables"), dict):
        raise ValueError(f"{path} must contain a top-level 'tables' mapping")
    return data


def quote_ident(name: str) -> str:
    if not IDENTIFIER.match(name):
        raise ValueError(f"Invalid SQL identifier: {name!r}")
    return '"' + name.replace('"', '""') + '"'


def table_columns(conn: sqlite3.Connection, table: str) -> List[str]:
    if not IDENTIFIER.match(table):
        raise ValueError(f"Invalid table name: {table!r}")
    rows = conn.execute(f"pragma table_info({quote_ident(table)})").fetchall()
    if not rows:
        raise ValueError(f"Table {table!r} does not exist")
    return [row[1] for row in rows]


def parse_order_by(specs: Optional[List[str]], available: set) -> str:
    if not specs:
        return ""
    parts = []
    for spec in specs:
        if not isinstance(spec, str):
            raise ValueError(f"order_by entries must be strings, got {spec!r}")
        match = ORDER_BY.match(spec.strip())
        if not match:
            raise ValueError(
                f"Invalid order_by {spec!r}; use 'column' or 'column desc'"
            )
        column, direction = match.group(1), (match.group(2) or "asc").upper()
        if column not in available:
            raise ValueError(f"order_by column {column!r} is not on the table")
        parts.append(f"{quote_ident(column)} {direction}")
    return " order by " + ", ".join(parts)


def select_tables(config: Dict[str, Any], only: Optional[List[str]]) -> Dict[str, Any]:
    tables = config["tables"]
    if only:
        missing = [name for name in only if name not in tables]
        if missing:
            raise ValueError(
                "Unknown table(s) in --table: "
                + ", ".join(missing)
                + ". Known: "
                + ", ".join(tables)
            )
        selected = {name: tables[name] for name in only}
    else:
        selected = {
            name: spec
            for name, spec in tables.items()
            if isinstance(spec, dict) and spec.get("enabled", True)
        }
    if not selected:
        raise ValueError("No tables selected for export")
    return selected


def output_path(output: str, table: str, spec: Dict[str, Any], table_count: int) -> str:
    filename = spec.get("file") or f"{table}.csv"
    if not isinstance(filename, str) or not filename.strip():
        raise ValueError(f"Table {table!r} has an invalid file name")
    if os.path.isdir(output) or (table_count > 1 and not output.lower().endswith(".csv")):
        os.makedirs(output, exist_ok=True)
        return os.path.join(output, os.path.basename(filename))
    if table_count == 1 and output.lower().endswith(".csv"):
        parent = os.path.dirname(output)
        if parent:
            os.makedirs(parent, exist_ok=True)
        return output
    os.makedirs(output, exist_ok=True)
    return os.path.join(output, os.path.basename(filename))


def export_table(
    conn: sqlite3.Connection,
    table: str,
    spec: Dict[str, Any],
    dest: str,
) -> int:
    if not isinstance(spec, dict):
        raise ValueError(f"Table {table!r} config must be a mapping")
    columns = spec.get("columns")
    if not isinstance(columns, list) or not columns:
        raise ValueError(f"Table {table!r} needs a non-empty columns list")

    available = table_columns(conn, table)
    available_set = set(available)
    unknown = [col for col in columns if col not in available_set]
    if unknown:
        hint = ""
        if table == "transactions" and any(
            col in transactionsdb.TRANSFORM_COLUMNS for col in unknown
        ):
            hint = " Run plaid-transform.py to add flattened transaction columns."
        raise ValueError(
            f"Table {table!r} has no column(s): {', '.join(unknown)}.{hint}"
        )

    where = ""
    if spec.get("exclude_archived"):
        if "archived" not in available_set:
            raise ValueError(f"Table {table!r} has no archived column")
        where = " where archived is null"

    order = parse_order_by(spec.get("order_by"), available_set)
    sql = (
        "select "
        + ", ".join(quote_ident(col) for col in columns)
        + f" from {quote_ident(table)}{where}{order}"
    )

    cursor = conn.execute(sql)
    count = 0
    with open(dest, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        for row in cursor:
            writer.writerow(row)
            count += 1
    return count


def export_database(
    dbfile: str,
    export_config: str,
    output: str,
    only: Optional[List[str]] = None,
) -> Dict[str, int]:
    config = load_export_config(export_config)
    selected = select_tables(config, only)
    conn = sqlite3.connect(dbfile)
    try:
        written = {}
        for table, spec in selected.items():
            dest = output_path(output, table, spec, len(selected))
            written[dest] = export_table(conn, table, spec, dest)
        return written
    finally:
        conn.close()


def main():
    args = parse_options()
    if args.create_export_config:
        try:
            write_sample_export_config(args.export_config)
        except (OSError, ValueError) as exc:
            print(f"Could not create export config: {exc}", file=sys.stderr)
            return 1
        print(f"Wrote sample export config to {args.export_config}")
        return 0

    if not args.dbfile:
        print("Export failed: -d/--database is required", file=sys.stderr)
        return 1

    try:
        written = export_database(
            args.dbfile, args.export_config, args.output, args.tables
        )
    except (OSError, ValueError, yaml.YAMLError, sqlite3.Error) as exc:
        print(f"Export failed: {exc}", file=sys.stderr)
        return 1

    for path, count in written.items():
        print(f"Wrote {count} rows to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
