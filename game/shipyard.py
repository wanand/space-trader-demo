"""
shipyard.py — Shipyard Browser Tab
=====================================
Lets you explore and interact with shipyards in your ship's system.

What you can do here
---------------------
1. Pick one of your ships to choose which system to search.
2. Click "Search Shipyards in System" to find all shipyard waypoints.
3. Click a waypoint to see its details: modification fee, available mounts,
   and ships for sale with prices.
4. Select a ship for sale and click "Buy Ship" to purchase it.
5. If one of your ships is at the waypoint with mounts in its cargo,
   use the "Install Mount from Cargo" panel to install them.

Important note about API limitations
--------------------------------------
The SpaceTraders API only returns full details (prices, mount list) when
one of your ships is physically present at the waypoint.  If no ship is
there, the tab shows what it can and explains why details may be missing.
"""

import tkinter as tk
from tkinter import ttk, messagebox
from dataclasses import dataclass
from typing import Callable

import requests


# =============================================================================
# Context — data injected from main.py
# =============================================================================

@dataclass
class ShipyardContext:
    """
    All the URLs and helpers this module needs.

    main.py creates one of these and passes it to build_shipyard_tab().
    {} in URL strings is a placeholder replaced with .format(value).
    """
    root:                   tk.Tk      # Main application window
    request_headers:        Callable   # Returns {"Authorization": "Bearer <token>"}
    my_ships_url:           str        # GET your ships / POST buy a ship
    system_waypoints_url:   str        # GET waypoints in a system; {} = system symbol
    shipyard_url:           str        # GET shipyard details; {} = system, {} = waypoint
    ship_cargo_url:         str        # GET cargo of a ship; {} = ship symbol
    ship_mounts_url:        str        # GET mounts on a ship; {} = ship symbol
    ship_install_mount_url: str        # POST install a mount; {} = ship symbol
    ship_dock_url:          str        # POST dock a ship; {} = ship symbol


# =============================================================================
# API helpers — one function per type of network request
# =============================================================================

def _get_my_ships(ctx: ShipyardContext) -> list:
    """Return your full list of ships, or [] on failure."""
    headers = ctx.request_headers(require_token=True)
    if headers is None:
        return []
    try:
        resp = requests.get(ctx.my_ships_url, headers=headers, params={"limit": 20})
        if resp.status_code == 200:
            return resp.json()["data"]
    except ConnectionError:
        pass
    return []


def _find_shipyards(system_symbol: str, ctx: ShipyardContext) -> tuple[list | None, str | None]:
    """
    Find every waypoint in *system_symbol* that has the SHIPYARD trait.

    Automatically fetches all pages (20 results per page).
    Returns (list_of_dicts, None) on success, or (None, error_string) on failure.
    """
    headers = ctx.request_headers(require_token=True)
    if headers is None:
        return None, "Missing token — please log in."

    results, page = [], 1
    try:
        while True:
            resp = requests.get(
                ctx.system_waypoints_url.format(system_symbol),
                headers=headers,
                params={"traits": "SHIPYARD", "limit": 20, "page": page},
            )
            if resp.status_code != 200:
                try:
                    return None, resp.json()["error"]["message"]
                except Exception:
                    return None, resp.text

            payload = resp.json()
            batch   = payload["data"]
            results.extend(batch)

            total = payload.get("meta", {}).get("total", len(results))
            if len(results) >= total or not batch:
                break
            page += 1

    except ConnectionError as ce:
        return None, str(ce)

    return results, None


def _get_shipyard_detail(system: str, waypoint: str, ctx: ShipyardContext) -> tuple[dict | None, str | None]:
    """Fetch full details for a single shipyard.  Returns (data, error)."""
    headers = ctx.request_headers(require_token=True)
    if headers is None:
        return None, "Missing token — please log in."
    try:
        resp = requests.get(ctx.shipyard_url.format(system, waypoint), headers=headers)
        if resp.status_code == 200:
            return resp.json()["data"], None
        try:
            return None, resp.json()["error"]["message"]
        except Exception:
            return None, resp.text
    except ConnectionError as ce:
        return None, str(ce)


