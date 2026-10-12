import base64
import os
import re
import shutil
import subprocess
import tempfile
from html import escape
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel

from db import get_conn, init_db

app = FastAPI(title="Grocery Shopper API")

ROOT = Path(__file__).resolve().parent.parent  # repo root, one level above server/

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://grocery.crandnet.com"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# Without this the responses carry only an ETag/Last-Modified, which lets a
# browser apply heuristic freshness and serve the shell from its HTTP cache for
# hours without asking. The service worker's own fetch goes through that cache
# too, so it would re-cache the stale copy and the installed app would sit on an
# old build while online. "no-cache" means revalidate, not "don't store" — the
# ETag turns each check into a cheap 304, and offline still serves from the
# service worker's Cache Storage.
SHELL_HEADERS = {"cache-control": "no-cache"}


@app.get("/")
def serve_index():
    return FileResponse(ROOT / "index.html", headers=SHELL_HEADERS)


MEAL_PLAN_CSS = """
*{box-sizing:border-box;-webkit-print-color-adjust:exact;print-color-adjust:exact}
body{margin:0;background:#fff;color:#4a2f28;padding:34px;
  font:14px -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
h1{font-family:Georgia,"Times New Roman",serif;font-weight:400;font-size:40px;
  text-align:center;color:#5a3a32;margin:0 0 26px}
.body{display:block}
.wk{display:flex;align-items:center;gap:8px;margin-bottom:18px;max-width:300px}
.wk span{background:#f6b8bc;border-radius:999px;padding:5px 9px;font-size:9px;letter-spacing:.08em}
.wk b{flex:1;background:#fbd3d6;border-radius:999px;padding:7px 10px;font-size:11px;font-weight:400}
.days{flex:1}
.day{display:flex;gap:6px;margin-bottom:12px;page-break-inside:avoid}
.dayname{flex:0 0 40px;border-radius:9px;background:#f3e8dc;display:flex;align-items:center;
  justify-content:center;writing-mode:vertical-rl;transform:rotate(180deg);
  font-size:10px;letter-spacing:.14em}
.slots{flex:1;border-radius:9px;background:#f3e8dc;padding:14px 18px;display:grid;
  grid-template-columns:1fr 1fr;gap:14px 26px;min-height:86px}
.day.alt .dayname,.day.alt .slots{background:#fbd3d6}
.slot span{display:block;font-size:8.5px;letter-spacing:.12em;color:#8a6a60}
.slot p{margin:3px 0 0;font-size:12.5px;line-height:1.35;min-height:16px}
.slot em{font-style:normal;font-size:10px;color:#a1837a;white-space:nowrap}
@page{size:A4;margin:12mm}
@media screen{body{max-width:820px;margin:0 auto}}
/* A standalone web app has no browser chrome, so this page has to offer its
   own way back or there's no escape from it. */
.back{margin:28px 0 0;text-align:center}
.back a{color:#8a6a60;font-size:13px;text-decoration:none}
@media print{.back{display:none}}
"""


# Chrome has to fetch the page from this same server. Kept local and
# overridable rather than derived from the request, whose host is the public
# tunnel address that Access would block.
PRINT_ORIGIN = os.environ.get("GROCERY_PRINT_ORIGIN", "http://127.0.0.1:8000")


def _chrome():
    for exe in ("google-chrome", "chromium", "chromium-browser"):
        path = shutil.which(exe)
        if path:
            return path
    return None


def _pdf_of(path: str, filename: str):
    """A PDF, because iOS can hand that to the share sheet — which is the only
    place an installed web app can reach a Print option. Always rendered from
    one of the HTML routes, so there's never a second layout to keep in step."""
    chrome = _chrome()
    if not chrome:
        raise HTTPException(status_code=503, detail="No browser on the server to build the PDF with.")
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "out.pdf")
        try:
            subprocess.run([chrome, "--headless", "--disable-gpu", "--no-sandbox",
                            "--no-pdf-header-footer", f"--print-to-pdf={out}",
                            f"--user-data-dir={tmp}/profile", PRINT_ORIGIN + path],
                           capture_output=True, timeout=60, check=True)
        except subprocess.TimeoutExpired:
            raise HTTPException(status_code=504, detail="Building the PDF took too long.")
        except subprocess.CalledProcessError:
            raise HTTPException(status_code=500, detail="Couldn't build the PDF.")
        if not os.path.exists(out):
            raise HTTPException(status_code=500, detail="Couldn't build the PDF.")
        return Response(open(out, "rb").read(), media_type="application/pdf",
                        headers={"content-disposition": f'inline; filename="{filename}"',
                                 "cache-control": "no-store"})


