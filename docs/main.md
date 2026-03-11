# main.py — Io Space Trading Game

## Overview

`main.py` is the **entry point** for the Io Space Trading desktop GUI application, built with Python's `tkinter`/`ttk` framework. It constructs the main window and all six tabs, manages application-level state (authentication token, faction cache, agent data), and wires together the three plug-in tab modules (`shipyard.py`, `navigation.py`, `upgrade.py`) via dependency-injected context objects.

**Key responsibilities:**
- Build and configure all six tab frames.
- Handle user registration, login, and logout against the SpaceTraders REST API.
- Provide shared infrastructure (`request_headers`, URL constants, date helpers, agent file I/O) consumed by the sub-modules.
- React to tab-switch events and refresh the correct data for each tab on demand.

---

## File Structure at a Glance

| Section | Lines | Purpose |
|---|---|---|
| Imports | 1–42 | Standard lib, third-party (`requests`, `tkinter`), local modules |
| File path / env constants | 43–62 | `AGENT_FILE`, `.env` candidates, token env key names |
| API URL constants | 63–90 | All SpaceTraders REST endpoint templates |
| Date format strings | 91–95 | UTC parse / display format strings |
| App-level state | 96–100 | Global caches (`FACTION_LOOKUPS`, `_faction_data`) |
| Env / .env helpers | 101–145 | `.env` loader, token getters |
| Date helpers | 146–170 | `parse_datetime`, `format_datetime` |
| Agent file helpers | 171–250 | `load_player_logins`, `store_agent_login` |
| Auth header builder | 251–290 | `request_headers` |
| Faction helpers | 291–500 | `get_faction_lookups`, `refresh_factions`, `on_faction_select` |
| Combobox helpers | 501–540 | `generate_faction_combobox`, `generate_login_combobox`, `show_agent_summary` |
| Registration / Login / Logout | 541–660 | `register_agent`, `login_agent`, `logout_agent` |
| Tab switching | 661–700 | `refresh_tabs` |
| Summary tab data | 701–830 | `refresh_player_summary`, `display_clicked_contract`, `display_clicked_ship` |
| Leaderboard | 831–865 | `refresh_leaderboard` |
| UI construction | 866–1307 | All widget and context-object declarations |

---

## Constants

### API URL Constants
All SpaceTraders v2 endpoint templates. `{}` placeholders are filled with `.format()`.

| Constant | Purpose |
|---|---|
| `API_STATUS` | GET server status + leaderboard data |
| `LIST_FACTIONS` | GET all factions (public) |
| `FACTION_DETAIL` | GET a single faction by symbol |
| `LIST_AGENTS` | GET public agent profiles (used for faction scoring) |
| `CLAIM_USER` | POST register a new agent |
| `MY_ACCOUNT` | GET the logged-in agent's details |
| `MY_CONTRACTS` | GET the agent's active contracts |
| `MY_SHIPS` | GET the agent's ships / POST buy a new ship |
| `SHIP_MOUNTS` | GET mounts on a specific ship |
| `SHIP_CARGO` | GET cargo inventory of a specific ship |
| `SHIP_INSTALL_MOUNT` | POST install a mount from cargo |
| `SHIP_REMOVE_MOUNT` | POST remove a mount into cargo |
| `SHIP_ORBIT` | POST move a ship into orbit |
| `SHIP_DOCK` | POST dock a ship at a waypoint |
| `SHIP_NAVIGATE` | POST navigate a ship to a waypoint |
| `SHIP_REFUEL` | POST refuel a ship |
| `SHIP_TRANSFER` | POST transfer cargo between ships |
| `SHIPYARD` | GET shipyard details for a waypoint |
| `SYSTEM_WAYPOINTS` | GET all waypoints in a system |

---

## Global State

