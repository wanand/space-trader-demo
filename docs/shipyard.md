# shipyard.py — Shipyard Browser Tab

## Overview

`shipyard.py` provides the **Shipyard tab** of the Io Space Trading GUI. It allows the player to explore shipyards within their ship's current star system, view ship listings and available mounts, purchase new ships, and install mounts from cargo.

Like `navigation.py`, the module is self-contained: it receives all external dependencies via a `ShipyardContext` dataclass and exposes one public function — `build_shipyard_tab()` — which builds the UI and returns a `reload()` callable.

> **API limitation note:** The SpaceTraders API only returns full shipyard details (prices, full mount list) when one of your ships is physically present at the waypoint. If no ship is present, the tab shows limited information and explains why.

---

## Player Workflow

1. **Pick a ship** from the dropdown — this determines which system to search.
2. **Click "Search Shipyards in System"** — the left panel fills with all shipyard waypoints in the system.
3. **Click a waypoint** — the right panel loads full details: modification fee, mounts found on ships sold here, and the list of ships for sale.
4. **Select a ship for sale** and click **"Buy Ship"** to purchase it (requires one of your ships to be present at the waypoint).
5. If one of your ships is at the waypoint and has `MOUNT_` items in its cargo, use the **"Install Mount from Cargo"** panel to install them onto that ship.

---

## Module Structure

| Section | Purpose |
|---|---|
| `ShipyardContext` dataclass | Holds all URLs and helpers injected from `main.py` |
| API helpers (`_get_*`, `_find_*`, `_buy_*`, etc.) | One function per type of network request |
| `build_shipyard_tab()` | Builds all widgets; all event handlers are inner functions |

---

## `ShipyardContext` Dataclass

| Field | Type | Description |
|---|---|---|
| `root` | `tk.Tk` | Main application window |
| `request_headers` | `Callable` | Returns `{"Authorization": "Bearer <token>"}` or `None` |
| `my_ships_url` | `str` | GET player ships / POST buy a ship |
| `system_waypoints_url` | `str` | GET waypoints in a system (with `traits=SHIPYARD` filter) |
| `shipyard_url` | `str` | GET full shipyard details for a specific waypoint |
| `ship_cargo_url` | `str` | GET a ship's cargo inventory |
| `ship_mounts_url` | `str` | GET mounts installed on a ship |
| `ship_install_mount_url` | `str` | POST install a mount from cargo |
| `ship_dock_url` | `str` | POST dock a ship |

---

## API Helper Functions

### `_get_my_ships(ctx: ShipyardContext) -> list`
Fetches all player ships via `GET /my/ships?limit=20`. Returns the `data` list or `[]` on any failure.

---

### `_find_shipyards(system_symbol: str, ctx: ShipyardContext) -> tuple[list | None, str | None]`
Finds all `SHIPYARD`-trait waypoints in a given system. Handles pagination automatically (20 results per page, loops using `meta.total`). Returns:
- `(list_of_waypoint_dicts, None)` on success.
- `(None, error_string)` on failure.

---

### `_get_shipyard_detail(system: str, waypoint: str, ctx: ShipyardContext) -> tuple[dict | None, str | None]`
Fetches full details for a single shipyard via `GET /systems/{system}/waypoints/{waypoint}/shipyard`. Returns `(data_dict, None)` or `(None, error_string)`. Full details (prices, mounts) are only returned when one of the player's ships is at the waypoint.

---

### `_buy_ship(ship_type: str, waypoint_symbol: str, ctx: ShipyardContext) -> tuple[dict | None, str | None]`
Purchases a ship by POSTing `{"shipType": ship_type, "waypointSymbol": waypoint_symbol}` to `/my/ships`. Returns the result dict (containing the new ship and updated agent credits) or an error message. One of the player's ships must be present at the waypoint.

---

### `_get_ship_cargo_mounts(ship_symbol: str, ctx: ShipyardContext) -> list`
Fetches a ship's cargo inventory and filters it to only items whose symbol starts with `"MOUNT_"`. Returns a list of matching cargo item dicts, or `[]` on failure.

---

### `_dock_ship(ship_symbol: str, ctx: ShipyardContext) -> tuple[dict | None, str | None]`
Docks the ship at its current waypoint via `POST /my/ships/{symbol}/dock`. Returns `(data, error)`.

---

### `_install_mount(ship_symbol: str, mount_symbol: str, ctx: ShipyardContext) -> tuple[dict | None, str | None]`
Installs a mount from the ship's cargo onto the ship via `POST /my/ships/{symbol}/mounts/install`. The ship must be DOCKED at a shipyard. Returns `(data, error)` on HTTP 201.

---

## `build_shipyard_tab(parent, ctx) -> Callable`

The main tab builder. Constructs all widgets, defines all event handlers as inner closures, and returns `reload_ships`.

### Shared Mutable State

| Variable | Type | Purpose |
|---|---|---|
| `_waypoints` | `list` | Shipyard waypoints found in the last search |
| `_current_system` | `list[str]` | System symbol of the currently selected ship |
| `_ships_for_sale` | `list` | Full ship dicts from the last shipyard detail fetch |
| `_cur_waypoint` | `list[str]` | Symbol of the currently selected waypoint |
| `_install_ships` | `list` | Player's ships currently at the selected waypoint |
| `_cargo_mounts` | `list` | `MOUNT_` items in the selected install-ship's cargo |