@app.get("/print/meal-plan.pdf")
def meal_plan_pdf():
    return _pdf_of("/print/meal-plan", "meal-plan.pdf")


# Store names live on the client as a constant; printing needs them here too.
STORES = ["Wal-Mart", "Sam's Club", "Produce Store"]

ORDER_CSS = """
*{box-sizing:border-box}
body{margin:0;padding:30px;color:#111;font:14px -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
h1{font-size:23px;margin:0 0 2px}
.date{color:#555;font-size:13px;margin-bottom:20px}
/* No avoid-break on the store block: with recipe amounts a single store can
   run past a full page, and avoiding the break just pushed it wholesale to the
   next sheet and left page one blank. Keep individual items intact instead. */
.store{margin-bottom:20px}
h2{break-after:avoid}
h3{break-after:avoid}
li{break-inside:avoid}
h2{font-size:17px;border-bottom:1px solid #000;padding-bottom:3px;margin:0 0 8px}
h3{font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:#444;margin:11px 0 4px}
ul{list-style:none;margin:0;padding:0}
li{display:flex;align-items:flex-start;gap:9px;padding:3.5px 0;font-size:14px}
.who{display:block}
.amt{display:block;font-size:11.5px;color:#333;margin-top:1px}
.amt i{font-style:normal;color:#777}
.box{width:13px;height:13px;border:1.5px solid #000;border-radius:2px;flex:0 0 auto;margin-top:2px}
.back{margin:28px 0 0;text-align:center}
.back a{color:#777;font-size:13px;text-decoration:none}
@page{size:A4;margin:14mm}
@media print{.back{display:none}}
@media screen{body{max-width:760px;margin:0 auto}}
"""


def _order_sheet(title: str, subtitle: str, rows):
    """rows: (store, category, item name, qty, [amount lines]), grouped for printing."""
    html = ""
    for store in STORES + sorted({r[0] for r in rows} - set(STORES)):
        here = [r for r in rows if r[0] == store]
        if not here:
            continue
        cats, seen = [], set()
        for r in here:
            if r[1] not in seen:
                seen.add(r[1]); cats.append(r[1])
        body = ""
        for cat in cats:
            lis = ""
            for st, c, n, q, amounts in here:
                if c != cat:
                    continue
                extra = "".join(f'<span class="amt">{escape(t)} <i>{escape(src)}</i></span>'
                                for t, src in amounts)
                lis += (f'<li><span class="box"></span><span class="who">{escape(n)}'
                        f'{f" ×{q}" if q > 1 else ""}{extra}</span></li>')
            body += f"<h3>{escape(cat)}</h3><ul>{lis}</ul>"
        html += f'<div class="store"><h2>{escape(store)}</h2>{body}</div>'
    return HTMLResponse(f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)}</title><style>{ORDER_CSS}</style></head><body>