| Variable | Type | Purpose |
|---|---|---|
| `FACTION_LOOKUPS` | `dict` | Cache of `{symbol: name}` for all factions |
| `_faction_data` | `dict` | Cache of `{symbol: full_faction_dict}` for the Factions detail panel |
| `player_token` | `tk.StringVar` | Bearer token for the currently logged-in agent |
| `player_login` | `tk.StringVar` | Display name of the logged-in agent |
| `player_faction` | `tk.StringVar` | Starting faction name of the agent |
| `player_worth` | `tk.StringVar` | Agent's current credit balance (formatted) |

---

## Functions

### `load_dotenv_if_present()`
Scans two candidate paths (`project root/.env` and `game/.env`) and, for each file found, reads `KEY=VALUE` lines and sets them in `os.environ` via `setdefault` (existing env vars are never overwritten). Lines starting with `#` and lines without `=` are skipped. Supports `export KEY=VALUE` syntax and strips surrounding quotes from values.

---

### `get_env_token()`
Returns the value of the `AGENT_TOKEN` environment variable (populated by `.env` loading or OS), or an empty string if not set.

---

### `get_account_token()`
Returns the best available account-level token in priority order:
1. The `account_token_var` Tk variable (from the Welcome tab text field).
2. The `ACCOUNT_TOKEN` environment variable.
3. Falls back to `get_env_token()`.

---

### `parse_datetime(dt)`
Parses a SpaceTraders ISO-8601 timestamp string (e.g. `"2024-01-15T08:30:00.000Z"`) into a Python `datetime` object using `UTC_FORMAT`.

---

### `format_datetime(dt_text)`
Converts a raw SpaceTraders timestamp into a human-friendly string like `"15th January, 2024"`. Computes the ordinal suffix (st/nd/rd/th) using a small lookup dict with a modulo fallback for `th`.

---

### `load_player_logins()`
Reads `agents.json` and returns a `dict` of `{agent_symbol: token}`. Returns `{}` if the file does not exist, cannot be read, or contains invalid JSON. Validates that both keys and values are non-empty strings before including them.

---

### `store_agent_login(json_result)`
Saves an agent's symbol and token to `agents.json`. Merges the new entry with any existing entries so previously saved agents are preserved. Silently returns if the symbol or token is missing/invalid.

---

### `request_headers(require_token=False, token=None)`
Builds and returns the HTTP headers dict `{"Accept": "application/json", "Authorization": "Bearer <token>"}`. Token is resolved in this order:
1. The explicit `token` argument.
2. The `player_token` Tk variable.
3. The `AGENT_TOKEN` environment variable.

If `require_token=True` and no token is found, returns `None` and prints a warning so callers can bail out early.

---

### `get_faction_lookups()`
Returns a `{symbol: name}` dict for all SpaceTraders factions. Fetches from the API on first call and caches the result in `FACTION_LOOKUPS` for subsequent calls.

---

### `refresh_factions()`
Three-step function triggered when the user switches to the Factions tab:
1. Fetches all factions from the API (all pages).
2. Fetches all public agents (all pages) and aggregates per-faction statistics: agent count, total credits, total ships.
3. Attaches the computed stats to each faction dict, sorts factions by agent count descending, and repopulates the faction treeview. The player's own faction is highlighted in blue.

---

### `on_faction_select(event=None)`
Event handler for clicking a row in the faction treeview. Looks up the clicked faction symbol in `_faction_data` and populates the detail text widget with: name, symbol, headquarters, recruiting status, description, reputation scores (agent count, credit totals, averages), and faction traits.

---

### `generate_faction_combobox()`
Populates the faction dropdown on the Welcome tab with sorted faction names. Called lazily by the combobox's `postcommand` so factions are only fetched when the dropdown is opened.

---

### `generate_login_combobox()`
Populates the login dropdown with agent names loaded from `agents.json`, sorted case-insensitively.

---

### `show_agent_summary(json_result)`
Called after a successful login or registration. Updates the Tk variables (`player_token`, `player_login`, `player_faction`, `player_worth`), re-enables the auth-required tabs (Summary, Leaderboard, Shipyard, Navigation), disables the Welcome tab, and switches the view to the Summary tab.