def _buy_ship(ship_type: str, waypoint_symbol: str, ctx: ShipyardContext) -> tuple[dict | None, str | None]:
    """
    Purchase a ship of *ship_type* at *waypoint_symbol*.

    Uses POST /my/ships.  Returns (result_dict, None) on success.
    One of your ships must be present at the waypoint.
    """
    headers = ctx.request_headers(require_token=True)
    if headers is None:
        return None, "Missing token — please log in."
    try:
        resp = requests.post(
            ctx.my_ships_url,
            json={"shipType": ship_type, "waypointSymbol": waypoint_symbol},
            headers={**headers, "Content-Type": "application/json"},
        )
        if resp.status_code in (200, 201):
            return resp.json()["data"], None
        try:
            return None, resp.json()["error"]["message"]
        except Exception:
            return None, resp.text
    except ConnectionError as ce:
        return None, str(ce)


def _get_ship_cargo_mounts(ship_symbol: str, ctx: ShipyardContext) -> list:
    """
    Return only the MOUNT_ items sitting in the ship's cargo.

    All mount symbols start with "MOUNT_", so we filter on that prefix.
    Returns [] if the ship has no mounts in cargo or the request fails.
    """
    headers = ctx.request_headers(require_token=True)
    if headers is None:
        return []
    try:
        resp = requests.get(ctx.ship_cargo_url.format(ship_symbol), headers=headers)
        if resp.status_code == 200:
            inventory = resp.json()["data"].get("inventory", [])
            return [item for item in inventory if item.get("symbol", "").startswith("MOUNT_")]
    except ConnectionError:
        pass
    return []


def _dock_ship(ship_symbol: str, ctx: ShipyardContext) -> tuple[dict | None, str | None]:
    """Dock the ship at its current waypoint.  Returns (data, error)."""
    headers = ctx.request_headers(require_token=True)
    if headers is None:
        return None, "Missing token — please log in."
    try:
        resp = requests.post(
            ctx.ship_dock_url.format(ship_symbol),
            json={},
            headers={**headers, "Content-Type": "application/json"},
        )
        if resp.status_code == 200:
            return resp.json()["data"], None
        try:
            return None, resp.json()["error"]["message"]
        except Exception:
            return None, resp.text
    except ConnectionError as ce:
        return None, str(ce)


def _install_mount(ship_symbol: str, mount_symbol: str, ctx: ShipyardContext) -> tuple[dict | None, str | None]:
    """
    Install a mount from the ship's cargo onto the ship.

    The ship must be DOCKED at a shipyard.
    Returns (data, error).
    """
    headers = ctx.request_headers(require_token=True)
    if headers is None:
        return None, "Missing token — please log in."
    try:
        resp = requests.post(
            ctx.ship_install_mount_url.format(ship_symbol),
            json={"symbol": mount_symbol},
            headers={**headers, "Content-Type": "application/json"},
        )
        if resp.status_code == 201:
            return resp.json()["data"], None
        try:
            return None, resp.json()["error"]["message"]
        except Exception:
            return None, resp.text
    except ConnectionError as ce:
        return None, str(ce)


# =============================================================================
# Tab builder — called once by main.py to construct the Shipyard tab
# =============================================================================

