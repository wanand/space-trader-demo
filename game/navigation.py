"""
navigation.py — Navigation Tab
================================
Lets you move your ships between shipyard waypoints in the same system.

Step-by-step flow for the player
----------------------------------
1. Pick a ship from the dropdown at the top.
2. Click "Find Shipyards in System" — the right panel fills with nearby
   shipyard waypoints sorted by distance from your ship.
3. Select a destination in the list.
4. Click "Navigate" — the app automatically orbits the ship first if it
   is still docked, then sends the navigate command.
5. Arrival time is shown.  Click "↻ Refresh" to check current status.
6. Once arrived, click "Dock" to land at the waypoint.
"""

import math
import tkinter as tk
from tkinter import ttk
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

import requests


# =============================================================================
# Context — data injected from main.py
# =============================================================================

@dataclass
class NavigationContext:
    """
    All the URLs and callables this module needs from the outside world.

    main.py creates one of these and passes it to build_navigation_tab().
    URL fields use {} as a placeholder, e.g. ship_orbit_url.format("SHIP-1").
    """
    root:                 tk.Tk      # Main application window
    request_headers:      Callable   # Returns {"Authorization": "Bearer <token>"}
    my_ships_url:         str        # GET list of all your ships
    ship_orbit_url:       str        # POST  — move ship into orbit
    ship_navigate_url:    str        # POST  — navigate ship to a waypoint
    ship_dock_url:        str        # POST  — dock ship at current waypoint
    ship_refuel_url:      str        # POST  — refuel ship (must be DOCKED + marketplace)
    system_waypoints_url: str        # GET waypoints in a system; {} = system symbol


# =============================================================================
# API helpers — each function does one network request
# =============================================================================

def _get_my_ships(ctx: NavigationContext) -> list:
    """Return the list of all your ships, or [] on failure."""
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


def _get_ship(ship_symbol: str, ctx: NavigationContext) -> dict | None:
    """Fetch a single ship's full details.  Returns the ship dict or None."""
    headers = ctx.request_headers(require_token=True)
    if headers is None:
        return None
    try:
        resp = requests.get(f"{ctx.my_ships_url}/{ship_symbol}", headers=headers)
        if resp.status_code == 200:
            return resp.json()["data"]
    except ConnectionError:
        pass
    return None


