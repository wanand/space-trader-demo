# upgrade.py — Ship Mount Upgrade Dialog

## Overview

`upgrade.py` creates a **modal pop-up dialog** (triggered by double-clicking a ship in the Summary tab's ships treeview) that lets the player manage the mounts on a single ship. It is the most interactive module in the codebase, combining ship status, mount management, and cargo transfer in one window.

**Capabilities:**
1. View all mounts currently installed on the selected ship.
2. Install new mounts from the ship's cargo (onto the ship itself).
3. Remove existing installed mounts back into cargo.
4. Transfer cargo items (including mounts) to another ship at the same waypoint.

The module never imports from `main.py` directly. All shared state and URLs are provided through an `UpgradeContext` dataclass.

---

## Module Structure

| Section | Purpose |
|---|---|
| `UpgradeContext` dataclass | All URLs and helpers injected by `main.py` |
| API helpers | One function per type of network request |
| `open_upgrade_dialog()` | Creates the modal dialog and all its inner event handlers |

---

## `UpgradeContext` Dataclass

| Field | Type | Description |
|---|---|---|
| `root` | `tk.Tk` | Main application window (parent for the dialog) |
| `request_headers` | `Callable` | Returns auth headers dict or `None` |
| `player_worth_var` | `tk.StringVar` | Bound to the credits display on the Summary tab |
| `refresh_summary` | `Callable` | Callable to refresh the Summary tab after changes |
| `my_ships_url` | `str` | GET list of all player ships |
| `ship_mounts_url` | `str` | GET installed mounts for a ship |
| `ship_cargo_url` | `str` | GET cargo inventory for a ship |
| `install_mount_url` | `str` | POST install a mount from cargo |
| `remove_mount_url` | `str` | POST remove an installed mount to cargo |
| `ship_orbit_url` | `str` | POST move ship into orbit |
| `ship_dock_url` | `str` | POST dock ship at current waypoint |
| `ship_transfer_url` | `str` | POST transfer cargo to another ship |
| `shipyard_url` | `str` | GET shipyard info at a waypoint |

---

## API Helper Functions

### `_get_ship(ship_symbol: str, ctx: UpgradeContext) -> dict | None`
Fetches full details for a single ship via `GET /my/ships/{ship_symbol}`. Returns the ship dict (with `nav`, `fuel`, `cargo`, `mounts` keys) or `None` on failure. Used to load initial state and re-check status after dock/orbit operations.

---

### `_get_shipyard(system: str, waypoint: str, ctx: UpgradeContext) -> dict | None`
Fetches shipyard details at a waypoint via `GET /systems/{system}/waypoints/{waypoint}/shipyard`. Returns the shipyard dict or `None`. Used to determine whether the ship is at a shipyard (a prerequisite for installing or removing mounts).

---

### `_get_mounts(ship_symbol: str, ctx: UpgradeContext) -> list`
Returns the list of all mounts currently installed on the ship via `GET /my/ships/{symbol}/mounts`. Each item is a dict with keys like `symbol`, `name`, `description`. Returns `[]` on failure.

---

### `_get_cargo_mounts(ship_symbol: str, ctx: UpgradeContext) -> list`
Fetches the ship's full cargo via `GET /my/ships/{symbol}/cargo` and filters the `inventory` list to only items whose `symbol` starts with `"MOUNT_"`. Returns a list of matching cargo item dicts, or `[]`.

---

### `_install_mount(ship_symbol: str, mount_symbol: str, ctx: UpgradeContext)`
Installs a mount from cargo via `POST /my/ships/{symbol}/mounts/install` with body `{"symbol": mount_symbol}`. The ship must be DOCKED at a shipyard. Returns `(result_dict, None)` on HTTP 201 or `(None, error_message)` on failure.

---

### `_remove_mount(ship_symbol: str, mount_symbol: str, ctx: UpgradeContext)`
Removes an installed mount to cargo via `POST /my/ships/{symbol}/mounts/remove` with body `{"symbol": mount_symbol}`. Ship must be DOCKED at a shipyard. Returns `(result_dict, None)` or `(None, error_message)`.

---

### `_get_ships_at_waypoint(waypoint: str, ctx: UpgradeContext) -> list`
Fetches all player ships and filters to those whose `nav.waypointSymbol` matches the given waypoint. Used to build the list of valid cargo transfer targets — only ships at the same location can receive a transfer.

---

### `_transfer_cargo(from_ship, to_ship, item_symbol, units, ctx) -> tuple`
Transfers `units` of `item_symbol` from `from_ship` to `to_ship` via `POST /my/ships/{from_ship}/transfer` with body `{"tradeSymbol": item_symbol, "units": units, "shipSymbol": to_ship}`. Both ships must be at the same waypoint. Returns `(result_dict, None)` on HTTP 200 or `(None, error_message)`.

---

### `_orbit_ship(ship_symbol: str, ctx: UpgradeContext)`
Moves the ship out of dock into orbit via `POST /my/ships/{symbol}/orbit`. Returns `(nav_dict, None)` or `(None, error_message)`.

---

### `_dock_ship(ship_symbol: str, ctx: UpgradeContext)`
Docks the ship at its current waypoint via `POST /my/ships/{symbol}/dock`. Returns `(nav_dict, None)` or `(None, error_message)`.

---

## `open_upgrade_dialog(ship_symbol, ctx)`

The main entry point of the module. Called by `main.py`'s `display_clicked_ship()` handler.

Creates a `tk.Toplevel` modal dialog (`transient` + `grab_set` to block the main window). All inner functions are defined as closures with access to the dialog's widgets and shared state.

### Dialog Window Title
`"Upgrade — {ship_symbol}"`

### Shared State (closure lists)

| Variable | Purpose |
|---|---|
| `_ship_data[0]` | Full ship dict after initial fetch (used by transfer dialog) |
| `_at_shipyard[0]` | `bool` — whether the ship's current waypoint is a shipyard |

### Widget Layout

Three `ttk.LabelFrame` panels side-by-side, plus a status bar at the bottom:

```
┌─ Installed Mounts ─────┐  ┌─ Ship Info ────────────────┐  ┌─ Cargo — Mounts ─────────┐
│  MOUNT_SENSOR_ARRAY     │  │  Location:  X1-DF55-A1      │  │  MOUNT_GAS_SIPHON_I  ×2   │
│  MOUNT_GAS_SIPHON       │  │  System:    X1-DF55         │  │  MOUNT_SENSOR_ARRAY  ×1   │
│  ...                    │  │  Status:    DOCKED          │  │  ...                      │
│                         │  │  Fuel:      300 / 400       │  │                           │
│                         │  │  Cargo:     10 / 40         │  │                           │
│  [Remove Selected Mount]│  │  [⚓ Dock] [🚀 Orbit] [↻]  │  │  [Install Selected Mount] │
│                         │  │                             │  │  [Transfer to Another Ship│
└─────────────────────────┘  └─────────────────────────────┘  └───────────────────────────┘
┌─ Status bar ────────────────────────────────────────────────────────────────────────────┐
│  At shipyard: X1-DF55-A1                                                                │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

### Inner Helper Functions

#### `_add_info_row(parent, row, label_text, value_var)`
Adds a bold label and a `ttk.Label` bound to a `tk.StringVar` on the specified grid row of `parent`. Used to build the Ship Info panel cleanly.

#### `_update_buttons(ship_nav_status: str = "")`
Centralized button state manager. Called after every state change. Logic:
- **Dock** button: enabled when `IN_ORBIT`.
- **Orbit** button: enabled when `DOCKED`.
- **Install** button: enabled when `DOCKED` AND `_at_shipyard[0]` AND a cargo mount is selected.
- **Transfer** button: enabled when any cargo mount is selected (regardless of dock status).
- **Remove** button: enabled when `DOCKED` AND `_at_shipyard[0]` AND an installed mount is selected.

Bound to `<<ListboxSelect>>` on both listboxes so buttons respond immediately to selection changes.

#### `_repopulate_installed(mounts: list)`
Clears and refills the installed mounts listbox. Each entry is formatted as `"MOUNT_SYMBOL  —  Mount Name"` if the name is available, otherwise just the symbol.

#### `_repopulate_cargo(items: list)`
Clears and refills the cargo mounts listbox. Each entry is formatted as `"MOUNT_SYMBOL  ×N"` where `N` is the quantity.

#### `_load_ship_data()`
The initialization function. Called once when the dialog opens. Steps:
1. Fetches the full ship dict via `_get_ship()`.
2. Populates all centre panel labels (location, system, status, fuel, cargo).
3. Calls `_get_shipyard()` to check if the ship's waypoint is a shipyard; sets `_at_shipyard[0]`.
4. Fetches installed mounts via `_get_mounts()` and populates the left listbox.
5. Fetches cargo mounts via `_get_cargo_mounts()` and populates the right listbox.
6. Calls `_update_buttons()` with the current nav status.
7. Sets the status bar message (e.g., "At shipyard: X1-DF55-A1" or "Docked, but not at a shipyard").

---

### Event Handler Inner Functions

#### `on_dock()`
Sends a dock command and updates the status label and button states on success.

#### `on_orbit()`
Sends an orbit command and updates state on success.

#### `on_refresh()`
Re-calls `_load_ship_data()` to reload all panels from the API.

#### `on_install()`
1. Parses the mount symbol from the cargo listbox selection (format: `"SYMBOL  ×N"`).
2. Calls `_install_mount()`.
3. On success, repopulates both listboxes using the `mounts` list returned by the API.
4. Updates `ctx.player_worth_var` if the result includes updated agent credits (installation costs credits if at a paid shipyard).
5. Calls `_update_buttons()`.

#### `on_remove()`
1. Parses the mount symbol from the installed mounts listbox (format: `"SYMBOL  —  Name"`).
2. Calls `_remove_mount()`.
3. On success, repopulates both listboxes.
4. Updates `ctx.player_worth_var` if credits changed.
5. Calls `_update_buttons()`.

#### `on_transfer()`
Opens a secondary modal sub-dialog (`tk.Toplevel`) for selecting a destination ship and quantity:

**Sub-dialog flow:**
1. Identifies the player's current waypoint from `_ship_data[0]`.
2. Calls `_get_ships_at_waypoint()` to find valid targets (other ships at the same location).
3. Builds destination labels showing each ship's free cargo space: `"SHIP-SYM  (free: N)"`.
4. Shows a combobox for destination selection, an entry for unit count, and a warning label.
5. `_check_dest()` fires on each combo selection change and warns if the target's cargo is full.
6. `do_transfer()` (the confirm button handler) parses the destination symbol, validates units, calls `_transfer_cargo()`, repopulates the cargo listbox, calls `_update_buttons()` and `ctx.refresh_summary()`, then auto-closes the sub-dialog after 800 ms via `sub.after(800, sub.destroy)`.

The Transfer button is disabled if no other ships are at the waypoint.

---

## Key Design Patterns

### Modal Dialog
`dialog.transient(ctx.root)` keeps the dialog above the main window. `dialog.grab_set()` makes it modal — the player cannot interact with the main window until the dialog is closed.

### Closure State with Lists
Because Python closures cannot reassign outer-scope variables without `nonlocal`, mutable shared state (`_ship_data`, `_at_shipyard`) is stored as single-element lists. The inner functions modify the list's content (`_ship_data[0] = ...`) rather than rebinding the name.

### Credits Update
When install or remove operations change the player's credit balance, the result dict from the API includes the updated `agent.credits`. The dialog immediately pushes this value to `ctx.player_worth_var`, keeping the Summary tab's credits display in sync without requiring a full tab refresh.