<h1>{escape(title)}</h1><div class="date">{escape(subtitle)}</div>
{html or "<p>Nothing on the list.</p>"}
<p class="back"><a href="/">&lsaquo; Back to the app</a></p>
</body></html>""", headers=SHELL_HEADERS)


@app.get("/print/order", response_class=HTMLResponse)
def print_order():
    from datetime import date
    with get_conn() as conn:
        items = {r["id"]: r for r in conn.execute(
            "SELECT id, name, category, default_store FROM items WHERE deleted_at IS NULL")}
        # What this week's planned recipes ask for, in their own words.
        wanted = {}
        for r in _recipes(conn):
            if r["planned_day"] is None:
                continue
            for g in r["ingredients"]:
                if g["item_id"]:
                    wanted.setdefault(g["item_id"], []).append((g["text"], r["title"]))
        rows = []
        for item_id, c in _checked(conn).items():
            it = items.get(item_id)
            if not it:
                continue
            si = c["store_override"] if c["store_override"] is not None else it["default_store"]
            rows.append((STORES[si] if 0 <= si < len(STORES) else STORES[0],
                         it["category"], it["name"], c["qty"], wanted.get(item_id, [])))
    rows.sort(key=lambda r: (r[1].lower(), r[2].lower()))
    return _order_sheet("Shopping List", f"{date.today():%A, %B %-d, %Y}", rows)


@app.get("/print/order.pdf")
def order_pdf():
    return _pdf_of("/print/order", "shopping-list.pdf")


# Registered before the HTML route below: {order_id} matches any non-slash
# run, so the HTML route would otherwise capture "<id>.pdf" whole and 404.
@app.get("/print/order/{order_id}.pdf")
def past_order_pdf(order_id: str):
    # Check first: Chrome will cheerfully render a 404 page into a valid PDF,
    # so without this a bad id comes back as 200 and a sheet saying "not found".
    with get_conn() as conn:
        if conn.execute("SELECT 1 FROM orders WHERE id=?", (order_id,)).fetchone() is None:
            raise HTTPException(status_code=404, detail="order not found")
    return _pdf_of(f"/print/order/{order_id}", "shopping-list.pdf")


@app.get("/print/order/{order_id}", response_class=HTMLResponse)
def print_past_order(order_id: str):
    with get_conn() as conn:
        o = conn.execute("SELECT finalized_at FROM orders WHERE id=?", (order_id,)).fetchone()
        if o is None:
            raise HTTPException(status_code=404, detail="order not found")
        rows = [(l["store"], l["category"], l["name"], l["qty"], []) for l in conn.execute(
            "SELECT name, category, store, qty FROM order_lines WHERE order_id=?", (order_id,))]
    rows.sort(key=lambda r: (r[1].lower(), r[2].lower()))
    when = datetime.fromisoformat(o["finalized_at"].replace("Z", "+00:00"))
    return _order_sheet("Shopping List", f"{when:%A, %B %-d, %Y}", rows)


DAYS_LONG = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
DAYS_ABBR = ["MON", "TUES", "WED", "THURS", "FRI", "SAT", "SUN"]


@app.get("/print/meal-plan", response_class=HTMLResponse)
def print_meal_plan():
    """Rendered here rather than in the app because window.print() does nothing
    in an iOS home-screen web app. Opening this in Safari gives a real print
    dialog, and it works from a desktop browser too."""
    from datetime import date, timedelta
    with get_conn() as conn:
        recipes = [r for r in _recipes(conn) if r["planned_day"] is not None]

    monday = date.today() - timedelta(days=date.today().weekday())
    span = f"{monday:%b %-d} – {monday + timedelta(days=6):%b %-d}"

    days = ""
    for d in range(7):
        dinner = "<br>".join(
            escape(r["title"]) + (f' <em>{r["minutes"]}m</em>' if r["minutes"] else "")
            for r in recipes if r["planned_day"] == d)
        slots = "".join(f'<div class="slot"><span>{lbl}</span><p>{val}</p></div>'
                        for lbl, val in (("BREAKFAST", ""), ("DINNER", dinner), ("LUNCH", ""), ("SNACK", "")))
        days += (f'<div class="day{" alt" if d % 2 else ""}">'
                 f'<div class="dayname">{DAYS_ABBR[d]}</div><div class="slots">{slots}</div></div>')

    return HTMLResponse(f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Weekly Meal Plan</title><style>{MEAL_PLAN_CSS}</style></head><body>
<h1>Weekly Meal Plan</h1>
<div class="wk"><span>WK</span><b>{span}</b></div>
<div class="body"><div class="days">{days}</div></div>
<p class="back"><a href="/">&lsaquo; Back to the app</a></p>
</body></html>""", headers=SHELL_HEADERS)


@app.get("/sw.js")
def serve_sw():
    return FileResponse(ROOT / "sw.js", media_type="application/javascript", headers=SHELL_HEADERS)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


@app.on_event("startup")
def on_startup():
    init_db()


class ItemIn(BaseModel):
    name: str
    category: str
    default_store: int
    # None means "leave as-is". A False default would clear the flag on every
    # write that doesn't mention it.
    staple: Optional[bool] = None
    oneoff: Optional[bool] = None


class CategoryIn(BaseModel):
    position: Optional[int] = None
    interchangeable: Optional[bool] = None


class RenameIn(BaseModel):
    new_name: str


class IngredientIn(BaseModel):
    text: str
    item_id: Optional[str] = None


