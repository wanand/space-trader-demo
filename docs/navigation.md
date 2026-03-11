# navigation.py — Navigation Tab

## Overview

`navigation.py` provides the **Navigation tab** of the Io Space Trading GUI. It lets the player move their ships between shipyard waypoints within the same star system.

The module is entirely self-contained: it receives all external dependencies through a `NavigationContext` dataclass injected by `main.py` at startup, and exposes a single public function — `build_navigation_tab()` — which constructs the tab's widgets and returns a `reload()` callable.

---

## Player Workflow

1. **Pick a ship** from the dropdown at the top of the tab.
2. **Click "Find Shipyards in System"** — the right panel fills with nearby shipyard waypoints sorted by distance from the ship's current position.
3. **Select a destination** in the waypoints list.
4. **Click "Navigate"** — the app automatically moves the ship into orbit first if it is still docked, then sends the navigate command.
5. **Arrival time** is shown in the left panel. Click **"↻ Refresh"** to check current status.
6. Once arrived, click **"Dock"** to land at the destination.

---

## Module Structure

| Section | Purpose |
|---|---|
| `NavigationContext` dataclass | Holds all URLs and helpers injected from `main.py` |
| API helpers (`_get_*`, `_find_*`, `_post_action`) | One function per type of network request |
| `build_navigation_tab()` | Builds all widgets; all event handlers are inner functions |

---

## `NavigationContext` Dataclass

Declared with `@dataclass`. Holds everything the module needs from the outside world so the module never imports from `main.py`.

| Field | Type | Description |
|---|---|---|
| `root` | `tk.Tk` | Main application window (used as parent for future dialogs) |
| `request_headers` | `Callable` | Returns `{"Authorization": "Bearer <token>"}` or `None` if not logged in |
| `my_ships_url` | `str` | URL template for GET-ing all player ships |
| `ship_orbit_url` | `str` | URL template for POST-ing a ship into orbit |
| `ship_navigate_url` | `str` | URL template for POST-ing a navigation command |
| `ship_dock_url` | `str` | URL template for POST-ing a dock command |
| `ship_refuel_url` | `str` | URL template for POST-ing a refuel command |
| `system_waypoints_url` | `str` | URL template for GET-ing waypoints in a system |

---

## API Helper Functions

These are **module-level private functions** (prefixed with `_`). Each makes exactly one type of network request and returns safe defaults on error.

---

### `_get_my_ships(ctx: NavigationContext) -> list`
Fetches the full list of all player ships via `GET /my/ships` with `limit=20`. Returns the `data` array from the JSON response, or `[]` on HTTP failure or `ConnectionError`.

---

### `_get_ship(ship_symbol: str, ctx: NavigationContext) -> dict | None`
Fetches detailed information for a single ship at `GET /my/ships/{ship_symbol}`. Returns the ship dict (containing `nav`, `fuel`, `cargo`, `mounts`, etc.) or `None` on failure.

---

### `_find_shipyards(system: str, ctx: NavigationContext) -> tuple[list | None, str | None]`
Finds all waypoints in a given star system that have the `SHIPYARD` trait. Because the SpaceTraders API paginates results to 20 per page, this function loops until `len(results) >= meta.total`. Returns:
- `(list_of_waypoint_dicts, None)` on success.
- `(None, error_message_string)` on failure (HTTP error or `ConnectionError`).

---

### `_post_action(url: str, body: dict, ctx: NavigationContext) -> tuple[dict | None, str | None]`
Generic POST helper used by all ship-action endpoints (orbit, dock, navigate, refuel). Sends the request with `Content-Type: application/json`. Returns:
- `(data_dict, None)` on HTTP 200 or 201.
- `(None, error_message)` on failure, extracting the API's `error.message` if available.

---

## `build_navigation_tab(parent, ctx) -> Callable`

The main tab builder. Takes the parent `tk.Widget` (the tab frame) and a `NavigationContext`, constructs all sub-widgets, defines all event handlers as inner functions (closures), and returns the `reload_ships` callable.

### Shared Mutable State (closure trick)

Inner functions in Python can read outer-scope variables but cannot *reassign* them without `nonlocal`. To sidestep this, mutable state is kept in **single-element lists**:

| Variable | Type | Purpose |
|---|---|---|
| `_shipyards` | `list` | Cached list of shipyard waypoint dicts from the last search |
| `_current_system` | `list[str]` | The system symbol of the currently selected ship |

