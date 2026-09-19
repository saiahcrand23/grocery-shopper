import base64
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
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
        "SELECT id, name, category, default_store, staple, updated_at FROM items WHERE deleted_at IS NULL"
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
        """SELECT id, title, instructions, minutes, cost, healthy, health_notes
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
        if body.staple is None:
            prev = conn.execute("SELECT staple FROM items WHERE id=?", (item_id,)).fetchone()
            staple = prev["staple"] if prev else 0
        else:
            staple = int(body.staple)
        conn.execute(
            """
            INSERT INTO items (id, name, category, default_store, staple, updated_at, deleted_at)
            VALUES (?, ?, ?, ?, ?, ?, NULL)
            ON CONFLICT(id) DO UPDATE SET
              name=excluded.name, category=excluded.category,
              default_store=excluded.default_store, staple=excluded.staple,
              updated_at=excluded.updated_at, deleted_at=NULL
            """,
            (item_id, body.name, body.category, body.default_store, staple, ts),
        )
        row = conn.execute("SELECT id, name, category, default_store, staple, updated_at FROM items WHERE id=?", (item_id,)).fetchone()
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
            INSERT INTO recipes (id, title, instructions, minutes, cost, healthy, health_notes, updated_at, deleted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
            ON CONFLICT(id) DO UPDATE SET
              title=excluded.title, instructions=excluded.instructions, minutes=excluded.minutes,
              cost=excluded.cost, healthy=excluded.healthy, health_notes=excluded.health_notes,
              updated_at=excluded.updated_at, deleted_at=NULL
            """,
            (recipe_id, body.title, body.instructions, body.minutes, body.cost,
             int(body.healthy), body.health_notes, ts),
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


class ExtractedRecipe(BaseModel):
    title: str
    instructions: str
    minutes: Optional[int] = None
    cost: Optional[int] = None
    healthy: bool
    health_notes: str
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
- `ingredients[].text` is the ingredient exactly as written, quantity included.
- `ingredients[].item_id` links to the household's grocery inventory. Use an id
  from the supplied list when the ingredient is clearly that item; otherwise
  null. Never invent an id. A rough match is fine (mozzarella -> a shredded
  cheese item); a wrong one is worse than null, since null just asks the user."""


def _extract_blocks(text: Optional[str], upload_bytes: Optional[bytes], media_type: Optional[str]):
    if upload_bytes is None:
        return [{"type": "text", "text": f"Extract the recipe from this text:\n\n{text}"}]
    data = base64.standard_b64encode(upload_bytes).decode("utf-8")
    if media_type == "application/pdf":
        block = {"type": "document",
                 "source": {"type": "base64", "media_type": "application/pdf", "data": data}}
    else:
        block = {"type": "image",
                 "source": {"type": "base64", "media_type": media_type, "data": data}}
    # Document/image first, instruction after — the documented ordering.
    return [block, {"type": "text", "text": "Extract the recipe from this file."}]


@app.post("/api/recipes/extract")
async def extract_recipe(text: Optional[str] = Form(None), file: Optional[UploadFile] = File(None)):
    # Input is validated before the key check so a bad file reports what's
    # actually wrong with it rather than a generic configuration message.
    upload_bytes = media_type = None
    if file is not None:
        media_type = (file.content_type or "").lower()
        if media_type not in IMAGE_TYPES and media_type != "application/pdf":
            raise HTTPException(status_code=415,
                                detail=f"Can't read {media_type or 'that file type'}. Upload a PDF or an image.")
        upload_bytes = await file.read()
        if len(upload_bytes) > MAX_UPLOAD_BYTES:
            mb = len(upload_bytes) / 1024 / 1024
            raise HTTPException(status_code=413,
                                detail=f"That file is {mb:.0f}MB. The limit is 20MB — try a smaller export or a photo of the page.")
        if media_type == "image/jpg":
            media_type = "image/jpeg"
    elif not (text or "").strip():
        raise HTTPException(status_code=400, detail="Provide recipe text or a file.")

    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise HTTPException(status_code=503,
                            detail="Recipe extraction isn't configured on the server. Enter the recipe manually.")

    with get_conn() as conn:
        inventory = [{"id": r["id"], "name": r["name"], "category": r["category"]} for r in conn.execute(
            "SELECT id, name, category FROM items WHERE deleted_at IS NULL ORDER BY category, name")]

    import anthropic
    client = anthropic.Anthropic()
    try:
        response = client.messages.parse(
            model="claude-opus-5",
            max_tokens=16000,
            output_config={"effort": "low"},  # extraction is mechanical; raise if results disappoint
            system=EXTRACT_SYSTEM,
            messages=[
                {"role": "user", "content": [{"type": "text",
                 "text": "Grocery inventory to link ingredients against:\n" +
                         "\n".join(f"{i['id']} = {i['name']} ({i['category']})" for i in inventory)}]},
                {"role": "user", "content": _extract_blocks(text, upload_bytes, media_type)},
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
    # Never trust a returned id: a hallucinated one would silently attach an
    # ingredient to the wrong grocery item.
    valid = {i["id"] for i in inventory}
    for ing in recipe.ingredients:
        if ing.item_id not in valid:
            ing.item_id = None
    return recipe
