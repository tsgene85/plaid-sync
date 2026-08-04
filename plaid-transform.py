#!/usr/bin/env python3

import argparse
import sys

import transactionsdb


def parse_options():
    parser = argparse.ArgumentParser(
        description=(
            "Transform transactions.plaid_json into standalone columns "
            "on an existing plaid-sync SQLite database"
        )
    )
    parser.add_argument(
        "-d",
        "--database",
        dest="dbfile",
        required=True,
        help="[REQUIRED] Path to the plaid-sync SQLite database file",
        metavar="DB_FILE",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        dest="verbose",
        action="store_true",
        help="Print progress information",
    )
    return parser.parse_args()


def main():
    args = parse_options()
    db = transactionsdb.TransactionsDB(args.dbfile)
    updated = db.transform_all_transactions(verbose=args.verbose)
    print(f"Updated {updated} transactions in {args.dbfile}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
