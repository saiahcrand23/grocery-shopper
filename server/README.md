# Grocery Shopper — sync server

A small FastAPI service backing the shared inventory, live shared cart, and order history described in `../PLAN2.0.md`. This is step 2 of that plan: a LAN-only server, not yet wired to `index.html`.

## Why the venv and DB live outside this folder

This repo is under Google Drive sync. A SQLite file getting partially synced mid-write is a real corruption risk, and a venv is thousands of pointless files for Drive to churn on. So:

- Database: `~/grocery-shopper-data/grocery.db` (override with `GROCERY_DB_PATH`)
- Virtualenv: `~/.venvs/grocery-shopper/`

Only this `server/` folder's source code is tracked in git and synced via Drive.

## First-time setup

```bash
mkdir -p ~/grocery-shopper-data
python3 -m venv ~/.venvs/grocery-shopper
~/.venvs/grocery-shopper/bin/pip install -r requirements.txt
```

## Run it manually (for testing)

From this `server/` directory:

```bash
~/.venvs/grocery-shopper/bin/uvicorn main:app --host 0.0.0.0 --port 8000
```

`--host 0.0.0.0` makes it reachable from other devices on the same LAN at `http://<this-machine's-LAN-IP>:8000` — find that IP with `hostname -I`. Nothing here is exposed beyond the LAN; there's no port forwarding, tunnel, or auth yet (that's step 6 in `PLAN2.0.md`).

## Run it as a persistent service (systemd --user)

So it survives closing the terminal and reboots, without root:

```bash
systemctl --user enable --now grocery-server
loginctl enable-linger "$USER"   # starts the user service at boot even with no active login
```

See the unit file at `~/.config/systemd/user/grocery-server.service`.

Logs: `journalctl --user -u grocery-server -f`

## API

See `../PLAN2.0.md` and the route definitions in `main.py`. Quick smoke test:

```bash
curl localhost:8000/api/health
curl -X PUT localhost:8000/api/categories/Dairy
curl -X PUT localhost:8000/api/items/dairy_milk -H 'content-type: application/json' \
  -d '{"name":"Milk","category":"Dairy","default_store":0}'
curl localhost:8000/api/state
curl -X PUT localhost:8000/api/checked/dairy_milk -H 'content-type: application/json' -d '{"qty":2}'
curl localhost:8000/api/checked
curl -X POST localhost:8000/api/orders -H 'content-type: application/json' \
  -d '{"id":"test-order-1","lines":[{"item_id":"dairy_milk","name":"Milk","category":"Dairy","store":"Wal-Mart","qty":2}]}'
curl localhost:8000/api/checked   # should be empty now
curl localhost:8000/api/orders
```
