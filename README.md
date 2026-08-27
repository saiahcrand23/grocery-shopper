# Grocery Shopper

A single-file grocery ordering app. Everything is in `index.html` — no build step, no server, no dependencies. Open it and it works.

## Putting it on her phone

1. Push this repo to GitHub.
2. **Settings → Pages → Source: Deploy from a branch → `main` / root.** GitHub gives you a URL like `https://<you>.github.io/grocery-shopper/`.
3. Open that URL in **Safari** on her iPhone.
4. Tap the Share button → **Add to Home Screen**.

Step 4 matters more than it looks. Safari will auto-clear a normal website's stored data after about 7 days without a visit — which would wipe the list and the order history. Once it's on the Home Screen, iOS treats it as an installed app and stops doing that. It also drops the Safari chrome, so it looks and feels like a real app.

## Using it

**Shop** — All 85 items grouped by category. Tap an item to check it off. Tap the store pill on the right to change where it's bought. The chip strip at the top jumps to a category; the search box filters everything.

**Order** — Everything currently checked, split by store, with a quantity stepper on each row. "Move" changes the store for this order only, without touching the item's normal default. **Finalize order** saves the whole thing to History with today's date and clears the checkboxes.

**History** — Every finalized order, newest first. Tap one to see what was in it.

**Manage** — Add items, rename them, change their default store, delete them. Also where backup lives.

## Stores

Wal-Mart, Sam's Club, Produce Store. Each item has a default store, so checking it off automatically files it under the right one — the per-order "Move" is only for one-off changes.

## Backup

All data lives in the phone's local storage, which means it's per-device and doesn't sync. Home Screen install protects against the routine case; it does not protect against a new phone or deleting the app.

So: **Manage → Export backup** every so often. That writes a `.json` file with the full inventory, the current list, and all order history. "Copy backup to clipboard" is the fallback if the download is awkward on iOS. **Import backup** restores from one — that's also how you'd move everything to a new phone.

## Order history

Finalizing an order records each line as `{ item, category, store, quantity, timestamp }`. Nothing reads that yet, but it's recorded from day one on purpose — it's the raw material for the "how often do we actually buy this" features later. The longer it runs, the more useful it gets.

## Editing the inventory in bulk

The starting list came from `inventory.xlsx`. For a handful of changes, use the Manage tab. For a large restructuring, edit the `SEED` object near the top of the `<script>` in `index.html` — but note that **Manage → Reset to the original inventory** is what re-reads `SEED`, and it wipes current data, so export a backup first.