---

### `register_agent()`
Registers a brand-new agent:
1. Reads the agent name from the Welcome form.
2. Looks up the account token via `get_account_token()`.
3. Reverse-maps the selected faction name back to its symbol.
4. POSTs to `CLAIM_USER`.
5. On success, saves the token to `agents.json` and calls `show_agent_summary()`.

---

### `login_agent()`
Logs in as an existing agent:
- If a saved agent is selected from the dropdown, looks up their token from `agents.json`.
- Otherwise treats the dropdown text as a raw token string.
- Falls back to the env token if nothing else is available.
- GETs `MY_ACCOUNT` to validate the token and fetch agent details.
- Saves the agent/token pair for future runs if it was a new token (not already in agents.json).

---

### `logout_agent()`
Clears `player_token` and `player_login`, disables all auth-required tabs (Summary, Leaderboard, Shipyard, Navigation), and switches back to the Welcome tab.

---

### `refresh_tabs(event)`
Bound to the `<<NotebookTabChanged>>` event. Dispatches to the correct refresh function depending on which tab index is now selected:
- Tab 1 → `refresh_player_summary()`
- Tab 2 → `refresh_leaderboard()`
- Tab 3 → `refresh_factions()`
- Tab 4 → `_shipyard_reload()`
- Tab 5 → `_navigation_reload()`

---

### `refresh_player_summary(*args)`
Refreshes all data on the Summary tab:
1. GETs `MY_ACCOUNT` and updates `player_worth`.
2. GETs `MY_CONTRACTS` and repopulates the contracts treeview. Uses `zip_longest` to pair multiple deliver items onto child rows.
3. GETs `MY_SHIPS` and repopulates the ships treeview. Extra modules and mounts beyond the first are added as collapsible child rows under each ship row.

---

### `display_clicked_contract(*args)`
Placeholder handler for double-clicking a contract row. Currently prints debug info to the console; no dialog is implemented yet.

---

### `display_clicked_ship(*args)`
Called when the player double-clicks a row in the ships treeview. Reads the focused row's `iid`; ignores sub-rows (those containing `#`). For top-level ship rows, calls `open_upgrade_dialog(iid, upgrade_ctx)` to open the mount upgrade dialog.

---

### `refresh_leaderboard(*args)`
Fetches the server status endpoint (`API_STATUS`), which returns two leaderboards:
- `mostCredits` — top agents by total credits.
- `mostSubmittedCharts` — top agents by chart submission count.

Populates both treeviews with rank, agent symbol, and score. No token required.

---

## UI Construction

The bottom third of `main.py` (roughly lines 866–1307) is procedural UI code that creates all the widgets. Key sections:

| Block | Contents |
|---|---|
| Root window | `tk.Tk()`, main `ttk.Frame`, `ttk.Notebook` with 6 tab frames |
| Welcome tab | Register panel (name, faction, account token) + Login panel (agent dropdown) |
| Summary tab | Agent info panel, Contracts treeview, Ships treeview |
| Leaderboard tab | Two treeviews (credits, charts) + Refresh button |
| Factions tab | Left treeview of all factions + right detail text widget + status bar |
| Context objects | `UpgradeContext`, `ShipyardContext`, `NavigationContext` — bundle URLs + helpers and pass to sub-modules |
| App start | `root.mainloop()` hands off to tkinter's event loop |

---

## Context Injection Pattern

Rather than having sub-modules import `main.py` directly (which would create circular imports), `main.py` constructs a **context dataclass** for each module and passes it in:

```
main.py  ──[UpgradeContext]──▶  upgrade.py
         ──[ShipyardContext]──▶ shipyard.py
         ──[NavigationContext]▶ navigation.py
```

Each context carries:
- The `tk.Tk` root window (for creating dialogs).
- The `request_headers` callable.
- All relevant URL constants.
- Any Tk variables or callbacks the module needs to update the main window.
