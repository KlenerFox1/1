from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import aiosqlite


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class User:
    user_id: int
    balance: float
    bonus: float
    frozen: float
    cryptobot_id: int | None


@dataclass(frozen=True)
class Request:
    request_id: int
    user_id: int
    account_type: str
    phone: str
    status: str
    is_work: int
    is_vip: int
    admin_note: str | None
    logs: str
    created_at: str


@dataclass(frozen=True)
class Withdrawal:
    withdrawal_id: int
    user_id: int
    amount: float
    net: float
    fee: float
    status: str
    cryptobot_transfer_id: str | None
    created_at: str


class Database:
    def __init__(self, db_path: str | Path) -> None:
        self._path = str(db_path)

    @staticmethod
    async def _fetchone(db: aiosqlite.Connection, sql: str, params: tuple[Any, ...] = ()) -> tuple[Any, ...] | None:
        async with db.execute(sql, params) as cur:
            return await cur.fetchone()

    @staticmethod
    async def _fetchall(db: aiosqlite.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
        async with db.execute(sql, params) as cur:
            rows = await cur.fetchall()
        return list(rows)

    async def connect(self) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.execute("PRAGMA journal_mode=WAL;")
            await db.execute("PRAGMA foreign_keys=ON;")
            await db.commit()
        await self.ensure_schema()

    async def ensure_schema(self) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.execute("PRAGMA foreign_keys=ON;")

            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    balance REAL NOT NULL DEFAULT 0,
                    bonus REAL NOT NULL DEFAULT 0,
                    frozen REAL NOT NULL DEFAULT 0,
                    cryptobot_id INTEGER,
                    created_at TEXT NOT NULL
                );
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS requests (
                    request_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    account_type TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    status TEXT NOT NULL,
                    is_work INTEGER NOT NULL DEFAULT 0,
                    is_vip INTEGER NOT NULL DEFAULT 0,
                    admin_note TEXT,
                    logs TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(user_id)
                );
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS cryptobot_invoices (
                    invoice_id TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    amount REAL NOT NULL,
                    status TEXT NOT NULL,
                    credited INTEGER NOT NULL DEFAULT 0,
                    target TEXT NOT NULL DEFAULT 'user',
                    pay_url TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(user_id)
                );
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS withdrawals (
                    withdrawal_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    amount REAL NOT NULL,
                    net REAL NOT NULL,
                    fee REAL NOT NULL,
                    status TEXT NOT NULL,
                    cryptobot_transfer_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(user_id) REFERENCES users(user_id)
                );
                """
            )
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS blacklist (
                    phone TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL
                );
                """
            )
            await db.commit()

        await self._ensure_default_settings()
        await self._ensure_migrations()

    async def _ensure_migrations(self) -> None:
        # Safe migrations for already-created DBs
        async with aiosqlite.connect(self._path) as db:
            try:
                await db.execute("ALTER TABLE cryptobot_invoices ADD COLUMN target TEXT NOT NULL DEFAULT 'user';")
                await db.commit()
            except Exception:
                pass

    async def _ensure_default_settings(self) -> None:
        if await self.get_setting("account_types") is None:
            await self.set_setting(
                "account_types",
                json.dumps(
                    [
                        {"name": "Telegram", "price": 1.0},
                        {"name": "WhatsApp", "price": 1.0},
                    ],
                    ensure_ascii=False,
                ),
            )
        if await self.get_setting("stop_accepting") is None:
            await self.set_setting("stop_accepting", "0")
        if await self.get_setting("treasury_balance") is None:
            await self.set_setting("treasury_balance", "0")
        if await self.get_setting("extra_admin_ids") is None:
            await self.set_setting("extra_admin_ids", "[]")
        if await self.get_setting("maintenance_mode") is None:
            await self.set_setting("maintenance_mode", "0")

    async def get_maintenance_mode(self) -> bool:
        raw = await self.get_setting("maintenance_mode")
        return str(raw or "0").strip() in {"1", "true", "True", "yes", "YES"}

    async def toggle_maintenance_mode(self) -> bool:
        new_val = "0" if await self.get_maintenance_mode() else "1"
        await self.set_setting("maintenance_mode", new_val)
        return await self.get_maintenance_mode()

    async def get_extra_admin_ids(self) -> list[int]:
        raw = await self.get_setting("extra_admin_ids")
        if not raw:
            return []
        try:
            v = json.loads(raw)
            if isinstance(v, list):
                out: list[int] = []
                for x in v:
                    try:
                        out.append(int(x))
                    except Exception:
                        continue
                return sorted(set(out))
        except Exception:
            return []
        return []

    async def add_extra_admin(self, admin_id: int) -> list[int]:
        ids = set(await self.get_extra_admin_ids())
        ids.add(int(admin_id))
        await self.set_setting("extra_admin_ids", json.dumps(sorted(ids)))
        return sorted(ids)

    async def remove_extra_admin(self, admin_id: int) -> list[int]:
        ids = set(await self.get_extra_admin_ids())
        ids.discard(int(admin_id))
        await self.set_setting("extra_admin_ids", json.dumps(sorted(ids)))
        return sorted(ids)

    async def is_admin(self, user_id: int, base_admin_ids: set[int]) -> bool:
        if user_id in base_admin_ids:
            return True
        extra = await self.get_extra_admin_ids()
        return user_id in set(extra)

    async def list_users(self, limit: int = 50000) -> list[User]:
        async with aiosqlite.connect(self._path) as db:
            rows = await self._fetchall(
                db,
                "SELECT user_id, balance, bonus, frozen, cryptobot_id FROM users ORDER BY user_id ASC LIMIT ?",
                (limit,),
            )
        return [
            User(
                user_id=int(r[0]),
                balance=float(r[1]),
                bonus=float(r[2]),
                frozen=float(r[3]),
                cryptobot_id=None if r[4] is None else int(r[4]),
            )
            for r in rows
        ]

    async def count_users(self) -> int:
        async with aiosqlite.connect(self._path) as db:
            row = await self._fetchone(db, "SELECT COUNT(*) FROM users")
        return int(row[0]) if row else 0

    async def request_stats(self) -> dict[str, int]:
        async with aiosqlite.connect(self._path) as db:
            rows = await self._fetchall(db, "SELECT status, COUNT(*) FROM requests GROUP BY status")
        return {str(r[0]): int(r[1]) for r in rows}

    async def blacklist_add(self, phone: str) -> None:
        now = _utcnow_iso()
        async with aiosqlite.connect(self._path) as db:
            await db.execute("INSERT OR IGNORE INTO blacklist(phone, created_at) VALUES(?,?)", (phone, now))
            await db.commit()

    async def blacklist_remove(self, phone: str) -> None:
        async with aiosqlite.connect(self._path) as db:
            await db.execute("DELETE FROM blacklist WHERE phone=?", (phone,))
            await db.commit()

    async def blacklist_list(self, limit: int = 200) -> list[str]:
        async with aiosqlite.connect(self._path) as db:
            rows = await self._fetchall(db, "SELECT phone FROM blacklist ORDER BY created_at DESC LIMIT ?", (limit,))
        return [str(r[0]) for r in rows]

    async def blacklist_contains(self, phone: str) -> bool:
        async with aiosqlite.connect(self._path) as db:
            row = await self._fetchone(db, "SELECT 1 FROM blacklist WHERE phone=? LIMIT 1", (phone,))
        return row is not None

    async def get_treasury_balance(self) -> float:
        raw = await self.get_setting("treasury_balance")
        try:
            return float(raw or 0)
        except Exception:
            return 0.0

    async def add_treasury_balance(self, amount: float) -> None:
        cur = await self.get_treasury_balance()
        new_val = cur + amount
        if new_val < 0:
            new_val = 0.0
        await self.set_setting("treasury_balance", str(new_val))

    async def can_cover_from_treasury(self, amount: float) -> bool:
        bal = await self.get_treasury_balance()
        return bal >= amount

    async def get_setting(self, key: str) -> str | None:
        async with aiosqlite.connect(self._path) as db:
            row = await self._fetchone(db, "SELECT value FROM settings WHERE key=?", (key,))
            return None if row is None else str(row[0])

    async def set_setting(self, key: str, value: str) -> None:
        now = _utcnow_iso()
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                """
                INSERT INTO settings(key, value, updated_at)
                VALUES(?,?,?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
                """,
                (key, value, now),
            )
            await db.commit()

    async def get_account_types_full(self) -> list[dict[str, Any]]:
        raw = await self.get_setting("account_types")
        if not raw:
            return []
        try:
            v = json.loads(raw)
            if isinstance(v, list):
                out: list[dict[str, Any]] = []
                for item in v:
                    if isinstance(item, dict) and "name" in item:
                        name = str(item.get("name") or "").strip()
                        if not name:
                            continue
                        try:
                            price = float(item.get("price", 0))
                        except Exception:
                            price = 0.0
                        out.append({"name": name, "price": price})
                    else:
                        # backward compatibility: plain string list
                        name = str(item).strip()
                        if not name:
                            continue
                        out.append({"name": name, "price": 0.0})
                return out
        except Exception:
            return []
        return []

    async def get_account_types(self) -> list[str]:
        full = await self.get_account_types_full()
        return [t["name"] for t in full]

    async def set_account_types(self, types_: list[dict[str, Any]]) -> None:
        cleaned: list[dict[str, Any]] = []
        for t in types_:
            name = str(t.get("name") or "").strip()
            if not name:
                continue
            try:
                price = float(t.get("price", 0))
            except Exception:
                price = 0.0
            cleaned.append({"name": name, "price": price})
        await self.set_setting("account_types", json.dumps(cleaned, ensure_ascii=False))

    async def get_account_type_price(self, name: str) -> float | None:
        name = name.strip()
        if not name:
            return None
        full = await self.get_account_types_full()
        for item in full:
            if item.get("name") == name:
                try:
                    return float(item.get("price", 0))
                except Exception:
                    return 0.0
        return None

    async def get_stop_accepting(self) -> bool:
        raw = await self.get_setting("stop_accepting")
        return str(raw or "0").strip() in {"1", "true", "True", "yes", "YES"}

    async def toggle_stop_accepting(self) -> bool:
        new_val = "0" if await self.get_stop_accepting() else "1"
        await self.set_setting("stop_accepting", new_val)
        return await self.get_stop_accepting()

    async def get_or_create_user(self, user_id: int) -> User:
        async with aiosqlite.connect(self._path) as db:
            # Race-safe: concurrent updates may call this simultaneously.
            await db.execute(
                "INSERT OR IGNORE INTO users(user_id, balance, bonus, frozen, cryptobot_id, created_at) "
                "VALUES(?,?,?,?,?,?)",
                (user_id, 0.0, 0.0, 0.0, None, _utcnow_iso()),
            )
            await db.commit()
            row = await self._fetchone(
                db,
                "SELECT user_id, balance, bonus, frozen, cryptobot_id FROM users WHERE user_id=?",
                (user_id,),
            )
            if row is None:
                # Should not happen, but keep it safe
                return User(user_id=user_id, balance=0.0, bonus=0.0, frozen=0.0, cryptobot_id=None)
            return User(
                user_id=int(row[0]),
                balance=float(row[1]),
                bonus=float(row[2]),
                frozen=float(row[3]),
                cryptobot_id=None if row[4] is None else int(row[4]),
            )

    async def set_cryptobot_id(self, user_id: int, cryptobot_id: int) -> None:
        await self.get_or_create_user(user_id)
        async with aiosqlite.connect(self._path) as db:
            await db.execute("UPDATE users SET cryptobot_id=? WHERE user_id=?", (cryptobot_id, user_id))
            await db.commit()

    async def add_balance(self, user_id: int, amount: float) -> None:
        await self.get_or_create_user(user_id)
        async with aiosqlite.connect(self._path) as db:
            await db.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, user_id))
            await db.commit()

    async def move_balance_to_frozen(self, user_id: int, amount: float) -> None:
        await self.get_or_create_user(user_id)
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                "UPDATE users SET balance = balance - ?, frozen = frozen + ? WHERE user_id=?",
                (amount, amount, user_id),
            )
            await db.commit()

    async def move_frozen_to_balance(self, user_id: int, amount: float) -> None:
        await self.get_or_create_user(user_id)
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                "UPDATE users SET frozen = frozen - ?, balance = balance + ? WHERE user_id=?",
                (amount, amount, user_id),
            )
            await db.commit()

    async def deduct_frozen(self, user_id: int, amount: float) -> None:
        await self.get_or_create_user(user_id)
        async with aiosqlite.connect(self._path) as db:
            await db.execute("UPDATE users SET frozen = frozen - ? WHERE user_id=?", (amount, user_id))
            await db.commit()

    async def create_request(self, *, user_id: int, account_type: str, phone: str) -> int:
        await self.get_or_create_user(user_id)
        now = _utcnow_iso()
        async with aiosqlite.connect(self._path) as db:
            cur = await db.execute(
                """
                INSERT INTO requests(user_id, account_type, phone, status, is_work, is_vip, admin_note, logs, created_at)
                VALUES(?,?,?,?,0,0,NULL,?,?)
                """,
                (user_id, account_type, phone, "pending", f"{now} created\n", now),
            )
            await db.commit()
            return int(cur.lastrowid)

    async def list_user_requests(self, user_id: int, limit: int = 10) -> list[Request]:
        async with aiosqlite.connect(self._path) as db:
            rows = await self._fetchall(
                db,
                """
                SELECT request_id, user_id, account_type, phone, status, is_work, is_vip, admin_note, logs, created_at
                FROM requests
                WHERE user_id=?
                ORDER BY request_id DESC
                LIMIT ?
                """,
                (user_id, limit),
            )
        return [self._row_to_request(r) for r in rows]

    async def list_pending_requests(self, limit: int = 50) -> list[Request]:
        async with aiosqlite.connect(self._path) as db:
            rows = await self._fetchall(
                db,
                """
                SELECT request_id, user_id, account_type, phone, status, is_work, is_vip, admin_note, logs, created_at
                FROM requests
                WHERE status='pending'
                ORDER BY request_id ASC
                LIMIT ?
                """,
                (limit,),
            )
        return [self._row_to_request(r) for r in rows]

    async def get_request(self, request_id: int) -> Request | None:
        async with aiosqlite.connect(self._path) as db:
            row = await self._fetchone(
                db,
                """
                SELECT request_id, user_id, account_type, phone, status, is_work, is_vip, admin_note, logs, created_at
                FROM requests
                WHERE request_id=?
                """,
                (request_id,),
            )
        return None if row is None else self._row_to_request(row)

    async def set_request_status(self, request_id: int, status: str) -> None:
        now = _utcnow_iso()
        async with aiosqlite.connect(self._path) as db:
            await db.execute("UPDATE requests SET status=? WHERE request_id=?", (status, request_id))
            await db.execute(
                "UPDATE requests SET logs = logs || ? WHERE request_id=?",
                (f"{now} status={status}\n", request_id),
            )
            await db.commit()

    async def toggle_request_flag(self, request_id: int, *, flag: str) -> Request | None:
        if flag not in {"is_work", "is_vip"}:
            raise ValueError("flag must be is_work or is_vip")
        now = _utcnow_iso()
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                f"UPDATE requests SET {flag} = CASE WHEN {flag}=1 THEN 0 ELSE 1 END WHERE request_id=?",
                (request_id,),
            )
            await db.execute(
                "UPDATE requests SET logs = logs || ? WHERE request_id=?",
                (f"{now} toggle {flag}\n", request_id),
            )
            await db.commit()
        return await self.get_request(request_id)

    async def set_admin_note(self, request_id: int, note: str) -> None:
        now = _utcnow_iso()
        async with aiosqlite.connect(self._path) as db:
            await db.execute("UPDATE requests SET admin_note=? WHERE request_id=?", (note, request_id))
            await db.execute(
                "UPDATE requests SET logs = logs || ? WHERE request_id=?",
                (f"{now} admin_note set\n", request_id),
            )
            await db.commit()

    async def append_request_log(self, request_id: int, line: str) -> None:
        now = _utcnow_iso()
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                "UPDATE requests SET logs = logs || ? WHERE request_id=?",
                (f"{now} {line}\n", request_id),
            )
            await db.commit()

    async def clear_pending_queue(self) -> int:
        async with aiosqlite.connect(self._path) as db:
            cur = await db.execute("DELETE FROM requests WHERE status='pending'")
            await db.commit()
            return int(cur.rowcount or 0)

    async def create_invoice(
        self,
        *,
        invoice_id: str,
        user_id: int,
        amount: float,
        status: str,
        pay_url: str | None,
        target: str = "user",
    ) -> None:
        await self.get_or_create_user(user_id)
        now = _utcnow_iso()
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                """
                INSERT INTO cryptobot_invoices(invoice_id, user_id, amount, status, credited, target, pay_url, created_at, updated_at)
                VALUES(?,?,?,?,0,?,?,?,?)
                ON CONFLICT(invoice_id) DO NOTHING
                """,
                (invoice_id, user_id, amount, status, target, pay_url, now, now),
            )
            await db.commit()

    async def list_uncredited_invoices(self, limit: int = 100) -> list[dict[str, Any]]:
        async with aiosqlite.connect(self._path) as db:
            rows = await self._fetchall(
                db,
                """
                SELECT invoice_id, user_id, amount, status, credited, target
                FROM cryptobot_invoices
                WHERE credited=0
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (limit,),
            )
        return [
            {
                "invoice_id": str(r[0]),
                "user_id": int(r[1]),
                "amount": float(r[2]),
                "status": str(r[3]),
                "credited": int(r[4]),
                "target": str(r[5] or "user"),
            }
            for r in rows
        ]

    async def update_invoice_status(self, invoice_id: str, status: str) -> None:
        now = _utcnow_iso()
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                "UPDATE cryptobot_invoices SET status=?, updated_at=? WHERE invoice_id=?",
                (status, now, invoice_id),
            )
            await db.commit()

    async def credit_invoice_once(self, invoice_id: str) -> bool:
        """
        Atomically marks invoice as credited and returns True only once.
        """
        now = _utcnow_iso()
        async with aiosqlite.connect(self._path) as db:
            await db.execute("BEGIN IMMEDIATE;")
            row = await self._fetchone(
                db,
                "SELECT user_id, amount, credited, target FROM cryptobot_invoices WHERE invoice_id=?",
                (invoice_id,),
            )
            if row is None:
                await db.execute("ROLLBACK;")
                return False
            user_id, amount, credited, target = int(row[0]), float(row[1]), int(row[2]), str(row[3] or "user")
            if credited == 1:
                await db.execute("ROLLBACK;")
                return False
            await db.execute(
                "UPDATE cryptobot_invoices SET credited=1, updated_at=?, status='paid' WHERE invoice_id=?",
                (now, invoice_id),
            )
            if target != "treasury":
                await db.execute("UPDATE users SET balance = balance + ? WHERE user_id=?", (amount, user_id))
            await db.commit()
            return True

    async def create_withdrawal(self, *, user_id: int, amount: float, fee: float) -> int:
        await self.get_or_create_user(user_id)
        net = max(0.0, amount - fee)
        now = _utcnow_iso()
        async with aiosqlite.connect(self._path) as db:
            cur = await db.execute(
                """
                INSERT INTO withdrawals(user_id, amount, net, fee, status, cryptobot_transfer_id, created_at, updated_at)
                VALUES(?,?,?,?,?,?,?,?)
                """,
                (user_id, amount, net, fee, "pending", None, now, now),
            )
            await db.commit()
            return int(cur.lastrowid)

    async def list_pending_withdrawals(self, limit: int = 50) -> list[Withdrawal]:
        async with aiosqlite.connect(self._path) as db:
            rows = await self._fetchall(
                db,
                """
                SELECT withdrawal_id, user_id, amount, net, fee, status, cryptobot_transfer_id, created_at
                FROM withdrawals
                WHERE status='pending'
                ORDER BY withdrawal_id ASC
                LIMIT ?
                """,
                (limit,),
            )
        return [self._row_to_withdrawal(r) for r in rows]

    async def set_withdrawal_status(
        self, withdrawal_id: int, *, status: str, cryptobot_transfer_id: str | None = None
    ) -> None:
        now = _utcnow_iso()
        async with aiosqlite.connect(self._path) as db:
            await db.execute(
                "UPDATE withdrawals SET status=?, cryptobot_transfer_id=?, updated_at=? WHERE withdrawal_id=?",
                (status, cryptobot_transfer_id, now, withdrawal_id),
            )
            await db.commit()

    async def export_withdrawals_csv_rows(self) -> list[list[str]]:
        async with aiosqlite.connect(self._path) as db:
            rows = await self._fetchall(
                db,
                """
                SELECT withdrawal_id, user_id, amount, net, fee, status, cryptobot_transfer_id, created_at
                FROM withdrawals
                ORDER BY withdrawal_id DESC
                """
            )
        out: list[list[str]] = [
            [
                "withdrawal_id",
                "user_id",
                "amount",
                "net",
                "fee",
                "status",
                "cryptobot_transfer_id",
                "created_at",
            ]
        ]
        for r in rows:
            out.append([str(x) if x is not None else "" for x in r])
        return out

    @staticmethod
    def _row_to_request(row: Iterable[Any]) -> Request:
        r = list(row)
        return Request(
            request_id=int(r[0]),
            user_id=int(r[1]),
            account_type=str(r[2]),
            phone=str(r[3]),
            status=str(r[4]),
            is_work=int(r[5]),
            is_vip=int(r[6]),
            admin_note=None if r[7] is None else str(r[7]),
            logs=str(r[8] or ""),
            created_at=str(r[9]),
        )

    @staticmethod
    def _row_to_withdrawal(row: Iterable[Any]) -> Withdrawal:
        r = list(row)
        return Withdrawal(
            withdrawal_id=int(r[0]),
            user_id=int(r[1]),
            amount=float(r[2]),
            net=float(r[3]),
            fee=float(r[4]),
            status=str(r[5]),
            cryptobot_transfer_id=None if r[6] is None else str(r[6]),
            created_at=str(r[7]),
        )
