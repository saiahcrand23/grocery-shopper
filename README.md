# Grocery Shopper

A single-file grocery ordering app. Everything is in `index.html` — no build step, no server, no dependencies. Open it and it works.

## Putting it on your phone

1. Push this repo to GitHub.
2. **Settings → Pages → Source: Deploy from a branch → `main` / root.** GitHub gives you a URL like `https://<you>.github.io/grocery-shopper/`.
3. Open that URL in **Safari** on the iPhone that will use it.
4. Tap the Share button → **Add to Home Screen**.

Step 4 matters more than it looks. Safari will auto-clear a normal website's stored data after about 7 days without a visit — which would wipe the list and the order history. Once it's on the Home Screen, iOS treats it as an installed app and stops doing that. It also drops the Safari chrome, so it looks and feels like a real app.

## Using it

**Shop** — All 90 items grouped by category. Tap an item to check it off. Tap the store pill on the right to change where it's bought. The chip strip at the top jumps to a category; the search box filters everything.

**Order** — Everything currently checked, split by store, with a quantity stepper on each row. "Move" changes the store for this order only, without touching the item's normal default. **Finalize order** saves the whole thing to History with today's date and unchecks the boxes. **Uncheck everything** does the same unchecking without saving anything.

Neither of those buttons removes items from your inventory — the only way an item leaves the list is Delete on the Manage tab.

**History** — Every finalized order, newest first. Tap one to see what was in it.

**Manage** — Add items, rename them, change their default store, delete them. Also where backup lives.

## Stores

Wal-Mart, Sam's Club, Produce Store. Each item has a default store, so checking it off automatically files it under the right one — the per-order "Move" is only for one-off changes.

## Backup

All data lives in the phone's local storage, which means it's per-device and doesn't sync. Home Screen install protects against the routine case; it does not protect against a new phone or deleting the app.

So: **Manage → Export backup** every so often. That writes a `.json` file with the full inventory, the current list, and all order history. "Copy backup to clipboard" is the fallback if the download is awkward on iOS. **Import backup** restores from one — that's also how you'd move everything to a new phone.

## Order history

Finalizing an order appends one entry to `history`: a timestamp plus a line per item, each recording `{ id, name, category, store, quantity }`.

Lines are deliberately both linked and denormalized. The `id` points back to the item, so renaming something later keeps its history as one continuous record instead of splitting it in two. The `name`, `category`, and `store` are stored as copies of the strings at the time of the order, so a past order still reads correctly even after that item is renamed or deleted — and the store is saved by name, not by position, so reordering the store list can't silently re-attribute old orders.

Nothing reads any of this yet. It's recorded from day one on purpose — it's the raw material for the "how often do you actually buy this" features later, and history can't be backfilled.

## Editing the inventory in bulk

The app ships with an example starting list (from `inventory.xlsx`), which lives in the `SEED` object near the top of the `<script>` in `index.html`. Replace it with your own to change what a fresh install begins with.

**`SEED` is only read on a phone that has never opened the app before.** After first use, the list lives in that phone's storage, and editing `SEED` will not push new items to it — that's deliberate, so a code change can never overwrite or delete what someone has built up.

So once it's live, add items one of two ways:

- **Manage tab**, on the phone itself. Best for a few items.
- **Export → edit the `.json` → Import.** Best for a big batch. The exported file has the full item list in it; add entries and import it back.

Edit `SEED` itself only for changing what a brand-new install starts with.