class RecipeIn(BaseModel):
    title: str
    instructions: str = ""
    minutes: Optional[int] = None
    cost: Optional[int] = None
    healthy: bool = False
    health_notes: str = ""
    source_url: str = ""
    planned_day: Optional[int] = None
    ingredients: list[IngredientIn] = []


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
        "SELECT id, name, category, default_store, staple, oneoff, updated_at FROM items WHERE deleted_at IS NULL"
    ).fetchall()
    return [dict(r) for r in rows]


def _categories(conn):
    rows = conn.execute(
        "SELECT name, position, interchangeable FROM categories WHERE deleted_at IS NULL ORDER BY position"
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


def _recipes(conn):
    rows = conn.execute(
        """SELECT id, title, instructions, minutes, cost, healthy, health_notes, source_url, planned_day
           FROM recipes WHERE deleted_at IS NULL ORDER BY title"""
    ).fetchall()
    out = []
    for r in rows:
        ing = conn.execute(
            "SELECT text, item_id FROM recipe_ingredients WHERE recipe_id=? ORDER BY position",
            (r["id"],),
        ).fetchall()
        d = dict(r)
        d["ingredients"] = [dict(i) for i in ing]
        out.append(d)
    return out


@app.get("/api/state")
def get_state():
    with get_conn() as conn:
        return {
            "items": _items(conn),
            "categories": _categories(conn),
            "checked": _checked(conn),
            "history": _history(conn),
            "recipes": _recipes(conn),
        }


@app.get("/api/items")
def list_items():
    with get_conn() as conn:
        return _items(conn)


@app.put("/api/items/{item_id}")
def upsert_item(item_id: str, body: ItemIn):
    with get_conn() as conn:
        ts = now()
        prev = conn.execute("SELECT staple, oneoff FROM items WHERE id=?", (item_id,)).fetchone()
        staple = int(body.staple) if body.staple is not None else (prev["staple"] if prev else 0)
        oneoff = int(body.oneoff) if body.oneoff is not None else (prev["oneoff"] if prev else 0)
        conn.execute(
            """
            INSERT INTO items (id, name, category, default_store, staple, oneoff, updated_at, deleted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
            ON CONFLICT(id) DO UPDATE SET
              name=excluded.name, category=excluded.category,
              default_store=excluded.default_store, staple=excluded.staple,
              oneoff=excluded.oneoff, updated_at=excluded.updated_at, deleted_at=NULL
            """,
            (item_id, body.name, body.category, body.default_store, staple, oneoff, ts),
        )
        row = conn.execute("SELECT id, name, category, default_store, staple, oneoff, updated_at FROM items WHERE id=?", (item_id,)).fetchone()
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
        existing = conn.execute("SELECT position, interchangeable FROM categories WHERE name=?", (name,)).fetchone()
        if body.position is not None:
            position = body.position
        elif existing is not None:
            position = existing["position"]
        else:
            row = conn.execute("SELECT MAX(position) AS m FROM categories").fetchone()
            position = (row["m"] + 1) if row["m"] is not None else 0
        if body.interchangeable is not None:
            interchangeable = int(body.interchangeable)
        else:
            interchangeable = existing["interchangeable"] if existing else 0
        conn.execute(
            """
            INSERT INTO categories (name, position, interchangeable, updated_at, deleted_at)
            VALUES (?, ?, ?, ?, NULL)
            ON CONFLICT(name) DO UPDATE SET position=excluded.position,
              interchangeable=excluded.interchangeable, updated_at=excluded.updated_at, deleted_at=NULL
            """,
            (name, position, interchangeable, ts),
        )
        return {"name": name, "position": position, "interchangeable": interchangeable}


@app.post("/api/categories/{name}/rename")
def rename_category(name: str, body: RenameIn):
    """Renaming moves every item in the category, so it happens here in one
    transaction rather than as a category write plus one write per item — a
    partial failure would strand items across two category names.

    order_lines keep the old category string on purpose: they're snapshots of
    what a past order looked like, and analysis joins them back to items by
    item_id anyway."""
    new_name = body.new_name.strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="new_name is required")
    with get_conn() as conn:
        row = conn.execute(
            "SELECT position, interchangeable FROM categories WHERE name=? AND deleted_at IS NULL", (name,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="category not found")
        if new_name != name:
            clash = conn.execute(
                "SELECT name FROM categories WHERE name=? AND deleted_at IS NULL", (new_name,)
            ).fetchone()
            if clash is not None:
                raise HTTPException(status_code=409, detail="a category with that name already exists")
        ts = now()
        conn.execute(
            "INSERT INTO categories (name, position, interchangeable, updated_at, deleted_at) VALUES (?, ?, ?, ?, NULL)"
            " ON CONFLICT(name) DO UPDATE SET position=excluded.position,"
            " interchangeable=excluded.interchangeable, updated_at=excluded.updated_at, deleted_at=NULL",
            (new_name, row["position"], row["interchangeable"], ts),
        )
        moved = conn.execute(
            "UPDATE items SET category=?, updated_at=? WHERE category=?", (new_name, ts, name)
        ).rowcount
        if new_name != name:
            conn.execute("DELETE FROM categories WHERE name=?", (name,))
        return {"ok": True, "name": new_name, "items_moved": moved}


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


def _write_lines(conn, order_id: str, lines):
    for line in lines:
        conn.execute(
            """
            INSERT INTO order_lines (order_id, item_id, name, category, store, qty)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (order_id, line.item_id, line.name, line.category, line.store, line.qty),
        )


@app.post("/api/orders")
def create_order(body: OrderIn):
    with get_conn() as conn:
        existing = conn.execute("SELECT id FROM orders WHERE id=?", (body.id,)).fetchone()
        if existing is not None:
            return {"ok": True, "id": body.id, "already_existed": True}
        ts = body.finalized_at or now()
        conn.execute("INSERT INTO orders (id, finalized_at) VALUES (?, ?)", (body.id, ts))
        _write_lines(conn, body.id, body.lines)
        conn.execute("DELETE FROM checked")
        return {"ok": True, "id": body.id, "finalized_at": ts}


@app.put("/api/orders/{order_id}")
def replace_order(order_id: str, body: OrderIn):
    with get_conn() as conn:
        row = conn.execute("SELECT finalized_at FROM orders WHERE id=?", (order_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="order not found")
        ts = body.finalized_at or row["finalized_at"]
        conn.execute("UPDATE orders SET finalized_at=? WHERE id=?", (ts, order_id))
        conn.execute("DELETE FROM order_lines WHERE order_id=?", (order_id,))
        _write_lines(conn, order_id, body.lines)
        return {"ok": True, "id": order_id, "finalized_at": ts}


@app.delete("/api/orders/{order_id}")
def delete_order(order_id: str):
    with get_conn() as conn:
        # Lines first: foreign_keys is ON, so the parent row can't go while they exist.
        conn.execute("DELETE FROM order_lines WHERE order_id=?", (order_id,))
        conn.execute("DELETE FROM orders WHERE id=?", (order_id,))
        return {"ok": True}


@app.get("/api/orders")
def list_orders():
    with get_conn() as conn:
        return _history(conn)


def _write_ingredients(conn, recipe_id: str, ingredients):
    for pos, ing in enumerate(ingredients):
        conn.execute(
            "INSERT INTO recipe_ingredients (recipe_id, position, text, item_id) VALUES (?, ?, ?, ?)",
            (recipe_id, pos, ing.text, ing.item_id),
        )


@app.get("/api/recipes")
def list_recipes():
    with get_conn() as conn:
        return _recipes(conn)


@app.put("/api/recipes/{recipe_id}")
def upsert_recipe(recipe_id: str, body: RecipeIn):
    with get_conn() as conn:
        ts = now()
        conn.execute(
            """
            INSERT INTO recipes (id, title, instructions, minutes, cost, healthy, health_notes, source_url, planned_day, updated_at, deleted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
            ON CONFLICT(id) DO UPDATE SET
              title=excluded.title, instructions=excluded.instructions, minutes=excluded.minutes,
              cost=excluded.cost, healthy=excluded.healthy, health_notes=excluded.health_notes,
              source_url=excluded.source_url, planned_day=excluded.planned_day,
              updated_at=excluded.updated_at, deleted_at=NULL
            """,
            (recipe_id, body.title, body.instructions, body.minutes, body.cost,
             int(body.healthy), body.health_notes, body.source_url, body.planned_day, ts),
        )
        # Ingredients are replaced wholesale — the client always sends the full list.
        conn.execute("DELETE FROM recipe_ingredients WHERE recipe_id=?", (recipe_id,))
        _write_ingredients(conn, recipe_id, body.ingredients)
        return {"ok": True, "id": recipe_id}


@app.delete("/api/recipes/{recipe_id}")
def delete_recipe(recipe_id: str):
    with get_conn() as conn:
        # Ingredients first: foreign_keys is ON.
        conn.execute("DELETE FROM recipe_ingredients WHERE recipe_id=?", (recipe_id,))
        conn.execute("DELETE FROM recipes WHERE id=?", (recipe_id,))
        return {"ok": True}


# ---------- recipe extraction ----------
# The only place this project calls a model. It runs at write time only: the
# result is stored, so searching and filtering stay instant, free and offline.

class ExtractedIngredient(BaseModel):
    text: str
    item_id: Optional[str] = None
    # Used only when item_id is null: what this ingredient should be called as a
    # grocery item, so an unmatched ingredient can still reach the list.
    item_name: Optional[str] = None
    category: Optional[str] = None


class ExtractedRecipe(BaseModel):
    title: str
    instructions: str
    minutes: Optional[int] = None
    cost: Optional[int] = None
    healthy: bool
    health_notes: str
    source_url: str = ""
    ingredients: list[ExtractedIngredient] = []


IMAGE_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/gif", "image/webp"}
# The API caps a request at 32MB and base64 inflates by about a third, so the
# raw file has to stay comfortably under that.
MAX_UPLOAD_BYTES = 20 * 1024 * 1024

EXTRACT_SYSTEM = """You extract structured recipes from text, photos and PDFs.

Rules:
- `instructions` is the full method as readable numbered steps.
- `minutes` is total time start to finish; null if not stated or inferable.
- `cost` is a rough grocery cost: 1 cheap, 2 moderate, 3 expensive. Never null.
- `healthy` is a plain yes/no judgement for everyday home cooking.
- `health_notes` is one short phrase, e.g. "high protein, low carb".
- `source_url` is the recipe's web address if one is visible on the page or in
  the text (printouts often carry it in a header or footer). Empty string if
  there isn't one. Never guess or construct a URL.
- `ingredients[].text` is the ingredient exactly as written, quantity included.
- `ingredients[].item_id` links to the household's grocery inventory. Use an id
  from the supplied list when the ingredient is clearly that item; otherwise
  null. Never invent an id. A rough match is fine (mozzarella -> a shredded
  cheese item); a wrong one is worse than null, since null just asks the user.
- When `item_id` is null, fill `item_name` and `category` so the ingredient can
  still be shopped for:
    - `item_name` is what you'd look for in a shop, not the recipe wording:
      "2 medium sweet potatoes, cut into cubes" -> "Sweet Potatoes";
      "4 cloves garlic, minced" -> "Garlic".
      Title Case, no quantities, no preparation, singular or plural as it would
      appear on a shelf.
    - `category` must be one of the supplied category names.
    - Leave both null for things nobody buys per recipe - "salt and pepper to
      taste", "water", "ice" - when they aren't already in the inventory.
  When `item_id` is set, leave `item_name` and `category` null."""


def _file_block(raw: bytes, media_type: str):
    data = base64.standard_b64encode(raw).decode("utf-8")
    if media_type == "application/pdf":
        return {"type": "document",
                "source": {"type": "base64", "media_type": "application/pdf", "data": data}}
    return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}}


def _extract_blocks(text: Optional[str], uploads):
    """uploads is a list of (bytes, media_type). More than one means the pages
    of a single recipe, not several recipes — the caller decides that by how it
    batches its requests."""
    if not uploads:
        return [{"type": "text", "text": f"Extract the recipe from this text:\n\n{text}"}]
    blocks = [_file_block(raw, mt) for raw, mt in uploads]
    # Documents/images first, instruction after — the documented ordering.
    blocks.append({"type": "text", "text":
        "Extract the recipe from this file." if len(uploads) == 1 else
        f"These {len(uploads)} files are consecutive pages of ONE recipe, in order. "
        "Combine them into a single recipe — ingredients may be on one page and the "
        "method on another, and a list may continue across a page break."})
    return blocks


@app.post("/api/recipes/extract")
async def extract_recipe(text: Optional[str] = Form(None), url: Optional[str] = Form(None),
                         files: list[UploadFile] = File(default=[])):
    # Input is validated before the key check so a bad file reports what's
    # actually wrong with it rather than a generic configuration message.
    uploads = []
    total = 0
    for f in files:
        media_type = (f.content_type or "").lower()
        if media_type not in IMAGE_TYPES and media_type != "application/pdf":
            raise HTTPException(status_code=415,
                                detail=f"Can't read {media_type or 'that file type'}. Upload PDFs or images.")
        raw = await f.read()
        total += len(raw)
        # The cap is on the whole request, since every page rides in one call.
        if total > MAX_UPLOAD_BYTES:
            mb = total / 1024 / 1024
            raise HTTPException(status_code=413,
                                detail=f"That's {mb:.0f}MB of files. The limit is 20MB per recipe — try fewer pages at a time.")
        uploads.append((raw, "image/jpeg" if media_type == "image/jpg" else media_type))
    url = (url or "").strip()
    if url and not re.match(r"^https?://", url, re.I):
        raise HTTPException(status_code=400, detail="That doesn't look like a web link. It should start with https://")
    if not uploads and not url and not (text or "").strip():
        raise HTTPException(status_code=400, detail="Provide a link, a file, or recipe text.")

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(status_code=503,
                            detail="Recipe extraction isn't configured on the server. Enter the recipe manually.")

    with get_conn() as conn:
        inventory = [{"id": r["id"], "name": r["name"], "category": r["category"]} for r in conn.execute(
            "SELECT id, name, category FROM items WHERE deleted_at IS NULL ORDER BY category, name")]
        categories = [r["name"] for r in conn.execute(
            "SELECT name FROM categories WHERE deleted_at IS NULL ORDER BY position")]

    import anthropic
    client = anthropic.Anthropic()
    # Claude does the fetching, not this server: the page is retrieved on
    # Anthropic's side, so a pasted link can never reach anything on this LAN.
    tools = [{"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 3}] if url else []
    try:
        response = client.messages.parse(
            model="claude-opus-5",
            max_tokens=16000,
            output_config={"effort": "low"},  # extraction is mechanical; raise if results disappoint
            system=EXTRACT_SYSTEM,
            tools=tools,
            messages=[
                {"role": "user", "content": [{"type": "text",
                 "text": "Grocery inventory to link ingredients against:\n" +
                         "\n".join(f"{i['id']} = {i['name']} ({i['category']})" for i in inventory) +
                         "\n\nCategories available for new items:\n" + ", ".join(categories)}]},
                {"role": "user", "content":
                    f"Fetch {url} and extract the recipe from that page. Ignore surrounding "
                    f"site navigation, comments and adverts." if url
                    else _extract_blocks(text, uploads)},
            ],
            output_format=ExtractedRecipe,
        )
    except anthropic.BadRequestError as e:
        raise HTTPException(status_code=400, detail=f"Claude rejected that input: {e.message}")
    except anthropic.AuthenticationError:
        raise HTTPException(status_code=503, detail="The server's Anthropic API key is invalid.")
    except anthropic.RateLimitError:
        raise HTTPException(status_code=429, detail="Rate limited — try again in a moment.")
    except anthropic.APIStatusError as e:
        raise HTTPException(status_code=502, detail=f"Claude returned an error ({e.status_code}).")
    except anthropic.APIConnectionError:
        raise HTTPException(status_code=502, detail="Couldn't reach Claude. Check the server's connection.")

    recipe = response.parsed_output
    # The link the user gave is the authoritative source, whatever the page says.
    if url:
        recipe.source_url = url
    # Never trust a returned id: a hallucinated one would silently attach an
    # ingredient to the wrong grocery item.
    valid = {i["id"] for i in inventory}
    known_cats = set(categories)
    for ing in recipe.ingredients:
        if ing.item_id not in valid:
            ing.item_id = None
        if ing.item_id:
            # A matched ingredient needs no new item.
            ing.item_name = ing.category = None
        elif ing.item_name:
            # Fall back rather than drop it: an odd category is easy to fix,
            # a missing ingredient on shopping day is not.
            if ing.category not in known_cats:
                ing.category = "Pantry" if "Pantry" in known_cats else (categories[0] if categories else "Pantry")
    return recipe