### Widget Layout

```
┌─ Top bar ──────────────────────────────────────────────────┐
│  Ship: [dropdown]  [Find Shipyards in System]  [status]    │
└────────────────────────────────────────────────────────────┘
┌─ Ship Status ──────┐  ┌─ Shipyards in System ─────────────┐
│  Location: ...     │  │  Waypoint     Type      Dist       │
│  System:   ...     │  │  ─────────────────────────────     │
│  Status:   ...     │  │  X1-DF55-A1   ASTEROID  123        │
│  Fuel:     ...     │  │  X1-DF55-B2   PLANET    456        │
│  Arrival:  ...     │  │  ...                               │
│                    │  │                                    │
│  [Orbit] [Dock]    │  │  [➤ Navigate to Selected]          │
│  [Refuel]          │  │                                    │
└────────────────────┘  └────────────────────────────────────┘
```

### Inner Helper Functions

#### `_current_ship_symbol() -> str`
Extracts just the ship symbol from the combobox label formatted as `"SHIP-SYM  (SYSTEM)"`. Splits on `"  "` and takes the first part.

#### `_update_ship_panel(ship: dict)`
Populates the left panel (location, system, status, fuel, arrival countdown) from a ship dict. Computes an arrival countdown from the route's ISO-8601 `arrival` timestamp using `datetime.now(timezone.utc)`. Enables/disables the Orbit, Dock, and Refuel buttons based on the ship's `nav.status` value (`DOCKED`, `IN_ORBIT`, `IN_TRANSIT`).

#### `_update_nav_btn(current_status: str = "")`
Enables the Navigate button only when:
- The ship is idle (not `IN_TRANSIT`, not empty/unknown status).
- A destination waypoint is selected in the treeview.

#### `_dist(wp: dict, ox: float, oy: float) -> float`
Calculates the Euclidean distance between a waypoint (using its `x`/`y` fields) and an origin point `(ox, oy)`. Used to sort waypoints by proximity to the ship.

---

### Event Handler Inner Functions

#### `reload_ships()`
Fetches all player ships from the API and rebuilds the ship dropdown labels as `"SHIP-SYMBOL  (SYSTEM)"`. If the previously selected ship is no longer in the list, auto-selects the first entry and triggers `on_ship_selected()`. This is the function returned to `main.py` and called on every tab activation.

#### `on_ship_selected()`
Called when the player picks a ship from the dropdown. Fetches full ship details via `_get_ship()`, populates the left panel via `_update_ship_panel()`, and stores the ship's system symbol in `_current_system[0]`.

#### `on_find()`
Triggered by the "Find Shipyards in System" button. Calls `_find_shipyards()` for the selected ship's system, then fetches the ship's current position to sort results by distance. Populates the right treeview; marks the ship's current waypoint with a `"◀ here"` label and dims it in grey so it is not accidentally chosen as a destination.

#### `on_orbit()`
Sends a POST orbit command for the current ship. On success, updates `ship_status`, flips the Orbit/Dock button states, and calls `_update_nav_btn()`.

#### `on_dock()`
Sends a POST dock command. On success, updates the status display, flips button states, and disables the Navigate button (docked ships cannot navigate).

#### `on_refuel()`
Sends a POST refuel command. On success, updates the fuel display and shows the cost (in credits) in the status bar. Requires the ship to be DOCKED at a waypoint with a marketplace that sells FUEL.

#### `on_navigate()`
The main navigation action:
1. Reads the selected destination waypoint from the treeview.
2. Checks that the ship is not already `IN_TRANSIT`.
3. If the ship is `DOCKED`, automatically calls the orbit endpoint first (SpaceTraders requires `IN_ORBIT` before navigating).
4. Sends the navigate POST with `{"waypointSymbol": dest}`.
5. On success, computes and displays the arrival countdown, updates the status to `IN_TRANSIT`, and disables all action buttons until the ship arrives.

#### `on_refresh_ship()`
Re-fetches the current ship's details from the API and updates the left panel. Used after the player expects arrival to check if the ship has landed.

---

## Return Value

`build_navigation_tab()` returns the `reload_ships` inner function. `main.py` stores this as `_navigation_reload` and calls it whenever the user switches to the Navigation tab (index 5) via `refresh_tabs()`.
