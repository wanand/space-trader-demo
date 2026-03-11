# Io Space Trading — Project Overview

## What Is This?

**Io Space Trading** is a desktop GUI client for the [SpaceTraders API](https://spacetraders.io/), a browser/REST-based space trading game. The application is written entirely in Python using `tkinter`/`ttk` for the GUI and the `requests` library for HTTP calls.

The player can register or log in as a SpaceTraders agent, browse factions, manage contracts and ships, navigate between shipyard waypoints, purchase new ships, and upgrade ships with equipment mounts — all from a single tabbed desktop window.

---

## File Structure

```
game/
├── main.py        Entry point; builds the window, all tabs, shared state, and context objects
├── navigation.py  Navigation tab — move ships between shipyard waypoints
├── shipyard.py    Shipyard tab — browse, buy ships, and install mounts
├── upgrade.py     Ship upgrade dialog — manage mounts (install, remove, transfer)
├── agents.json    Persisted agent name → token map (auto-created on first login)
docs/
├── overview.md    This file — how everything fits together
├── main.md        Detailed reference for main.py
├── navigation.md  Detailed reference for navigation.py
├── shipyard.md    Detailed reference for shipyard.py
├── upgrade.md     Detailed reference for upgrade.py
requrirements.txt  Python package dependencies
```

---

## Architecture

### Layered Design

The codebase uses a **three-layer architecture**:

```
┌──────────────────────────────────────────────────────┐
│                  UI Layer (tkinter)                  │
│  Tab frames, treeviews, buttons, dialogs, StringVars │
└────────────┬──────────┬──────────┬───────────────────┘
             │          │          │
      [UpgradeCtx] [ShipyardCtx] [NavigationCtx]
             │          │          │
┌────────────▼──────────▼──────────▼───────────────────┐
│               Business / Event Logic                  │
│  main.py functions + inner event handlers in modules  │
└────────────────────────┬─────────────────────────────┘
                         │  HTTP via `requests`
┌────────────────────────▼─────────────────────────────┐
│              SpaceTraders REST API v2                 │
│  https://api.spacetraders.io/v2/                     │
└──────────────────────────────────────────────────────┘
```

### Dependency Injection via Context Objects

Rather than sharing global state or having sub-modules import `main.py` (which would create circular imports), `main.py` constructs a **context dataclass** for each sub-module and passes it in at startup:

```
main.py
  │
  ├── creates UpgradeContext   ──▶  upgrade.py    (open_upgrade_dialog)
  ├── creates ShipyardContext  ──▶  shipyard.py   (build_shipyard_tab)
  └── creates NavigationContext──▶  navigation.py (build_navigation_tab)
```

Each context dataclass bundles:
- The `tk.Tk` root window (so sub-modules can create dialogs).
- The `request_headers` callable (for authentication).
- All relevant API URL constants.
- Any Tk variables or callbacks the module needs to update the main window (e.g., `player_worth_var`, `refresh_summary`).

This keeps each module **fully independent** — they can be developed and tested in isolation from `main.py`.

---

## Module Roles

| File | Role | Public API |
|---|---|---|
| `main.py` | Orchestrator — builds everything and wires it together | `root.mainloop()` (entry point) |
| `navigation.py` | Navigation tab feature module | `NavigationContext`, `build_navigation_tab()` |
| `shipyard.py` | Shipyard tab feature module | `ShipyardContext`, `build_shipyard_tab()` |
| `upgrade.py` | Mount upgrade modal dialog | `UpgradeContext`, `open_upgrade_dialog()` |

---

## Tab Overview

The main window has six tabs managed by a `ttk.Notebook`. Tabs that require authentication are disabled until the player logs in.

| Index | Tab Name | Auth Required | Module | Data Source |
|---|---|---|---|---|
| 0 | Welcome | No | `main.py` | Local (`agents.json`) + POST `/register` |
| 1 | Summary | Yes | `main.py` | `GET /my/agent`, `/my/contracts`, `/my/ships` |
| 2 | Leaderboard | Yes | `main.py` | `GET /` (server status) |
| 3 | Factions | No | `main.py` | `GET /factions`, `GET /agents` |
| 4 | Shipyard | Yes | `shipyard.py` | `GET /systems/.../waypoints`, `GET .../shipyard` |
| 5 | Navigation | Yes | `navigation.py` | `GET /my/ships`, `POST .../orbit`, `.../navigate` |

The **Upgrade Dialog** is not a tab — it is a modal window opened from the Summary tab by double-clicking a ship row.

---

## Authentication Flow

```
User opens app
     │
     ▼
Welcome tab
  ├── [Register new agent]
  │     POST /register (needs account-level token)
  │     → save to agents.json → show_agent_summary()
  │
  └── [Login] (select saved agent OR paste token)
        GET /my/agent  (validates token)
        → save to agents.json → show_agent_summary()
```

`show_agent_summary()` sets `player_token` (a `tk.StringVar`), enables all auth-required tabs, and switches to the Summary tab.

All authenticated API calls go through `request_headers(require_token=True)`, which reads `player_token`. If unset, it returns `None` and callers bail out early.

---

## Data Persistence

The only persistent data is `agents.json`, a JSON object mapping agent symbols to their bearer tokens:

```json
{
  "AGENT_NAME_1": "eyJhbGciOi...",
  "AGENT_NAME_2": "eyJhbGciOi..."
}
```

This file lives in the `game/` directory alongside the Python files. It is created on first login/registration and updated on every new successful authentication.

A `.env` file in the project root or `game/` folder can pre-populate `AGENT_TOKEN` and `ACCOUNT_TOKEN` so the player does not need to paste tokens manually.

---

## Tab Lifecycle and Refresh Strategy

Data is fetched **on demand** — only when a tab is activated. `main.py` binds the `<<NotebookTabChanged>>` event to `refresh_tabs()`, which dispatches to the correct refresh function:

```
Tab activated
     │
     ▼
refresh_tabs(event)
  │
  ├── Tab 1 → refresh_player_summary()   (agent, contracts, ships)
  ├── Tab 2 → refresh_leaderboard()      (credits + charts boards)
  ├── Tab 3 → refresh_factions()         (all factions + agent scoring)
  ├── Tab 4 → _shipyard_reload()         (ship dropdown only)
  └── Tab 5 → _navigation_reload()       (ship dropdown only)
```

For the Shipyard and Navigation tabs, only the **ship dropdown** is refreshed on tab activation. The heavier network operations (finding shipyards, loading shipyard details, fetching waypoints) are triggered explicitly by the player clicking buttons. This keeps tab switches fast.

---

## Key Patterns

### Lazy Faction Cache
`get_faction_lookups()` fetches all factions once and caches them in `FACTION_LOOKUPS`. Subsequent calls return the in-memory dict without another API request.

### Pagination Loop
The SpaceTraders API returns paginated results (20 items per page). Both `_find_shipyards()` (in `shipyard.py` and `navigation.py`) and `refresh_factions()` (in `main.py`) loop using the `meta.total` field until all pages are fetched:

```python
while True:
    resp = requests.get(url, params={"limit": 20, "page": page})
    results.extend(resp.json()["data"])
    if len(results) >= meta["total"] or not batch:
        break
    page += 1
```

### Mutable Closure State via Lists
Inner functions (event handlers) in Python closures cannot rebind outer-scope variables without `nonlocal`. To work around this cleanly, mutable state is stored in **single-element lists**:

```python
_current_system = [""]   # Inner functions update _current_system[0] = "X1-ABC"
_ship_data      = [None] # Inner functions update _ship_data[0] = {...}
```

This pattern appears consistently across `navigation.py`, `shipyard.py`, and `upgrade.py`.

### Auto-Orbit Before Navigate/Install
The SpaceTraders API requires ships to be `IN_ORBIT` before navigating and `DOCKED` at a shipyard before installing/removing mounts. Rather than requiring the player to manually transition states, the relevant event handlers check the current `nav.status` first and automatically send the prerequisite command:

- `on_navigate()` in `navigation.py` — orbits automatically if docked.
- `on_install()` in `shipyard.py` — docks automatically if in orbit.

### Live Credit Updates
After install, remove, and buy operations the API response includes the agent's updated credit balance. The modules push this directly to `ctx.player_worth_var` (a `tk.StringVar` bound to the Summary tab label), keeping the display accurate without a full tab refresh.

---

## Running the Application

```bash
cd game
python main.py
```

**Requirements** (see `requrirements.txt`):
- Python 3.10+ (uses `dict | None` union type hints)
- `requests`
- `tkinter` (ships with most Python distributions)

---

## SpaceTraders API Integration Summary

| Operation | HTTP Method | Endpoint |
|---|---|---|
| Server status / leaderboard | GET | `/` |
| List factions | GET | `/factions` |
| List agents | GET | `/agents` |
| Register new agent | POST | `/register` |
| Get my agent | GET | `/my/agent` |
| Get my contracts | GET | `/my/contracts` |
| Get my ships | GET | `/my/ships` |
| Buy a ship | POST | `/my/ships` |
| Get ship cargo | GET | `/my/ships/{sym}/cargo` |
| Get ship mounts | GET | `/my/ships/{sym}/mounts` |
| Install mount | POST | `/my/ships/{sym}/mounts/install` |
| Remove mount | POST | `/my/ships/{sym}/mounts/remove` |
| Orbit ship | POST | `/my/ships/{sym}/orbit` |
| Dock ship | POST | `/my/ships/{sym}/dock` |
| Navigate ship | POST | `/my/ships/{sym}/navigate` |
| Refuel ship | POST | `/my/ships/{sym}/refuel` |
| Transfer cargo | POST | `/my/ships/{sym}/transfer` |
| Get waypoints in system | GET | `/systems/{sys}/waypoints` |
| Get shipyard at waypoint | GET | `/systems/{sys}/waypoints/{wp}/shipyard` |
