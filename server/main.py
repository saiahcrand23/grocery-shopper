from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from db import get_conn, init_db

app = FastAPI(title="Grocery Shopper API")

# LAN-only for now, not wired to a real origin yet — tighten before any public exposure.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


@app.on_event("startup")
def on_startup():
    init_db()


class ItemIn(BaseModel):
    name: str
    category: str
    default_store: int


class CategoryIn(BaseModel):
    position: Optional[int] = None


class CheckedIn(BaseModel):
    qty: int = 1
    store_override: Optional[int] = None


class OrderLineIn(BaseModel):
    item_id: Optional[str] = None
    name: str
    category: str
    store: str
    qty: int


class OrderIn(BaseModel):
    id: str
    lines: list[OrderLineIn]
    finalized_at: Optional[str] = None


@app.get("/api/health")
def health():
    return {"ok": True}


def _items(conn):
    rows = conn.execute(
        "SELECT id, name, category, default_store, updated_at FROM items WHERE deleted_at IS NULL"
    ).fetchall()
    return [dict(r) for r in rows]


def _categories(conn):
    rows = conn.execute(
        "SELECT name, position FROM categories WHERE deleted_at IS NULL ORDER BY position"
    ).fetchall()
    return [dict(r) for r in rows]


def _checked(conn):
    rows = conn.execute("SELECT item_id, qty, store_override, updated_at FROM checked").fetchall()
    return {r["item_id"]: {"qty": r["qty"], "store_override": r["store_override"], "updated_at": r["updated_at"]} for r in rows}


def _history(conn):
    orders = conn.execute("SELECT id, finalized_at FROM orders ORDER BY finalized_at DESC").fetchall()
    result = []
    for o in orders:
        lines = conn.execute(
            "SELECT item_id, name, category, store, qty FROM order_lines WHERE order_id = ?",
            (o["id"],),
        ).fetchall()
        result.append({"id": o["id"], "finalized_at": o["finalized_at"], "lines": [dict(l) for l in lines]})
    return result


@app.get("/api/state")
def get_state():
    with get_conn() as conn:
        return {
            "items": _items(conn),
            "categories": _categories(conn),
            "checked": _checked(conn),
            "history": _history(conn),
        }


@app.get("/api/items")
def list_items():
    with get_conn() as conn:
        return _items(conn)


@app.put("/api/items/{item_id}")
def upsert_item(item_id: str, body: ItemIn):
    with get_conn() as conn:
        ts = now()
        conn.execute(
            """
            INSERT INTO items (id, name, category, default_store, updated_at, deleted_at)
            VALUES (?, ?, ?, ?, ?, NULL)
            ON CONFLICT(id) DO UPDATE SET
              name=excluded.name, category=excluded.category,
              default_store=excluded.default_store, updated_at=excluded.updated_at, deleted_at=NULL
            """,
            (item_id, body.name, body.category, body.default_store, ts),
        )
        row = conn.execute("SELECT id, name, category, default_store, updated_at FROM items WHERE id=?", (item_id,)).fetchone()
        return dict(row)


@app.delete("/api/items/{item_id}")
def delete_item(item_id: str):
    with get_conn() as conn:
        ts = now()
        cur = conn.execute("UPDATE items SET deleted_at=? WHERE id=? AND deleted_at IS NULL", (ts, item_id))
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="item not found")
        conn.execute("DELETE FROM checked WHERE item_id=?", (item_id,))
        return {"ok": True}


@app.get("/api/categories")
def list_categories():
    with get_conn() as conn:
        return _categories(conn)


@app.put("/api/categories/{name}")
def upsert_category(name: str, body: CategoryIn = CategoryIn()):
    with get_conn() as conn:
        ts = now()
        if body.position is not None:
            position = body.position
        else:
            existing = conn.execute("SELECT position FROM categories WHERE name=?", (name,)).fetchone()
            if existing is not None:
                position = existing["position"]
            else:
                row = conn.execute("SELECT MAX(position) AS m FROM categories").fetchone()
                position = (row["m"] + 1) if row["m"] is not None else 0
        conn.execute(
            """
            INSERT INTO categories (name, position, updated_at, deleted_at)
            VALUES (?, ?, ?, NULL)
            ON CONFLICT(name) DO UPDATE SET position=excluded.position, updated_at=excluded.updated_at, deleted_at=NULL
            """,
            (name, position, ts),
        )
        return {"name": name, "position": position}


@app.get("/api/checked")
def get_checked():
    with get_conn() as conn:
        return _checked(conn)


@app.put("/api/checked/{item_id}")
def check_item(item_id: str, body: CheckedIn):
    with get_conn() as conn:
        item = conn.execute("SELECT id FROM items WHERE id=? AND deleted_at IS NULL", (item_id,)).fetchone()
        if item is None:
            raise HTTPException(status_code=404, detail="item not found")
        ts = now()
        conn.execute(
            """
            INSERT INTO checked (item_id, qty, store_override, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(item_id) DO UPDATE SET qty=excluded.qty, store_override=excluded.store_override, updated_at=excluded.updated_at
            """,
            (item_id, body.qty, body.store_override, ts),
        )
        return {"item_id": item_id, "qty": body.qty, "store_override": body.store_override, "updated_at": ts}


@app.delete("/api/checked/{item_id}")
def uncheck_item(item_id: str):
    with get_conn() as conn:
        conn.execute("DELETE FROM checked WHERE item_id=?", (item_id,))
        return {"ok": True}


@app.delete("/api/checked")
def uncheck_all():
    with get_conn() as conn:
        conn.execute("DELETE FROM checked")
        return {"ok": True}


@app.post("/api/orders")
def create_order(body: OrderIn):
    with get_conn() as conn:
        existing = conn.execute("SELECT id FROM orders WHERE id=?", (body.id,)).fetchone()
        if existing is not None:
            return {"ok": True, "id": body.id, "already_existed": True}
        ts = body.finalized_at or now()
        conn.execute("INSERT INTO orders (id, finalized_at) VALUES (?, ?)", (body.id, ts))
        for line in body.lines:
            conn.execute(
                """
                INSERT INTO order_lines (order_id, item_id, name, category, store, qty)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (body.id, line.item_id, line.name, line.category, line.store, line.qty),
            )
        conn.execute("DELETE FROM checked")
        return {"ok": True, "id": body.id, "finalized_at": ts}


@app.get("/api/orders")
def list_orders():
    with get_conn() as conn:
        return _history(conn)
