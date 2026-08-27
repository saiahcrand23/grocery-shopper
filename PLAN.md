## Overview
An `index.html` grocery ordering app for my wife, stored in GitHub. It holds an inventory of the items we commonly buy at the store, organized by category, and lets her check off what we need to order for the week.

## Problem
Help my wife not forget to order anything on her grocery pickup order.

## Stores
- Wal-Mart
- Sam's Club
- Produce Store

## Data Model
- **Inventory**: category, item name, **editable default store** per item — auto-sorts the item into that store's list, but overridable on a per-order basis.
- **Order history**: timestamp, item, store, quantity — logged whenever a week's order is finalized. This is the foundation the future "learning" capability will read from, so it needs to start being recorded from v1 even though nothing uses it yet.

## Status
**v1 is built** — see `index.html` (single file, no dependencies) and `README.md` for setup. Everything under "v1 (MVP) Capabilities" below is implemented. Seeded with all 85 items / 13 categories from `inventory.xlsx`.

## v1 (MVP) Capabilities
- Easy scrolling through categories and items, optimized for iPhone.
- Each item has an editable default store; checking it off sorts it into that store's list on the order tab, overridable per order.
- Check off items needed for the week.
- Secondary tab showing all checked items, separated per store.
- "Finalize order" action that timestamps and logs the finalized list (item, store, quantity) to order history.
- Static single-file `index.html`, no backend — data persisted client-side (localStorage).
- **Data durability**, since localStorage alone is fragile (Safari can auto-clear a site's storage after ~7 days of no visits, and a new phone or cleared browsing data wipes it outright):
  - Prompt/instruct her to **Add to Home Screen** on her iPhone — Safari treats a home-screen web app as installed and exempts it from that auto-clearing, at low implementation cost (manifest + meta tags).
  - An in-app **JSON import/export**, read-only for v1: export current state (inventory, checked items, order history) to a JSON file for backup, and import a JSON file to load/restore inventory or state. No live/automatic connection to Drive or any API — purely manual file-based, so there's no write-back to worry about.

## Future Capabilities (Backlog)
- Learn our purchasing patterns (how often we buy an item, where, how many per trip) from the order history logged in v1.
- Manual export/import of purchase history from store accounts, if feasible, to help train the pattern-learning.
- Hook directly into grocery store account purchase history (Walmart, Sam's Club) to feed the learning — **no public API exists for this today**; revisit only if that changes.
- Auto-add items to store carts (Walmart, Sam's Club) — likely requires browser automation, which carries real ToS-violation / account-ban risk on these sites. An app called Meal Lime reportedly did something similar for Fry's/Kroger. Back burner; only pursue if a legitimate integration path turns up.
- Full read/write Drive sync (OAuth) so in-app edits to inventory persist back to the shared Drive file automatically, if read-only pull + local edits proves too limiting.

## Tech Notes
- Single static `index.html` file, hosted from the GitHub repo (GitHub Pages is a natural fit).
- Client-side only for v1 — no server/backend.