### Widget Layout

```
┌─ Top bar ──────────────────────────────────────────────────────────────────┐
│  Ship: [dropdown]   [Search Shipyards in System]   [status label]          │
└────────────────────────────────────────────────────────────────────────────┘
┌─ Shipyards Found ──────┐  ┌─ Shipyard Details ──────────────────────────────┐
│  Waypoint    Type      │  │  [Mounts info text area]                         │
│  ──────────────────    │  │                                                  │
│  X1-DF55-A1  ORBITAL   │  ├─ Ships for Sale ────────────────────────────────┤
│  X1-DF55-B2  MOON      │  │  Type         Name         Price (credits)       │
│  ...                   │  │  ─────────────────────────────────────────────   │
│                        │  │  SHIP_PROBE   Probe Core   25,000                │
│                        │  │  [🛒 Buy Selected Ship]                          │
│                        │  ├─ Install Mount from Cargo ──────────────────────┤
│                        │  │  Ship at waypoint: [dropdown]  [↻]               │
│                        │  │  Mounts in cargo:  [listbox]                     │
│                        │  │  [⬇ Install Selected Mount]                      │
└────────────────────────┘  └─────────────────────────────────────────────────┘
```

### Inner Helper Functions

#### `_set_detail(lines: list)`
Replaces the entire contents of the detail text widget with a new set of lines. `lines` is a list of `(text, tag_name_or_None)` tuples. Temporarily enables the widget (it is read-only by default), writes all content, then disables it again.

#### `_populate_ships_tree(ships: list, show_types_only: bool = False)`
Fills the "Ships for Sale" treeview. In normal mode, displays type, name, and formatted price for each ship. If `show_types_only=True` (no player ship at waypoint), only type codes are shown and prices appear as `"unknown"`.

#### `_refresh_install_ships()`
Rebuilds the "Ship at waypoint" dropdown by fetching all player ships and filtering to those whose `nav.waypointSymbol` matches `_cur_waypoint[0]`. If ships are found, auto-selects the first and triggers `_on_install_ship_change()`. Shows an informative message if no ships are at the waypoint.

#### `_on_install_ship_change(*_)`
Called whenever the install-ship picker selection changes (and also via `inst_ship_var.trace_add("write", ...)`). Extracts the ship symbol from the label, fetches its `MOUNT_` cargo items via `_get_ship_cargo_mounts()`, and populates the cargo listbox.

#### `_selected_system() -> str`
Extracts the system symbol from the ship combobox label `"SHIP-SYM  (SYSTEM)"` by finding the substring between `(` and `)`.

#### `_build_detail_lines(data: dict, waypoint_symbol: str) -> list`
Turns a shipyard data dict into a `(text, tag)` list for the detail text widget. Displays:
- Waypoint name as a heading.
- Modification fee in credits.
- All unique mount symbols found across all ships for sale, with names and truncated descriptions (≤90 chars).
- An explanatory note that these mounts are pre-installed on ships, not sold separately.

#### `_update_buy_btn(*_)`
Enables the Buy button only when a ship row is selected and `_ships_for_sale` is non-empty (meaning price data is available).

#### `_update_install_btn(*_)`
Enables the Install button only when a cargo mount is selected in the listbox and `_cargo_mounts` is non-empty.

---

### Event Handler Inner Functions

#### `reload_ships()`
Fetches all player ships and rebuilds the ship dropdown. Called by `main.py` on every tab activation (stored as `_shipyard_reload`). Does not auto-select or trigger a search — the player must click Search.

#### `on_search()`
Triggered by "Search Shipyards in System". Extracts the system from the ship dropdown label, calls `_find_shipyards()`, and populates the left waypoints treeview. Updates `_current_system[0]`.

#### `on_waypoint_select()`
Fired when the player clicks a waypoint row. Calls `_get_shipyard_detail()` and:
1. Populates the detail text widget via `_build_detail_lines()`.
2. Fills the Ships for Sale treeview (full details if available, types-only otherwise).
3. Refreshes the "Install Mount from Cargo" panel via `_refresh_install_ships()`.

If the detail fetch fails (e.g., no ship present), shows an informative error in the detail text area explaining the API limitation.

#### `on_buy()`
Handles the "Buy Ship" button:
1. Looks up the ship's full name and price from `_ships_for_sale`.
2. Shows a confirmation dialog (`messagebox.askyesno`) with name, type, waypoint, and price.
3. On confirmation, calls `_buy_ship()`.
4. On success, displays the new ship symbol and updated credit balance, then calls `reload_ships()` and `_refresh_install_ships()` so the new ship appears immediately.

#### `on_install()`
Handles the "Install Selected Mount" button:
1. Reads the selected mount symbol and ship from the UI.
2. Checks the ship's `nav.status`; if not `DOCKED`, automatically calls `_dock_ship()` first.
3. Calls `_install_mount()`.
4. On success, refreshes the cargo listbox to reflect the consumed mount item.

---

## Return Value

`build_shipyard_tab()` returns the `reload_ships` inner function. `main.py` stores it as `_shipyard_reload` and calls it when the user switches to the Shipyard tab (index 4).
