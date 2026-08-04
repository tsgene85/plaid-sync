#!python3

import sqlite3
import json
import datetime

from typing import Any, Dict, List

from plaidapi import AccountBalance, AccountInfo, Transaction as PlaidTransaction


def build_placeholders(list):
    return ",".join(["?"] * len(list))


# Columns extracted from transactions.plaid_json into first-class fields.
# Keys are SQLite column names; values document the source for readability.
TRANSFORM_COLUMNS = [
    "date",
    "authorized_date",
    "datetime",
    "authorized_datetime",
    "name",
    "merchant_name",
    "amount",
    "iso_currency_code",
    "unofficial_currency_code",
    "pending",
    "pending_transaction_id",
    "payment_channel",
    "transaction_type",
    "transaction_code",
    "category",
    "category_id",
    "pfc_primary",
    "pfc_detailed",
    "pfc_confidence",
    "website",
    "logo_url",
    "check_number",
    "account_owner",
    "merchant_entity_id",
    "location_address",
    "location_city",
    "location_region",
    "location_postal_code",
    "location_country",
    "location_lat",
    "location_lon",
    "location_store_number",
    "payment_meta",
    "counterparties",
]


def extract_transaction_fields(data: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten a Plaid transaction JSON object into standalone column values."""
    location = data.get("location") or {}
    pfc = data.get("personal_finance_category") or {}
    category = data.get("category")
    payment_meta = data.get("payment_meta")
    counterparties = data.get("counterparties")
    pending = data.get("pending")

    return {
        "date": data.get("date"),
        "authorized_date": data.get("authorized_date"),
        "datetime": data.get("datetime"),
        "authorized_datetime": data.get("authorized_datetime"),
        "name": data.get("name"),
        "merchant_name": data.get("merchant_name"),
        "amount": data.get("amount"),
        "iso_currency_code": data.get("iso_currency_code"),
        "unofficial_currency_code": data.get("unofficial_currency_code"),
        "pending": None if pending is None else (1 if pending else 0),
        "pending_transaction_id": data.get("pending_transaction_id"),
        "payment_channel": data.get("payment_channel"),
        "transaction_type": data.get("transaction_type"),
        "transaction_code": data.get("transaction_code"),
        "category": json.dumps(category) if category is not None else None,
        "category_id": data.get("category_id"),
        "pfc_primary": pfc.get("primary"),
        "pfc_detailed": pfc.get("detailed"),
        "pfc_confidence": pfc.get("confidence_level"),
        "website": data.get("website"),
        "logo_url": data.get("logo_url"),
        "check_number": data.get("check_number"),
        "account_owner": data.get("account_owner"),
        "merchant_entity_id": data.get("merchant_entity_id"),
        "location_address": location.get("address"),
        "location_city": location.get("city"),
        "location_region": location.get("region"),
        "location_postal_code": location.get("postal_code"),
        "location_country": location.get("country"),
        "location_lat": location.get("lat"),
        "location_lon": location.get("lon"),
        "location_store_number": location.get("store_number"),
        "payment_meta": json.dumps(payment_meta) if payment_meta is not None else None,
        "counterparties": (
            json.dumps(counterparties) if counterparties is not None else None
        ),
    }


class TransactionsDB:
    def __init__(self, dbfile: str, transform_json: bool = False):
        self.conn = sqlite3.connect(dbfile, timeout=30)
        self.conn.execute("PRAGMA busy_timeout = 30000")
        self.transform_json = transform_json

        c = self.conn.cursor()
        c.execute("""
            create table if not exists transactions
                (account_id, transaction_id, created, updated, archived, plaid_json)
            """)
        c.execute(
            "create unique index if not exists accounts_idx     ON transactions(account_id, transaction_id)"
        )
        c.execute(
            "create unique index if not exists transactions_idx ON transactions(transaction_id)"
        )

        c.execute("""
            create table if not exists balances
                (date, item_id, account_id, account_type, balance_current, balance_available, balance_limit, currency_code, updated, plaid_json)
        """)
        c.execute(
            "create unique index if not exists balances_idx ON balances(item_id, account_id, date)"
        )

        c.execute("""
            create table if not exists items
                (item_id, institution_id, consent_expiration, last_failed_update, last_successful_update, updated, plaid_json, cursor)
        """)
        c.execute("create unique index if not exists items_idx ON items(item_id)")

        self.conn.commit()

        if self.transform_json:
            self.ensure_transform_columns()

        # This might be needed if there's not consistent support for json_extract in sqlite3 installations
        # this will need to be modified to support the "$.prop" syntax
        # def json_extract(json_str, prop):
        #    ret = json.loads(json_str).get(prop, None)
        #    return ret
        # self.conn.create_function("json_extract", 2, json_extract)

    def existing_columns(self, table: str) -> set:
        c = self.conn.cursor()
        return {row[1] for row in c.execute(f"pragma table_info({table})").fetchall()}

    def ensure_transform_columns(self):
        """Add standalone transaction columns derived from plaid_json if missing."""
        existing = self.existing_columns("transactions")
        c = self.conn.cursor()
        for column in TRANSFORM_COLUMNS:
            if column not in existing:
                c.execute(f"alter table transactions add column {column}")
        self.conn.commit()
        self.transform_json = True

    def transform_all_transactions(self, verbose: bool = False) -> int:
        """
        Ensure transform columns exist and populate them for every transaction
        from its plaid_json blob. Returns the number of rows updated.
        """
        self.ensure_transform_columns()
        c = self.conn.cursor()
        rows = c.execute(
            "select rowid, plaid_json from transactions where plaid_json is not null"
        ).fetchall()

        update_cols = ", ".join(f"{col} = ?" for col in TRANSFORM_COLUMNS)
        sql = f"update transactions set {update_cols} where rowid = ?"

        updated = 0
        for rowid, plaid_json in rows:
            fields = extract_transaction_fields(json.loads(plaid_json))
            values = [fields[col] for col in TRANSFORM_COLUMNS] + [rowid]
            c.execute(sql, values)
            updated += 1

        self.conn.commit()
        if verbose:
            print(f"Transformed {updated} transactions")
        return updated

    def datetime_handler(self, obj):
        if isinstance(obj, (datetime.datetime, datetime.date)):
            return obj.isoformat()
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

    def get_transaction_ids(
        self, start_date: datetime.date, end_date: datetime.date, account_ids: List[str]
    ) -> List[str]:
        c = self.conn.cursor()
        res = c.execute(
            """
                select transaction_id from transactions
                where json_extract(plaid_json, '$.date') between ? and ?
                and account_id in ({PARAMS})
                and archived is null
            """.replace("{PARAMS}", build_placeholders(account_ids)),
            [start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")]
            + list(account_ids),
        )
        return [r[0] for r in res.fetchall()]

    def archive_transactions(self, transaction_ids: List[str]):
        c = self.conn.cursor()
        c.execute(
            """
                update transactions set archived = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
                where archived is null
                and transaction_id in ({PARAMS})
                """.replace("{PARAMS}", build_placeholders(transaction_ids)),
            list(transaction_ids),
        )

        self.conn.commit()

    def save_transaction(self, transaction: PlaidTransaction):
        c = self.conn.cursor()
        data = json.dumps(transaction.raw_data, default=self.datetime_handler)

        if self.transform_json:
            fields = extract_transaction_fields(transaction.raw_data)
            columns = (
                ["account_id", "transaction_id", "created", "updated", "archived", "plaid_json"]
                + TRANSFORM_COLUMNS
            )
            placeholders = [
                "?",
                "?",
                "strftime('%Y-%m-%dT%H:%M:%SZ', 'now')",
                "strftime('%Y-%m-%dT%H:%M:%SZ', 'now')",
                "null",
                "?",
            ] + ["?"] * len(TRANSFORM_COLUMNS)
            update_assignments = [
                "updated = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')",
                "plaid_json = excluded.plaid_json",
            ] + [f"{col} = excluded.{col}" for col in TRANSFORM_COLUMNS]
            sql = f"""
                insert into transactions({", ".join(columns)})
                values({", ".join(placeholders)})
                on conflict(account_id, transaction_id) DO UPDATE
                    set {", ".join(update_assignments)}
            """
            values = (
                [transaction.account_id, transaction.transaction_id, data]
                + [fields[col] for col in TRANSFORM_COLUMNS]
            )
            c.execute(sql, values)
        else:
            c.execute(
                """
                insert into
                    transactions(account_id, transaction_id, created, updated, archived, plaid_json)
                    values(?,?,strftime('%Y-%m-%dT%H:%M:%SZ', 'now'),strftime('%Y-%m-%dT%H:%M:%SZ', 'now'),null,?)
                    on conflict(account_id, transaction_id) DO UPDATE
                        set updated    = strftime('%Y-%m-%dT%H:%M:%SZ', 'now'),
                            plaid_json = excluded.plaid_json
            """,
                [transaction.account_id, transaction.transaction_id, data],
            )

        self.conn.commit()

    def save_item_info(self, item_info: AccountInfo):
        c = self.conn.cursor()

        data = json.dumps(item_info.raw_data, default=self.datetime_handler)
        c.execute(
            """
            insert into
                items(item_id, institution_id, consent_expiration, last_failed_update, last_successful_update, updated, plaid_json)
                values(?,?,?,?,?,strftime('%Y-%m-%dT%H:%M:%SZ', 'now'),?)
                on conflict(item_id) DO UPDATE
                    set updated    = strftime('%Y-%m-%dT%H:%M:%SZ', 'now'),
                    institution_id = excluded.institution_id,
                    consent_expiration = excluded.consent_expiration,
                    last_failed_update = excluded.last_failed_update,
                    last_successful_update = excluded.last_successful_update,
                    plaid_json = excluded.plaid_json
        """,
            [
                item_info.item_id,
                item_info.institution_id,
                item_info.ts_consent_expiration,
                item_info.ts_last_failed_update,
                item_info.ts_last_successful_update,
                data,
            ],
        )

        self.conn.commit()

    def save_balance(self, item_id: str, balance: AccountBalance):
        c = self.conn.cursor()

        data = json.dumps(balance.raw_data, default=self.datetime_handler)
        c.execute(
            """
            insert into
                balances(date, item_id, account_id, account_type, balance_current, balance_available, balance_limit, currency_code, updated, plaid_json)
                values(strftime('%Y-%m-%d', 'now'),?,?,?,?,?,?,?,strftime('%Y-%m-%dT%H:%M:%SZ', 'now'), ?)
                on conflict(item_id, account_id, date) DO UPDATE
                    set updated    = strftime('%Y-%m-%dT%H:%M:%SZ', 'now'),
                        account_type = excluded.account_type,
                        balance_current = excluded.balance_current,
                        balance_available = excluded.balance_available,
                        balance_limit = excluded.balance_limit,
                        currency_code = excluded.currency_code,
                        plaid_json = excluded.plaid_json
        """,
            [
                item_id,
                balance.account_id,
                balance.account_type,
                balance.balance_current,
                balance.balance_available,
                balance.balance_limit,
                balance.currency_code,
                data,
            ],
        )

        self.conn.commit()

    def fetch_transactions_by_id(
        self, transaction_ids: List[str]
    ) -> List[PlaidTransaction]:
        c = self.conn.cursor()
        r = c.execute(
            """
            select plaid_json from transactions
            where transaction_id in ({PARAMS})
        """.replace("{PARAMS}", build_placeholders(transaction_ids)),
            list(transaction_ids),
        )
        return [PlaidTransaction(json.loads(d[0])) for d in r.fetchall()]

    def get_last_sync_cursor(self, item_id):
        """
        Retrieve the last sync cursor for a given item_id.
        Returns None if no cursor exists (indicating initial sync needed).
        """
        c = self.conn.cursor()
        cursor = c.execute(
            "SELECT cursor FROM items WHERE item_id = ?", (item_id,)
        ).fetchone()

        if cursor and cursor[0]:
            return cursor[0]
        return None

    def save_sync_cursor(self, item_id, cursor):
        """
        Save the sync cursor for a given item_id.
        Updates the existing item record with the new cursor.
        """
        c = self.conn.cursor()
        c.execute("UPDATE items SET cursor = ? WHERE item_id = ?", (cursor, item_id))
        self.conn.commit()