def _find_shipyards(system: str, ctx: NavigationContext) -> tuple[list | None, str | None]:
    """
    Find every waypoint in *system* that has the SHIPYARD trait.

    The API paginates results (20 per page) so we loop until we have them all.
    Returns (list_of_waypoint_dicts, None) on success,
    or     (None, error_message)         on failure.
    """
    headers = ctx.request_headers(require_token=True)
    if headers is None:
        return None, "Missing token — please log in."

    results, page = [], 1
    try:
        while True:
            resp = requests.get(
                ctx.system_waypoints_url.format(system),
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

            # "meta.total" tells us how many results exist in total
            total = payload.get("meta", {}).get("total", len(results))
            if len(results) >= total or not batch:
                break  # All pages received
            page += 1

    except ConnectionError as ce:
        return None, str(ce)

    return results, None


def _post_action(url: str, body: dict, ctx: NavigationContext) -> tuple[dict | None, str | None]:
    """
    Generic helper for any POST request that expects a JSON {"data": …} response.

    Used for orbit, dock, navigate, and refuel — they all follow the same pattern.
    Returns (data_dict, None) on success, or (None, error_message) on failure.
    """
    headers = ctx.request_headers(require_token=True)
    if headers is None:
        return None, "Missing token — please log in."
    try:
        resp = requests.post(
            url,
            json=body,
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


# =============================================================================
# Tab builder — called once by main.py to construct the Navigation tab
# =============================================================================

def build_navigation_tab(parent: tk.Widget, ctx: NavigationContext) -> Callable:
    """
    Build all widgets for the Navigation tab inside *parent*.

    All event handlers are defined as inner (nested) functions so they can
    naturally access the widgets and shared state without needing global vars.

    Returns a no-argument reload() function that main.py can call whenever
    the user switches to this tab — it refreshes the ship dropdown.
    """

    # ── Shared state ─────────────────────────────────────────────────────
    # We store mutable state in single-element lists.  This is a common Python
    # trick: inner functions can *read* outer variables freely, but to *reassign*
    # them you would need "nonlocal".  A list sidesteps that: we never reassign
    # the list itself, we just change its contents (e.g. _current_system[0] = "X").
    _shipyards:      list = []    # Cached list of shipyard waypoint dicts
    _current_system: list = [""]  # The system symbol of the currently selected ship

    # ── Top bar — ship picker + Find button + status label ────────────────
    top = ttk.Frame(parent, padding=(6, 6, 6, 0))
    top.grid(row=0, column=0, columnspan=2, sticky=tk.EW)

    ttk.Label(top, text="Ship:").grid(row=0, column=0, sticky=tk.W, padx=(0, 4))
    ship_var = tk.StringVar()
    ship_combo = ttk.Combobox(top, textvariable=ship_var, width=30, state="readonly")
    ship_combo.grid(row=0, column=1, sticky=tk.W, padx=(0, 8))
    ship_combo.bind("<<ComboboxSelected>>", lambda e: on_ship_selected())

    find_btn = ttk.Button(top, text="Find Shipyards in System", command=lambda: on_find())
    find_btn.grid(row=0, column=2, sticky=tk.W, padx=(0, 12))

    status_var = tk.StringVar(value="Select a ship to get started.")
    ttk.Label(top, textvariable=status_var, anchor=tk.W).grid(
        row=0, column=3, sticky=tk.EW, padx=(0, 6)
    )
    top.columnconfigure(3, weight=1)  # Let the status label stretch

    # ── Left panel — current ship status + action buttons ─────────────────
    left = ttk.LabelFrame(parent, text="Ship Status", padding=8)
    left.grid(row=1, column=0, sticky=tk.NSEW, padx=(6, 3), pady=6)

    def _info_row(frame, row, label, var):
        """Add a bold label and a StringVar value on the same row."""
        ttk.Label(frame, text=label, font=("TkDefaultFont", 9, "bold")).grid(
            row=row, column=0, sticky=tk.W, pady=(0, 2)
        )
        ttk.Label(frame, textvariable=var, anchor=tk.W).grid(
            row=row, column=1, sticky=tk.W, padx=(8, 0), pady=(0, 2)
        )

    loc_var     = tk.StringVar(value="—")
    system_var  = tk.StringVar(value="—")
    ship_status = tk.StringVar(value="—")   # e.g. DOCKED, IN_ORBIT, IN_TRANSIT
    fuel_var    = tk.StringVar(value="—")
    arrival_var = tk.StringVar(value="—")   # countdown or "Arrived"

    _info_row(left, 0, "Location:", loc_var)
    _info_row(left, 1, "System:",   system_var)
    _info_row(left, 2, "Status:",   ship_status)
    _info_row(left, 3, "Fuel:",     fuel_var)
    _info_row(left, 4, "Arrival:",  arrival_var)

    btn_frame = ttk.Frame(left)
    btn_frame.grid(row=5, column=0, columnspan=2, sticky=tk.EW, pady=(12, 0))

    orbit_btn   = ttk.Button(btn_frame, text="🚀  Orbit",   state=tk.DISABLED, command=lambda: on_orbit())
    dock_btn    = ttk.Button(btn_frame, text="⚓  Dock",    state=tk.DISABLED, command=lambda: on_dock())
    refresh_btn = ttk.Button(btn_frame, text="↻  Refresh",                    command=lambda: on_refresh_ship())

    orbit_btn.grid(  row=0, column=0, sticky=tk.EW, padx=(0, 4))
    dock_btn.grid(   row=0, column=1, sticky=tk.EW, padx=(0, 4))
    refresh_btn.grid(row=0, column=2, sticky=tk.EW)

    refuel_btn = ttk.Button(btn_frame, text="⛽  Refuel", state=tk.DISABLED, command=lambda: on_refuel())
    refuel_btn.grid(row=1, column=0, columnspan=3, sticky=tk.EW, pady=(6, 0))

    # Small hint below the refuel button
    ttk.Label(
        btn_frame,
        text="Refuel requires DOCKED at a waypoint with a MARKETPLACE selling FUEL.",
        foreground="#888",
        wraplength=200,
        justify=tk.LEFT,
    ).grid(row=2, column=0, columnspan=3, sticky=tk.W, pady=(2, 0))

    btn_frame.columnconfigure((0, 1, 2), weight=1)
    left.columnconfigure(1, weight=1)

    # ── Right panel — shipyards list + Navigate button ────────────────────
    right = ttk.LabelFrame(parent, text="Shipyards in System  (select destination)", padding=5)
    right.grid(row=1, column=1, sticky=tk.NSEW, padx=(3, 6), pady=6)

    yard_tree = ttk.Treeview(
        right,
        columns=("Waypoint", "Type", "Distance"),
        show="headings",   # "headings" means don't show a tree toggle column
        height=14,
        selectmode="browse",  # Only one row selectable at a time
    )
    yard_tree.heading("Waypoint", text="Waypoint")
    yard_tree.heading("Type",     text="Type")
    yard_tree.heading("Distance", text="Dist (units)")
    yard_tree.column("Waypoint",  width=160, anchor=tk.W)
    yard_tree.column("Type",      width=140, anchor=tk.W)
    yard_tree.column("Distance",  width=90,  anchor=tk.E)
    yard_tree.grid(row=0, column=0, sticky=tk.NSEW)

    yard_scroll = ttk.Scrollbar(right, orient=tk.VERTICAL, command=yard_tree.yview)
    yard_scroll.grid(row=0, column=1, sticky=tk.NS)
    yard_tree.config(yscrollcommand=yard_scroll.set)

    # Enable Navigate whenever a row is selected
    yard_tree.bind("<<TreeviewSelect>>", lambda e: _update_nav_btn())

    nav_btn = ttk.Button(
        right,
        text="➤  Navigate to Selected Shipyard",
        state=tk.DISABLED,
        command=lambda: on_navigate(),
    )
    nav_btn.grid(row=1, column=0, columnspan=2, sticky=tk.EW, pady=(6, 0))

    right.columnconfigure(0, weight=1)
    right.rowconfigure(0, weight=1)

    # Make the right panel expand to fill remaining space
    parent.columnconfigure(0, weight=0)
    parent.columnconfigure(1, weight=1)
    parent.rowconfigure(1, weight=1)

    # =========================================================================
    # Internal helpers
    # =========================================================================

    def _current_ship_symbol() -> str:
        """Extract just the ship symbol from the combobox label "SYM  (SYSTEM)"."""
        raw = ship_var.get()
        return raw.split("  ")[0].strip() if raw else ""

    def _update_ship_panel(ship: dict):
        """Populate the left panel with data from a ship dict."""
        nav  = ship.get("nav", {})
        fuel = ship.get("fuel", {})

        loc_var.set(    nav.get("waypointSymbol", "?"))
        system_var.set( nav.get("systemSymbol",   "?"))
        current_status = nav.get("status", "?")
        ship_status.set(current_status)

        curr = fuel.get("current", "?")
        cap  = fuel.get("capacity", "?")
        fuel_var.set(f"{curr} / {cap}")

        # Show arrival countdown if the ship is in transit
        route   = nav.get("route", {})
        arr_raw = route.get("arrival")
        if arr_raw:
            try:
                arr_dt = datetime.fromisoformat(arr_raw.replace("Z", "+00:00"))
                delta  = arr_dt - datetime.now(timezone.utc)
                if delta.total_seconds() > 0:
                    mins, secs = divmod(int(delta.total_seconds()), 60)
                    arrival_var.set(f"{mins}m {secs}s remaining")
                else:
                    arrival_var.set("Arrived")
            except Exception:
                arrival_var.set(arr_raw)
        else:
            arrival_var.set("—")

        # Enable/disable buttons based on current nav status
        is_docked   = (current_status == "DOCKED")
        is_in_orbit = (current_status == "IN_ORBIT")
        orbit_btn.config( state=tk.NORMAL if is_docked   else tk.DISABLED)
        dock_btn.config(  state=tk.NORMAL if is_in_orbit else tk.DISABLED)
        refuel_btn.config(state=tk.NORMAL if is_docked   else tk.DISABLED)
        _update_nav_btn(current_status)

    def _update_nav_btn(current_status: str = ""):
        """Enable Navigate only when idle (DOCKED or IN_ORBIT) + destination selected."""
        if not current_status:
            current_status = ship_status.get()
        # "IN_TRANSIT" means the ship is already moving — block navigation
        blocked = current_status in ("", "IN_TRANSIT", "—", "?", "UNKNOWN")
        can_nav = not blocked and bool(yard_tree.selection())
        nav_btn.config(state=tk.NORMAL if can_nav else tk.DISABLED)

    def _dist(wp: dict, ox: float, oy: float) -> float:
        """Calculate straight-line distance between waypoint and (ox, oy)."""
        return math.hypot(wp.get("x", 0) - ox, wp.get("y", 0) - oy)

    # =========================================================================
    # Event handlers — one per user action
    # =========================================================================

    def reload_ships():
        """
        Refresh the ship dropdown with the latest list from the API.

        main.py calls this whenever the user switches to the Navigation tab.
        """
        ships  = _get_my_ships(ctx)
        labels = [f"{s['symbol']}  ({s['nav']['systemSymbol']})" for s in ships]
        ship_combo["values"] = labels
        if ship_var.get() not in labels:
            ship_var.set(labels[0] if labels else "")
        if ship_var.get():
            on_ship_selected()

    def on_ship_selected():
        """Called when the player picks a ship — loads its current status."""
        sym = _current_ship_symbol()
        if not sym:
            return
        ship = _get_ship(sym, ctx)
        if ship:
            _update_ship_panel(ship)
            # Remember the system so "Find Shipyards" knows where to search
            _current_system[0] = ship.get("nav", {}).get("systemSymbol", "")
        else:
            status_var.set(f"Failed to load ship {sym}.")

    def on_find():
        """Search for all SHIPYARD waypoints in the selected ship's system."""
        sym = _current_ship_symbol()
        if not sym:
            status_var.set("Select a ship first.")
            return
        system = _current_system[0]
        if not system:
            status_var.set("Cannot determine ship's system.")
            return

        status_var.set(f"Searching for shipyards in {system}…")
        parent.update_idletasks()  # Force a UI refresh so user sees the message

        waypoints, err = _find_shipyards(system, ctx)
        if waypoints is None:
            status_var.set(f"Search failed: {err}")
            return

        _shipyards.clear()
        _shipyards.extend(waypoints)

        # Get the ship's current coordinates to sort waypoints by distance
        ship = _get_ship(sym, ctx)
        sx, sy = 0, 0
        current_wp = ""
        if ship:
            pos = ship.get("nav", {}).get("route", {}).get("destination", {})
            sx  = pos.get("x", 0)
            sy  = pos.get("y", 0)
            current_wp = ship.get("nav", {}).get("waypointSymbol", "")

        yard_tree.delete(*yard_tree.get_children())
        for wp in sorted(_shipyards, key=lambda w: _dist(w, sx, sy)):
            dist   = _dist(wp, sx, sy)
            is_here = (wp["symbol"] == current_wp)
            # Mark the waypoint where our ship already is with a "◀ here" label
            label   = wp["symbol"] + ("  ◀ here" if is_here else "")
            tag     = ("here",) if is_here else ()
            yard_tree.insert("", "end", iid=wp["symbol"],
                             values=(label, wp.get("type", "?"), f"{dist:.0f}"),
                             tags=tag)

        yard_tree.tag_configure("here", foreground="#888")  # Dim the current waypoint
        status_var.set(
            f"{len(_shipyards)} shipyard(s) in {system}. "
            "Select a destination and click Navigate."
        )

    def on_orbit():
        """Move the ship from DOCKED into IN_ORBIT."""
        sym = _current_ship_symbol()
        status_var.set("Moving to orbit…")
        parent.update_idletasks()
        data, err = _post_action(ctx.ship_orbit_url.format(sym), {}, ctx)
        if data is None:
            status_var.set(f"Orbit failed: {err}")
            return
        nav = data.get("nav", {})
        new_status = nav.get("status", "IN_ORBIT")
        ship_status.set(new_status)
        orbit_btn.config(state=tk.DISABLED)
        dock_btn.config( state=tk.NORMAL)
        _update_nav_btn(new_status)
        status_var.set(f"In orbit at {nav.get('waypointSymbol', '?')}.")

    def on_dock():
        """Land the ship at its current waypoint (IN_ORBIT → DOCKED)."""
        sym = _current_ship_symbol()
        status_var.set("Docking…")
        parent.update_idletasks()
        data, err = _post_action(ctx.ship_dock_url.format(sym), {}, ctx)
        if data is None:
            status_var.set(f"Dock failed: {err}")
            return
        nav = data.get("nav", {})
        new_status = nav.get("status", "DOCKED")
        ship_status.set(new_status)
        dock_btn.config(  state=tk.DISABLED)
        orbit_btn.config( state=tk.NORMAL)
        nav_btn.config(   state=tk.DISABLED)  # Can't navigate while docked
        refuel_btn.config(state=tk.NORMAL)
        status_var.set(f"Docked at {nav.get('waypointSymbol', '?')}.")

    def on_refuel():
        """Refuel the ship.  Ship must be DOCKED at a waypoint with a fuel marketplace."""
        sym = _current_ship_symbol()
        status_var.set("Refueling…")
        parent.update_idletasks()
        data, err = _post_action(ctx.ship_refuel_url.format(sym), {}, ctx)
        if data is None:
            status_var.set(f"Refuel failed: {err}")
            return
        fuel = data.get("fuel", {})
        curr = fuel.get("current", "?")
        cap  = fuel.get("capacity", "?")
        fuel_var.set(f"{curr} / {cap}")
        cost = data.get("transaction", {}).get("totalPrice")
        msg  = f"Refueled: {curr}/{cap} fuel."
        if cost is not None:
            msg += f"  Cost: {cost:,} credits."
        status_var.set(msg)

    def on_navigate():
        """
        Send the ship toward the selected destination waypoint.

        If the ship is still DOCKED the function automatically orbits first,
        because the SpaceTraders API requires IN_ORBIT to navigate.
        """
        sym = _current_ship_symbol()
        sel = yard_tree.selection()
        if not sel:
            status_var.set("Select a destination first.")
            return
        dest = sel[0]   # The tree row IID is the waypoint symbol

        current_status = ship_status.get()
        if current_status == "IN_TRANSIT":
            status_var.set("Ship is already in transit — wait for arrival then click ↻ Refresh.")
            return

        # Auto-orbit if docked — required before navigating
        if current_status == "DOCKED":
            status_var.set("Still docked — moving to orbit first…")
            parent.update_idletasks()
            orb_data, orb_err = _post_action(ctx.ship_orbit_url.format(sym), {}, ctx)
            if orb_data is None:
                status_var.set(f"Orbit failed: {orb_err}")
                return
            new_status = orb_data.get("nav", {}).get("status", "IN_ORBIT")
            ship_status.set(new_status)
            orbit_btn.config(state=tk.DISABLED)
            dock_btn.config( state=tk.NORMAL)

        status_var.set(f"Navigating to {dest}…")
        parent.update_idletasks()
        data, err = _post_action(
            ctx.ship_navigate_url.format(sym),
            {"waypointSymbol": dest},
            ctx,
        )
        if data is None:
            status_var.set(f"Navigation failed: {err}")
            return

        nav   = data.get("nav", {})
        route = nav.get("route", {})
        arr   = route.get("arrival", "")

        # Show a countdown to arrival
        try:
            arr_dt = datetime.fromisoformat(arr.replace("Z", "+00:00"))
            delta  = arr_dt - datetime.now(timezone.utc)
            mins, secs = divmod(max(0, int(delta.total_seconds())), 60)
            arrival_var.set(f"{mins}m {secs}s remaining")
        except Exception:
            arrival_var.set(arr or "—")

        loc_var.set(nav.get("waypointSymbol", "?"))
        ship_status.set(nav.get("status", "IN_TRANSIT"))
        # All buttons disabled while in transit
        orbit_btn.config(state=tk.DISABLED)
        dock_btn.config( state=tk.DISABLED)
        nav_btn.config(  state=tk.DISABLED)
        status_var.set(f"En route to {dest}.  Click ↻ Refresh once arrived to dock.")

    def on_refresh_ship():
        """Re-fetch the ship's status from the API and update the left panel."""
        sym = _current_ship_symbol()
        if not sym:
            status_var.set("Select a ship first.")
            return
        ship = _get_ship(sym, ctx)
        if ship:
            _update_ship_panel(ship)
            status_var.set("Refreshed.")
        else:
            status_var.set("Failed to refresh ship data.")

    # Return the reload callable so main.py can call it on tab activation
    return reload_ships