def build_shipyard_tab(parent: tk.Widget, ctx: ShipyardContext) -> Callable:
    """
    Build all the Shipyard tab widgets inside *parent*.

    Returns a no-argument reload() callable that main.py calls whenever
    the player switches to this tab (refreshes the ship dropdown).

    UI layout
    ----------
    Top bar  — ship picker + Search button + status label
    Left     — list of shipyard waypoints found in the system
    Right    — details panel:
                 (top)    mounts info text
                 (middle) ships for sale + Buy button
                 (bottom) install mount from cargo
    """

    # ── Shared state ─────────────────────────────────────────────────────────
    # These lists hold mutable state accessible by all inner functions.
    # (See navigation.py for an explanation of why we use lists instead of
    # plain variables for mutable state in closures.)
    _waypoints:      list = []    # Shipyard waypoints found in the last search
    _current_system: list = [""]  # System symbol of the currently selected ship
    _ships_for_sale: list = []    # Ship dicts from the last shipyard fetch
    _cur_waypoint:   list = [""]  # Symbol of the currently selected waypoint
    _install_ships:  list = []    # Your ships currently at the selected waypoint
    _cargo_mounts:   list = []    # MOUNT_ items in the selected install-ship's cargo

    # ── Top bar ───────────────────────────────────────────────────────────────
    top = ttk.Frame(parent, padding=(6, 6, 6, 0))
    top.grid(row=0, column=0, columnspan=2, sticky=tk.EW)

    ttk.Label(top, text="Ship:").grid(row=0, column=0, sticky=tk.W, padx=(0, 4))
    ship_var   = tk.StringVar()
    ship_combo = ttk.Combobox(top, textvariable=ship_var, width=28, state="readonly")
    ship_combo.grid(row=0, column=1, sticky=tk.W, padx=(0, 8))

    ttk.Button(top, text="Search Shipyards in System", command=lambda: on_search()).grid(
        row=0, column=2, sticky=tk.W, padx=(0, 12)
    )

    status_var = tk.StringVar(value="Select a ship then click Search.")
    ttk.Label(top, textvariable=status_var, anchor=tk.W).grid(
        row=0, column=3, sticky=tk.EW, padx=(0, 6)
    )
    top.columnconfigure(3, weight=1)

    # ── Left — list of shipyard waypoints ─────────────────────────────────────
    left_frame = ttk.LabelFrame(parent, text="Shipyards Found", padding=5)
    left_frame.grid(row=1, column=0, sticky=tk.NSEW, padx=(6, 3), pady=6)

    waypoint_tree = ttk.Treeview(
        left_frame,
        columns=("Waypoint", "Type"),
        show="headings",
        height=16,
        selectmode="browse",
    )
    waypoint_tree.heading("Waypoint", text="Waypoint")
    waypoint_tree.heading("Type",     text="Type")
    waypoint_tree.column("Waypoint",  width=140, anchor=tk.W)
    waypoint_tree.column("Type",      width=140, anchor=tk.W)
    waypoint_tree.grid(row=0, column=0, sticky=tk.NSEW)

    wp_scroll = ttk.Scrollbar(left_frame, orient=tk.VERTICAL, command=waypoint_tree.yview)
    wp_scroll.grid(row=0, column=1, sticky=tk.NS)
    waypoint_tree.config(yscrollcommand=wp_scroll.set)
    waypoint_tree.bind("<<TreeviewSelect>>", lambda e: on_waypoint_select())

    left_frame.columnconfigure(0, weight=1)
    left_frame.rowconfigure(0, weight=1)

    # ── Right — shipyard details ───────────────────────────────────────────────
    right_frame = ttk.LabelFrame(parent, text="Shipyard Details", padding=5)
    right_frame.grid(row=1, column=1, sticky=tk.NSEW, padx=(3, 6), pady=6)

    # ----- Mounts info text area (top of right frame) -----
    detail_text = tk.Text(
        right_frame,
        wrap=tk.WORD,
        width=52,
        height=9,
        state=tk.DISABLED,  # Read-only; we enable it briefly to write, then disable again
        relief=tk.FLAT,
        cursor="arrow",     # Keeps the cursor an arrow (not a text cursor) over the widget
    )
    detail_text.tag_configure("heading",    font=("TkDefaultFont", 11, "bold"))
    detail_text.tag_configure("subheading", font=("TkDefaultFont",  9, "bold"))
    detail_text.tag_configure("dim",        foreground="#888")
    detail_text.tag_configure("mount",      foreground="#006400", font=("TkDefaultFont", 9, "bold"))
    detail_text.grid(row=0, column=0, sticky=tk.NSEW)

    dt_scroll = ttk.Scrollbar(right_frame, orient=tk.VERTICAL, command=detail_text.yview)
    dt_scroll.grid(row=0, column=1, sticky=tk.NS)
    detail_text.config(yscrollcommand=dt_scroll.set)

    # ----- Ships for sale (middle of right frame) -----
    sale_frame = ttk.LabelFrame(right_frame, text="Ships for Sale", padding=5)
    sale_frame.grid(row=1, column=0, columnspan=2, sticky=tk.NSEW, pady=(8, 0))

    ships_tree = ttk.Treeview(
        sale_frame,
        columns=("Type", "Name", "Price"),
        show="headings",
        height=5,
        selectmode="browse",
    )
    ships_tree.heading("Type",  text="Type")
    ships_tree.heading("Name",  text="Name")
    ships_tree.heading("Price", text="Price (credits)")
    ships_tree.column("Type",   width=160, anchor=tk.W)
    ships_tree.column("Name",   width=160, anchor=tk.W)
    ships_tree.column("Price",  width=110, anchor=tk.E)
    ships_tree.grid(row=0, column=0, sticky=tk.NSEW)

    st_scroll = ttk.Scrollbar(sale_frame, orient=tk.VERTICAL, command=ships_tree.yview)
    st_scroll.grid(row=0, column=1, sticky=tk.NS)
    ships_tree.config(yscrollcommand=st_scroll.set)

    buy_btn = ttk.Button(
        sale_frame, text="🛒  Buy Selected Ship",
        state=tk.DISABLED, command=lambda: on_buy(),
    )
    buy_btn.grid(row=1, column=0, columnspan=2, sticky=tk.EW, pady=(6, 0))

    buy_status_var = tk.StringVar(value="")
    ttk.Label(sale_frame, textvariable=buy_status_var, wraplength=440, anchor=tk.W).grid(
        row=2, column=0, columnspan=2, sticky=tk.EW, pady=(4, 0)
    )

    # Enable Buy only when a ship row is selected and we have price data
    def _update_buy_btn(*_):
        state = tk.NORMAL if (ships_tree.selection() and _ships_for_sale) else tk.DISABLED
        buy_btn.config(state=state)

    ships_tree.bind("<<TreeviewSelect>>", _update_buy_btn)
    sale_frame.columnconfigure(0, weight=1)
    sale_frame.rowconfigure(0, weight=1)

    # ----- Install mount from cargo (bottom of right frame) -----
    install_frame = ttk.LabelFrame(right_frame, text="Install Mount from Cargo", padding=5)
    install_frame.grid(row=2, column=0, columnspan=2, sticky=tk.NSEW, pady=(8, 0))

    # Row 0: ship-at-waypoint picker + refresh button
    ttk.Label(install_frame, text="Ship at waypoint:").grid(
        row=0, column=0, sticky=tk.W, padx=(0, 4)
    )
    inst_ship_var   = tk.StringVar()
    inst_ship_combo = ttk.Combobox(install_frame, textvariable=inst_ship_var, width=26, state="readonly")
    inst_ship_combo.grid(row=0, column=1, sticky=tk.EW, padx=(0, 4))
    ttk.Button(install_frame, text="↻", width=3, command=lambda: _refresh_install_ships()).grid(
        row=0, column=2, sticky=tk.W
    )

    # Row 1: listbox showing MOUNT_ items in the selected ship's cargo
    ttk.Label(install_frame, text="Mounts in cargo:").grid(
        row=1, column=0, sticky=tk.NW, pady=(6, 0)
    )
    cargo_lb_frame = ttk.Frame(install_frame)
    cargo_lb_frame.grid(row=1, column=1, columnspan=2, sticky=tk.NSEW, pady=(6, 0))

    cargo_lb = tk.Listbox(cargo_lb_frame, height=4, selectmode=tk.SINGLE, exportselection=False)
    cargo_lb.grid(row=0, column=0, sticky=tk.NSEW)
    cargo_lb_scroll = ttk.Scrollbar(cargo_lb_frame, orient=tk.VERTICAL, command=cargo_lb.yview)
    cargo_lb_scroll.grid(row=0, column=1, sticky=tk.NS)
    cargo_lb.config(yscrollcommand=cargo_lb_scroll.set)
    cargo_lb_frame.columnconfigure(0, weight=1)
    cargo_lb_frame.rowconfigure(0, weight=1)

    # Row 2: install button + status label
    install_btn = ttk.Button(
        install_frame, text="⬇  Install Selected Mount",
        state=tk.DISABLED, command=lambda: on_install(),
    )
    install_btn.grid(row=2, column=0, columnspan=3, sticky=tk.EW, pady=(6, 0))

    inst_status_var = tk.StringVar(value="Select a waypoint, then pick a ship to see its cargo mounts.")
    ttk.Label(install_frame, textvariable=inst_status_var, wraplength=440, anchor=tk.W).grid(
        row=3, column=0, columnspan=3, sticky=tk.EW, pady=(4, 0)
    )

    # Enable Install only when a cargo mount is selected
    def _update_install_btn(*_):
        state = tk.NORMAL if (cargo_lb.curselection() and _cargo_mounts) else tk.DISABLED
        install_btn.config(state=state)

    cargo_lb.bind("<<ListboxSelect>>", _update_install_btn)
    install_frame.columnconfigure(1, weight=1)

    # Layout weights
    right_frame.columnconfigure(0, weight=1)
    right_frame.rowconfigure((0, 1, 2), weight=1)
    parent.columnconfigure(0, weight=1)
    parent.columnconfigure(1, weight=2)
    parent.rowconfigure(1, weight=1)

    # =========================================================================
    # Helpers
    # =========================================================================

    def _set_detail(lines: list):
        """
        Replace the contents of the detail text widget.

        *lines* is a list of (text_string, tag_name_or_None) tuples.
        """
        detail_text.config(state=tk.NORMAL)
        detail_text.delete("1.0", tk.END)
        for text, tag in lines:
            if tag:
                detail_text.insert(tk.END, text, tag)
            else:
                detail_text.insert(tk.END, text)
        detail_text.config(state=tk.DISABLED)

    def _populate_ships_tree(ships: list, show_types_only: bool = False):
        """
        Fill the "Ships for Sale" treeview.

        If *show_types_only* is True, only ship type codes are available
        (no names or prices) — this happens when no player ship is at the
        waypoint.
        """
        _ships_for_sale.clear()
        ships_tree.delete(*ships_tree.get_children())
        buy_status_var.set("")
        buy_btn.config(state=tk.DISABLED)

        if show_types_only:
            # The API gave us shipTypes (just codes), not full ship objects
            for ship_type in ships:
                ships_tree.insert("", "end", values=(ship_type.get("type", "?"), "—", "unknown"))
            return

        _ships_for_sale.extend(ships)
        for ship in sorted(ships, key=lambda s: s.get("type", "")):
            price = ship.get("purchasePrice")
            price_str = f"{price:,}" if price is not None else "unknown"
            ships_tree.insert(
                "", "end",
                iid=ship.get("type", ""),   # Use type as the row ID for easy lookup
                values=(ship.get("type", "?"), ship.get("name", ""), price_str),
            )

    def _refresh_install_ships():
        """
        Reload the "Ship at waypoint" dropdown with your ships currently
        docked or orbiting at the selected waypoint.
        """
        _install_ships.clear()
        waypoint = _cur_waypoint[0]
        if not waypoint:
            inst_ship_combo["values"] = []
            inst_ship_var.set("")
            inst_status_var.set("Select a shipyard waypoint first.")
            return

        all_ships = _get_my_ships(ctx)
        # Keep only ships physically at this waypoint
        at_wp = [s for s in all_ships if s.get("nav", {}).get("waypointSymbol") == waypoint]
        _install_ships.extend(at_wp)

        labels = [
            f"{s['symbol']}  [{s.get('nav', {}).get('status', '?')}]"
            for s in at_wp
        ]
        inst_ship_combo["values"] = labels

        if labels:
            inst_ship_var.set(labels[0])
            _on_install_ship_change()
        else:
            inst_ship_var.set("")
            cargo_lb.delete(0, tk.END)
            _cargo_mounts.clear()
            install_btn.config(state=tk.DISABLED)
            inst_status_var.set(f"No ships at {waypoint}.  Navigate and dock a ship here first.")

    def _on_install_ship_change(*_):
        """
        Called whenever the install-ship picker changes.

        Loads MOUNT_ cargo items for the newly selected ship.
        This function is also triggered automatically by
        inst_ship_var.trace_add() below.
        """
        _cargo_mounts.clear()
        cargo_lb.delete(0, tk.END)
        install_btn.config(state=tk.DISABLED)

        lbl = inst_ship_var.get()
        if not lbl or not _install_ships:
            return

        # The label is "SHIP-SYMBOL  [STATUS]" — extract just the symbol
        ship_sym = lbl.split("  [")[0]
        items    = _get_ship_cargo_mounts(ship_sym, ctx)
        _cargo_mounts.extend(items)

        if items:
            for item in items:
                cargo_lb.insert(tk.END, f"{item['symbol']}  ×{item.get('units', 1)}")
            inst_status_var.set(
                f"{len(items)} mount(s) in cargo.  Ship must be DOCKED to install."
            )
        else:
            inst_status_var.set(f"No MOUNT_ items in {ship_sym}'s cargo.")

    # Automatically call _on_install_ship_change whenever inst_ship_var changes
    inst_ship_var.trace_add("write", _on_install_ship_change)

    def _selected_system() -> str:
        """Extract the system symbol from the ship combobox label "SYM  (SYSTEM)"."""
        raw = ship_var.get()
        if "(" in raw and raw.endswith(")"):
            return raw[raw.index("(") + 1 : -1].strip()
        return ""

    def _build_detail_lines(data: dict, waypoint_symbol: str) -> list:
        """
        Turn a shipyard data dict into a list of (text, tag) tuples for
        the detail text widget.

        Shows the waypoint name, modification fee, and mounts available
        pre-installed on ships sold here.
        """
        lines = [(f"{waypoint_symbol}\n", "heading")]

        mod_fee = data.get("modificationsFee")
        if mod_fee is not None:
            lines.append((f"Modification fee: {mod_fee:,} credits\n\n", None))

        ships_available = data.get("ships", [])

        # Collect unique mounts across all ships for sale
        seen_symbols: set = set()
        mount_objects: list = []
        for ship in ships_available:
            for m in ship.get("mounts", []):
                sym = m.get("symbol", "")
                if sym and sym not in seen_symbols:
                    seen_symbols.add(sym)
                    mount_objects.append(m)

        lines.append(("Mounts Found on Ships Sold Here\n", "subheading"))
        lines.append((
            "  ℹ  These mounts are pre-installed on ships for sale — they are NOT\n"
            "     sold as standalone items here.  To get a mount into your cargo\n"
            "     you must: remove it from a ship, extract it from an asteroid, or\n"
            "     buy it at a marketplace that sells it as a trade good.\n",
            "dim",
        ))

        if mount_objects:
            for m in sorted(mount_objects, key=lambda x: x.get("symbol", "")):
                sym  = m.get("symbol", "?")
                name = m.get("name", "")
                desc = m.get("description", "")
                label = f"  • {sym}"
                if name:
                    label += f"  —  {name}"
                lines.append((label + "\n", "mount"))
                if desc:
                    # Truncate long descriptions to keep the panel clean
                    short = desc if len(desc) <= 90 else desc[:87] + "…"
                    lines.append((f"      {short}\n", "dim"))
        elif seen_symbols:
            for sym in sorted(seen_symbols):
                lines.append((f"  • {sym}\n", "mount"))
        else:
            if ships_available:
                lines.append(("  (no mounts found on ships sold here)\n", "dim"))
            else:
                lines.append((
                    "  Full mount list not available — one of your ships must\n"
                    "  be present at this waypoint to see details.\n",
                    "dim",
                ))

        return lines

    # =========================================================================
    # Event handlers — one per user action
    # =========================================================================

    def reload_ships():
        """
        Refresh the ship dropdown with the latest list from the API.

        main.py calls this whenever the player switches to the Shipyard tab.
        """
        ships  = _get_my_ships(ctx)
        labels = [f"{s['symbol']}  ({s['nav']['systemSymbol']})" for s in ships]
        ship_combo["values"] = labels
        if ship_var.get() not in labels:
            ship_var.set(labels[0] if labels else "")

    def on_search():
        """Search for all shipyard waypoints in the selected ship's system."""
        system = _selected_system()
        if not system:
            status_var.set("Pick a ship first.")
            return
        status_var.set(f"Searching for shipyards in {system}…")
        parent.update_idletasks()

        waypoints, err = _find_shipyards(system, ctx)
        if waypoints is None:
            status_var.set(f"Search failed: {err}")
            return

        _waypoints.clear()
        _waypoints.extend(waypoints)
        _current_system[0] = system

        waypoint_tree.delete(*waypoint_tree.get_children())
        for wp in _waypoints:
            waypoint_tree.insert("", "end", iid=wp["symbol"],
                                 values=(wp["symbol"], wp["type"]))

        count = len(_waypoints)
        if count == 0:
            status_var.set(f"No shipyards found in {system}.")
            _set_detail([])
            _populate_ships_tree([])
        else:
            status_var.set(f"{count} shipyard(s) found in {system}.  Click one for details.")

    def on_waypoint_select():
        """Load and display full details when the player clicks a waypoint."""
        sel = waypoint_tree.selection()
        if not sel:
            return
        waypoint = sel[0]
        system   = _current_system[0]
        _cur_waypoint[0] = waypoint

        status_var.set(f"Loading {waypoint}…")
        parent.update_idletasks()

        data, err = _get_shipyard_detail(system, waypoint, ctx)
        if data is None:
            # Show an informative error in the detail panel
            status_var.set(f"Failed: {err}")
            _set_detail([
                (f"{waypoint}\n", "heading"),
                (f"\nCould not load details:\n{err}\n", None),
                (
                    "\nNote: full details (prices, mount list) are only returned\n"
                    "when one of your ships is present at this waypoint.\n",
                    "dim",
                ),
            ])
            _populate_ships_tree([])
            _refresh_install_ships()
            return

        # Populate the three right-panel sections
        _set_detail(_build_detail_lines(data, waypoint))

        ships_available = data.get("ships", [])      # Full details (needs ship present)
        ship_types      = data.get("shipTypes", [])  # Just type codes (always available)

        if ships_available:
            _populate_ships_tree(ships_available)           # Full info with prices
        elif ship_types:
            _populate_ships_tree(ship_types, show_types_only=True)  # Type codes only
        else:
            _populate_ships_tree([])

        _refresh_install_ships()
        status_var.set(f"Showing details for {waypoint}.")

    def on_buy():
        """Purchase the selected ship after confirming with the player."""
        sel = ships_tree.selection()
        if not sel:
            return
        ship_type = sel[0]   # Row IID is the ship type string
        waypoint  = _cur_waypoint[0]
        if not waypoint:
            buy_status_var.set("No waypoint selected.")
            return

        # Look up the full ship data to get name and price
        ship_data = next((s for s in _ships_for_sale if s.get("type") == ship_type), None)
        name      = ship_data.get("name", ship_type) if ship_data else ship_type
        price     = ship_data.get("purchasePrice")    if ship_data else None
        price_str = f"{price:,} credits" if price is not None else "unknown price"

        # Ask for confirmation before spending credits
        confirmed = messagebox.askyesno(
            "Confirm Purchase",
            f"Buy  {name}  ({ship_type})\nat  {waypoint}\nfor  {price_str}?\n\n"
            "Your agent's account will be charged.",
            parent=ctx.root,
        )
        if not confirmed:
            return

        buy_status_var.set(f"Purchasing {ship_type}…")
        ctx.root.update_idletasks()

        data, err = _buy_ship(ship_type, waypoint, ctx)
        if data is None:
            buy_status_var.set(f"Purchase failed: {err}")
            return

        new_sym    = data.get("ship", {}).get("symbol", "?")
        agent      = data.get("agent", {})
        credits    = agent.get("credits")
        credit_str = f"  |  Balance: {credits:,} credits" if credits is not None else ""
        buy_status_var.set(f"✓  {ship_type} purchased!  New ship: {new_sym}{credit_str}")

        # Refresh dropdowns so the new ship appears
        reload_ships()
        _refresh_install_ships()

    def on_install():
        """
        Install the selected cargo mount on the chosen ship.

        Automatically docks the ship first if it is not already docked.
        """
        sel = cargo_lb.curselection()
        if not sel or not _cargo_mounts:
            return

        item       = _cargo_mounts[sel[0]]
        mount_sym  = item["symbol"]
        lbl        = inst_ship_var.get()
        if not lbl:
            inst_status_var.set("Pick a ship first.")
            return
        ship_sym = lbl.split("  [")[0]

        # Find the ship in our cached list to check nav status
        ship_data  = next((s for s in _install_ships if s["symbol"] == ship_sym), None)
        nav_status = ship_data.get("nav", {}).get("status", "") if ship_data else ""

        # Auto-dock if not already docked (install requires DOCKED)
        if nav_status != "DOCKED":
            inst_status_var.set(f"Docking {ship_sym}…")
            parent.update_idletasks()
            _, dock_err = _dock_ship(ship_sym, ctx)
            if dock_err:
                inst_status_var.set(f"Could not dock: {dock_err}")
                return

        inst_status_var.set(f"Installing {mount_sym} on {ship_sym}…")
        parent.update_idletasks()

        data, err = _install_mount(ship_sym, mount_sym, ctx)
        if data is None:
            inst_status_var.set(f"Install failed: {err}")
            return

        # Refresh the cargo list to reflect the removed mount
        _cargo_mounts.clear()
        cargo_lb.delete(0, tk.END)
        install_btn.config(state=tk.DISABLED)
        new_cargo = _get_ship_cargo_mounts(ship_sym, ctx)
        _cargo_mounts.extend(new_cargo)
        for ci in new_cargo:
            cargo_lb.insert(tk.END, f"{ci['symbol']}  ×{ci.get('units', 1)}")

        inst_status_var.set(f"✓  {mount_sym} installed on {ship_sym}.")

    return reload_ships
