"""
upgrade.py — Ship Mount Upgrade Dialog
=======================================
This module creates a pop-up window (modal dialog) that lets you:
  1. See which mounts are currently installed on a ship.
  2. Install new mounts from the ship's cargo.
  3. Remove existing mounts back into cargo.
  4. Transfer cargo (including mounts) to another ship.

How it connects to the rest of the app
---------------------------------------
main.py passes an UpgradeContext object when calling open_upgrade_dialog().
The context holds all the URLs and helper functions we need, so this file
does not have to import from main.py directly (avoiding circular imports).
"""

import tkinter as tk
from tkinter import ttk
from dataclasses import dataclass
from typing import Callable

import requests


# =============================================================================
# Context — data passed in from main.py
# =============================================================================

@dataclass
class UpgradeContext:
    """
    Holds everything this module needs from the outside world.

    Using a dataclass (instead of global variables) keeps the code clean
    and makes it easy to see exactly what information is required.
    """
    root:             tk.Tk       # The main application window (parent for dialogs)
    request_headers:  Callable    # Function that returns {"Authorization": "Bearer …"}
    player_worth_var: tk.StringVar  # Tkinter variable shown in the Summary tab
    refresh_summary:  Callable    # Call this after changes to refresh the Summary tab

    # API URL templates.  Use .format(ship_symbol) or .format(ship, waypoint)
    # to turn them into real URLs before making requests.
    my_ships_url:     str   # GET list of all your ships
    ship_mounts_url:  str   # GET/DELETE mounts on a specific ship
    ship_cargo_url:   str   # GET cargo inventory of a specific ship
    install_mount_url: str  # POST to install a mount from cargo
    remove_mount_url:  str  # POST to remove an installed mount into cargo
    ship_orbit_url:   str   # POST to move the ship into orbit
    ship_dock_url:    str   # POST to dock the ship at a waypoint
    ship_transfer_url: str  # POST to transfer cargo to another ship
    shipyard_url:     str   # GET info about a shipyard at a waypoint


# =============================================================================
# API helpers — each function makes exactly one kind of network request
# =============================================================================

def _get_ship(ship_symbol: str, ctx: UpgradeContext) -> dict | None:
    """
    Fetch full details for one ship.

    Returns the ship dict on success, or None if the request fails.
    The ship dict contains nav, fuel, cargo, mounts, etc.
    """
    headers = ctx.request_headers(require_token=True)
    if headers is None:
        return None  # Not logged in
    try:
        resp = requests.get(f"{ctx.my_ships_url}/{ship_symbol}", headers=headers)
        if resp.status_code == 200:
            return resp.json()["data"]
    except ConnectionError:
        pass
    return None


def _get_shipyard(system: str, waypoint: str, ctx: UpgradeContext) -> dict | None:
    """
    Fetch shipyard details for a waypoint (needs a ship present there).

    Returns the shipyard dict, or None on failure.
    """
    headers = ctx.request_headers(require_token=True)
    if headers is None:
        return None
    try:
        resp = requests.get(ctx.shipyard_url.format(system, waypoint), headers=headers)
        if resp.status_code == 200:
            return resp.json()["data"]
    except ConnectionError:
        pass
    return None


def _get_mounts(ship_symbol: str, ctx: UpgradeContext) -> list:
    """
    Return list of mounts currently installed on the ship.

    Each item is a dict with keys like "symbol", "name", "description".
    Returns an empty list if the request fails.
    """
    headers = ctx.request_headers(require_token=True)
    if headers is None:
        return []
    try:
        resp = requests.get(ctx.ship_mounts_url.format(ship_symbol), headers=headers)
        if resp.status_code == 200:
            return resp.json()["data"]
    except ConnectionError:
        pass
    return []


def _get_cargo_mounts(ship_symbol: str, ctx: UpgradeContext) -> list:
    """
    Return only the mount items sitting in the ship's cargo.

    Mount items have symbols starting with "MOUNT_".
    Returns an empty list if nothing found.
    """
    headers = ctx.request_headers(require_token=True)
    if headers is None:
        return []
    try:
        resp = requests.get(ctx.ship_cargo_url.format(ship_symbol), headers=headers)
        if resp.status_code == 200:
            cargo = resp.json()["data"]
            # Only keep items whose symbol starts with "MOUNT_"
            return [
                item for item in cargo.get("inventory", [])
                if item.get("symbol", "").startswith("MOUNT_")
            ]
    except ConnectionError:
        pass
    return []


def _install_mount(ship_symbol: str, mount_symbol: str, ctx: UpgradeContext):
    """
    Install a mount from cargo onto the ship.

    The ship must be DOCKED at a shipyard for this to work.
    Returns (result_dict, error_message).  On success, error_message is None.
    """
    headers = ctx.request_headers(require_token=True)
    if headers is None:
        return None, "Not logged in."
    try:
        resp = requests.post(
            ctx.install_mount_url.format(ship_symbol),
            json={"symbol": mount_symbol},
            headers={**headers, "Content-Type": "application/json"},
        )
        if resp.status_code == 201:
            return resp.json()["data"], None
        # Try to extract a friendly error message from the API response
        try:
            return None, resp.json()["error"]["message"]
        except Exception:
            return None, resp.text
    except ConnectionError as ce:
        return None, str(ce)


def _remove_mount(ship_symbol: str, mount_symbol: str, ctx: UpgradeContext):
    """
    Remove an installed mount back into the ship's cargo.

    The ship must be DOCKED at a shipyard.
    Returns (result_dict, error_message).
    """
    headers = ctx.request_headers(require_token=True)
    if headers is None:
        return None, "Not logged in."
    try:
        resp = requests.post(
            ctx.remove_mount_url.format(ship_symbol),
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


def _get_ships_at_waypoint(waypoint: str, ctx: UpgradeContext) -> list:
    """
    Return all YOUR ships that are currently at the given waypoint.

    Used to find valid transfer targets when moving cargo.
    """
    headers = ctx.request_headers(require_token=True)
    if headers is None:
        return []
    try:
        resp = requests.get(ctx.my_ships_url, headers=headers, params={"limit": 20})
        if resp.status_code == 200:
            all_ships = resp.json()["data"]
            # Filter to only ships whose current waypoint matches
            return [
                s for s in all_ships
                if s.get("nav", {}).get("waypointSymbol") == waypoint
            ]
    except ConnectionError:
        pass
    return []


def _transfer_cargo(
    from_ship: str, to_ship: str, item_symbol: str, units: int, ctx: UpgradeContext
):
    """
    Transfer *units* of *item_symbol* from one ship to another.

    Both ships must be at the same waypoint.
    Returns (result_dict, error_message).
    """
    headers = ctx.request_headers(require_token=True)
    if headers is None:
        return None, "Not logged in."
    try:
        resp = requests.post(
            ctx.ship_transfer_url.format(from_ship),
            json={"tradeSymbol": item_symbol, "units": units, "shipSymbol": to_ship},
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


def _orbit_ship(ship_symbol: str, ctx: UpgradeContext):
    """Move the ship out of dock into orbit. Returns (nav_dict, error_message)."""
    headers = ctx.request_headers(require_token=True)
    if headers is None:
        return None, "Not logged in."
    try:
        resp = requests.post(
            ctx.ship_orbit_url.format(ship_symbol),
            json={},
            headers={**headers, "Content-Type": "application/json"},
        )
        if resp.status_code == 200:
            return resp.json()["data"]["nav"], None
        try:
            return None, resp.json()["error"]["message"]
        except Exception:
            return None, resp.text
    except ConnectionError as ce:
        return None, str(ce)


def _dock_ship(ship_symbol: str, ctx: UpgradeContext):
    """Dock the ship at its current waypoint. Returns (nav_dict, error_message)."""
    headers = ctx.request_headers(require_token=True)
    if headers is None:
        return None, "Not logged in."
    try:
        resp = requests.post(
            ctx.ship_dock_url.format(ship_symbol),
            json={},
            headers={**headers, "Content-Type": "application/json"},
        )
        if resp.status_code == 200:
            return resp.json()["data"]["nav"], None
        try:
            return None, resp.json()["error"]["message"]
        except Exception:
            return None, resp.text
    except ConnectionError as ce:
        return None, str(ce)


# =============================================================================
# Main dialog — called from main.py when you double-click a ship
# =============================================================================

def open_upgrade_dialog(ship_symbol: str, ctx: UpgradeContext):
    """
    Open the mount upgrade dialog for *ship_symbol*.

    The dialog has three panels side by side:
      Left   — Installed mounts (with a Remove button)
      Centre — Ship info (location, status, dock/orbit controls)
      Right  — Mounts in cargo (with Install and Transfer buttons)
    """

    # ── Create the dialog window ─────────────────────────────────────────
    # Toplevel creates a new window.  "transient" makes it stay on top of
    # the main window.  "grab_set" blocks interaction with other windows
    # until this one is closed (modal behaviour).
    dialog = tk.Toplevel(ctx.root)
    dialog.title(f"Upgrade — {ship_symbol}")
    dialog.transient(ctx.root)
    dialog.grab_set()

    # ── State variables ───────────────────────────────────────────────────
    # We use single-element lists as a trick to let inner functions (closures)
    # modify these values.  A plain variable like  ship_data = None  cannot
    # be reassigned inside a nested function without "nonlocal" — the list
    # avoids that complication.
    _ship_data = [None]   # Holds the full ship dict after fetching

    # These track whether we know the ship is at a shipyard (needed for installs)
    _at_shipyard = [False]

    # ── Status bar at the bottom ──────────────────────────────────────────
    status_var = tk.StringVar(value="Loading…")
    status_bar = ttk.Label(dialog, textvariable=status_var, relief=tk.SUNKEN, anchor=tk.W)
    status_bar.grid(row=1, column=0, columnspan=3, sticky=tk.EW, padx=4, pady=(0, 4))

    # ── Three-column layout ───────────────────────────────────────────────
    left_frame   = ttk.LabelFrame(dialog, text="Installed Mounts",  padding=6)
    centre_frame = ttk.LabelFrame(dialog, text="Ship Info",         padding=6)
    right_frame  = ttk.LabelFrame(dialog, text="Cargo — Mounts",    padding=6)

    left_frame.grid(  row=0, column=0, sticky=tk.NSEW, padx=(6, 3), pady=6)
    centre_frame.grid(row=0, column=1, sticky=tk.NSEW, padx=3,       pady=6)
    right_frame.grid( row=0, column=2, sticky=tk.NSEW, padx=(3, 6),  pady=6)

    dialog.columnconfigure(0, weight=1)
    dialog.columnconfigure(1, weight=1)
    dialog.columnconfigure(2, weight=1)
    dialog.rowconfigure(0, weight=1)

    # ── Left panel — installed mounts ─────────────────────────────────────
    # A Listbox displays a scrollable list of text items.
    inst_lb = tk.Listbox(left_frame, height=10, width=28, selectmode=tk.SINGLE,
                         exportselection=False)
    inst_lb.grid(row=0, column=0, sticky=tk.NSEW)
    inst_scroll = ttk.Scrollbar(left_frame, orient=tk.VERTICAL, command=inst_lb.yview)
    inst_scroll.grid(row=0, column=1, sticky=tk.NS)
    inst_lb.config(yscrollcommand=inst_scroll.set)

    remove_btn = ttk.Button(left_frame, text="Remove Selected Mount",
                            state=tk.DISABLED, command=lambda: on_remove())
    remove_btn.grid(row=1, column=0, columnspan=2, sticky=tk.EW, pady=(6, 0))

    left_frame.columnconfigure(0, weight=1)
    left_frame.rowconfigure(0, weight=1)

    # ── Centre panel — ship info and dock/orbit buttons ───────────────────
    # We use a small helper to add a label/value row cleanly
    def _add_info_row(parent, row, label_text, value_var):
        """Add a "Label: [value]" row to the given frame."""
        ttk.Label(parent, text=label_text, font=("TkDefaultFont", 9, "bold")).grid(
            row=row, column=0, sticky=tk.W, pady=(0, 2)
        )
        ttk.Label(parent, textvariable=value_var, anchor=tk.W).grid(
            row=row, column=1, sticky=tk.W, padx=(8, 0), pady=(0, 2)
        )

    loc_var    = tk.StringVar(value="—")
    system_var = tk.StringVar(value="—")
    status_var2 = tk.StringVar(value="—")  # ship nav status (DOCKED / IN_ORBIT / …)
    fuel_var   = tk.StringVar(value="—")
    cargo_var  = tk.StringVar(value="—")

    _add_info_row(centre_frame, 0, "Location:", loc_var)
    _add_info_row(centre_frame, 1, "System:",   system_var)
    _add_info_row(centre_frame, 2, "Status:",   status_var2)
    _add_info_row(centre_frame, 3, "Fuel:",     fuel_var)
    _add_info_row(centre_frame, 4, "Cargo:",    cargo_var)

    # Dock/Orbit/Refresh buttons
    btn_row = ttk.Frame(centre_frame)
    btn_row.grid(row=5, column=0, columnspan=2, sticky=tk.EW, pady=(12, 0))

    dock_btn    = ttk.Button(btn_row, text="⚓  Dock",    state=tk.DISABLED, command=lambda: on_dock())
    orbit_btn   = ttk.Button(btn_row, text="🚀  Orbit",   state=tk.DISABLED, command=lambda: on_orbit())
    refresh_btn = ttk.Button(btn_row, text="↻  Refresh",                    command=lambda: on_refresh())

    dock_btn.grid(  row=0, column=0, sticky=tk.EW, padx=(0, 4))
    orbit_btn.grid( row=0, column=1, sticky=tk.EW, padx=(0, 4))
    refresh_btn.grid(row=0, column=2, sticky=tk.EW)
    btn_row.columnconfigure((0, 1, 2), weight=1)

    centre_frame.columnconfigure(1, weight=1)

    # ── Right panel — cargo mounts + install + transfer ───────────────────
    cargo_lb = tk.Listbox(right_frame, height=10, width=28, selectmode=tk.SINGLE,
                          exportselection=False)
    cargo_lb.grid(row=0, column=0, sticky=tk.NSEW)
    cargo_scroll = ttk.Scrollbar(right_frame, orient=tk.VERTICAL, command=cargo_lb.yview)
    cargo_scroll.grid(row=0, column=1, sticky=tk.NS)
    cargo_lb.config(yscrollcommand=cargo_scroll.set)

    install_btn  = ttk.Button(right_frame, text="Install Selected Mount",
                              state=tk.DISABLED, command=lambda: on_install())
    transfer_btn = ttk.Button(right_frame, text="Transfer to Another Ship",
                              state=tk.DISABLED, command=lambda: on_transfer())
    install_btn.grid( row=1, column=0, columnspan=2, sticky=tk.EW, pady=(6, 0))
    transfer_btn.grid(row=2, column=0, columnspan=2, sticky=tk.EW, pady=(4, 0))

    right_frame.columnconfigure(0, weight=1)
    right_frame.rowconfigure(0, weight=1)

    # ── Helper: enable/disable buttons based on current state ────────────

    def _update_buttons(ship_nav_status: str = ""):
        """Enable or disable dock/orbit/install buttons based on ship status."""
        if not ship_nav_status:
            ship_nav_status = status_var2.get()

        is_docked   = (ship_nav_status == "DOCKED")
        is_in_orbit = (ship_nav_status == "IN_ORBIT")

        dock_btn.config( state=tk.NORMAL if is_in_orbit else tk.DISABLED)
        orbit_btn.config(state=tk.NORMAL if is_docked   else tk.DISABLED)

        # Install requires DOCKED at a shipyard
        can_install = is_docked and _at_shipyard[0] and bool(cargo_lb.curselection())
        install_btn.config(state=tk.NORMAL if can_install else tk.DISABLED)

        # Transfer just needs a mount selected
        can_transfer = bool(cargo_lb.curselection())
        transfer_btn.config(state=tk.NORMAL if can_transfer else tk.DISABLED)

        # Remove just needs an installed mount selected
        remove_btn.config(
            state=tk.NORMAL if (is_docked and _at_shipyard[0] and inst_lb.curselection())
            else tk.DISABLED
        )

    # Bind selection changes so buttons update immediately
    inst_lb.bind( "<<ListboxSelect>>", lambda e: _update_buttons())
    cargo_lb.bind("<<ListboxSelect>>", lambda e: _update_buttons())

    # ── Helper: repopulate the installed-mounts list ──────────────────────

    def _repopulate_installed(mounts: list):
        """Clear and refill the installed mounts listbox."""
        inst_lb.delete(0, tk.END)
        for m in mounts:
            sym  = m.get("symbol", "?")
            name = m.get("name", "")
            # Show "MOUNT_SYMBOL — Mount Name" or just "MOUNT_SYMBOL"
            label = f"{sym}  —  {name}" if name else sym
            inst_lb.insert(tk.END, label)

    def _repopulate_cargo(items: list):
        """Clear and refill the cargo mounts listbox."""
        cargo_lb.delete(0, tk.END)
        for item in items:
            sym   = item.get("symbol", "?")
            units = item.get("units", 1)
            cargo_lb.insert(tk.END, f"{sym}  ×{units}")

    # ── Initial data load ────────────────────────────────────────────────

    def _load_ship_data():
        """Fetch ship info and fill all three panels."""
        ship = _get_ship(ship_symbol, ctx)
        if ship is None:
            status_var.set(f"Could not load ship {ship_symbol}.")
            return
        _ship_data[0] = ship

        # Populate centre panel labels
        nav    = ship.get("nav", {})
        fuel   = ship.get("fuel", {})
        cargo  = ship.get("cargo", {})

        loc_var.set(   nav.get("waypointSymbol", "?"))
        system_var.set(nav.get("systemSymbol",   "?"))
        nav_status = nav.get("status", "?")
        status_var2.set(nav_status)
        fuel_var.set(  f'{fuel.get("current", "?")} / {fuel.get("capacity", "?")}')
        cargo_var.set( f'{cargo.get("units", "?")} / {cargo.get("capacity", "?")}')

        # Check whether the ship is at a shipyard
        system   = nav.get("systemSymbol", "")
        waypoint = nav.get("waypointSymbol", "")
        yard = _get_shipyard(system, waypoint, ctx) if system and waypoint else None
        _at_shipyard[0] = yard is not None

        # Fill left panel (installed mounts)
        mounts = _get_mounts(ship_symbol, ctx)
        _repopulate_installed(mounts)

        # Fill right panel (cargo mounts)
        cargo_items = _get_cargo_mounts(ship_symbol, ctx)
        _repopulate_cargo(cargo_items)

        _update_buttons(nav_status)

        if nav_status == "DOCKED" and not _at_shipyard[0]:
            status_var.set("Docked, but not at a shipyard — navigate to a shipyard to install/remove mounts.")
        elif _at_shipyard[0]:
            status_var.set(f"At shipyard: {waypoint}")
        else:
            status_var.set(f"Status: {nav_status}")

    _load_ship_data()

    # ==========================================================================
    # Event handlers — one function per button
    # ==========================================================================

    def on_dock():
        """Move the ship from orbit into dock."""
        status_var.set("Docking…")
        dialog.update_idletasks()   # Refresh the UI immediately so user sees "Docking…"
        nav, err = _dock_ship(ship_symbol, ctx)
        if nav is None:
            status_var.set(f"Dock failed: {err}")
            return
        new_status = nav.get("status", "DOCKED")
        status_var2.set(new_status)
        _update_buttons(new_status)
        status_var.set(f"Docked at {nav.get('waypointSymbol', '?')}.")

    def on_orbit():
        """Move the ship from dock into orbit."""
        status_var.set("Moving to orbit…")
        dialog.update_idletasks()
        nav, err = _orbit_ship(ship_symbol, ctx)
        if nav is None:
            status_var.set(f"Orbit failed: {err}")
            return
        new_status = nav.get("status", "IN_ORBIT")
        status_var2.set(new_status)
        _update_buttons(new_status)
        status_var.set(f"In orbit at {nav.get('waypointSymbol', '?')}.")

    def on_refresh():
        """Reload all ship data from the API."""
        status_var.set("Refreshing…")
        dialog.update_idletasks()
        _load_ship_data()

    def on_install():
        """Install the selected cargo mount onto the ship."""
        sel = cargo_lb.curselection()
        if not sel:
            return
        # Parse the symbol out of "MOUNT_SYMBOL  ×N"
        raw_label   = cargo_lb.get(sel[0])
        mount_symbol = raw_label.split("  ×")[0].strip()

        status_var.set(f"Installing {mount_symbol}…")
        dialog.update_idletasks()

        result, err = _install_mount(ship_symbol, mount_symbol, ctx)
        if result is None:
            status_var.set(f"Install failed: {err}")
            return

        # Refresh both panels to reflect the change
        mounts = result.get("mounts", [])
        _repopulate_installed(mounts)
        new_cargo = _get_cargo_mounts(ship_symbol, ctx)
        _repopulate_cargo(new_cargo)

        # Refresh wallet display
        agent = result.get("agent", {})
        if agent.get("credits") is not None:
            ctx.player_worth_var.set(f"{agent['credits']:n}")

        _update_buttons()
        status_var.set(f"Installed {mount_symbol}.")

    def on_remove():
        """Remove the selected installed mount back into cargo."""
        sel = inst_lb.curselection()
        if not sel:
            return
        # The listbox entry is "MOUNT_SYMBOL  —  Mount Name" — take the first part
        raw_label    = inst_lb.get(sel[0])
        mount_symbol = raw_label.split("  —  ")[0].strip()

        status_var.set(f"Removing {mount_symbol}…")
        dialog.update_idletasks()

        result, err = _remove_mount(ship_symbol, mount_symbol, ctx)
        if result is None:
            status_var.set(f"Remove failed: {err}")
            return

        mounts = result.get("mounts", [])
        _repopulate_installed(mounts)
        new_cargo = _get_cargo_mounts(ship_symbol, ctx)
        _repopulate_cargo(new_cargo)

        agent = result.get("agent", {})
        if agent.get("credits") is not None:
            ctx.player_worth_var.set(f"{agent['credits']:n}")

        _update_buttons()
        status_var.set(f"Removed {mount_symbol} — now in cargo.")

    def on_transfer():
        """
        Open a mini dialog to choose another ship and transfer the selected mount.

        Both ships must be at the same waypoint.
        """
        sel = cargo_lb.curselection()
        if not sel:
            return
        raw_label    = cargo_lb.get(sel[0])
        mount_symbol = raw_label.split("  ×")[0].strip()

        # Find out how many units we have
        cargo_items  = _get_cargo_mounts(ship_symbol, ctx)
        item         = next((i for i in cargo_items if i["symbol"] == mount_symbol), None)
        available    = item["units"] if item else 1

        # Find which waypoint our ship is at
        ship = _ship_data[0]
        if ship is None:
            status_var.set("No ship data loaded — click Refresh first.")
            return
        waypoint = ship.get("nav", {}).get("waypointSymbol", "")

        # Get all other ships at the same waypoint
        ships_here = [
            s for s in _get_ships_at_waypoint(waypoint, ctx)
            if s["symbol"] != ship_symbol   # Exclude the current ship
        ]

        # ── Build the transfer sub-dialog ─────────────────────────────────
        sub = tk.Toplevel(dialog)
        sub.title(f"Transfer {mount_symbol}")
        sub.transient(dialog)
        sub.grab_set()

        ttk.Label(sub, text=f"Transfer  {mount_symbol}  (×{available} available)",
                  font=("TkDefaultFont", 10, "bold")).grid(
            row=0, column=0, columnspan=2, sticky=tk.EW, padx=10, pady=(10, 4)
        )
        ttk.Label(sub, text="To ship:").grid(row=1, column=0, sticky=tk.W, padx=10, pady=4)

        dest_var = tk.StringVar()

        # Build labels showing each ship's free cargo space
        def _free_space(s: dict) -> int:
            c = s.get("cargo", {})
            return c.get("capacity", 0) - c.get("units", 0)

        ship_labels = [
            f"{s['symbol']}  (free: {_free_space(s)})"
            for s in ships_here
        ]

        dest_combo = ttk.Combobox(sub, textvariable=dest_var, values=ship_labels,
                                  state="readonly", width=34)
        dest_combo.grid(row=1, column=1, sticky=tk.EW, padx=(0, 10), pady=4)
        if ship_labels:
            dest_combo.current(0)   # Select the first option automatically

        ttk.Label(sub, text="Units:").grid(row=2, column=0, sticky=tk.W, padx=10, pady=4)
        units_var = tk.StringVar(value=str(available))
        ttk.Entry(sub, textvariable=units_var, width=8).grid(
            row=2, column=1, sticky=tk.W, padx=(0, 10), pady=4
        )

        warn_var = tk.StringVar(value="")
        warn_label = ttk.Label(sub, textvariable=warn_var, foreground="orange")
        warn_label.grid(row=3, column=0, columnspan=2, sticky=tk.EW, padx=10, pady=(0, 4))

        # The transfer button is stored in a list so the lambda below can
        # reference it before the variable is assigned (a common Python closure trick)
        xfer_btn_ref = [None]

        def _check_dest(*_):
            """Warn if destination ship has no free cargo space."""
            lbl = dest_var.get()
            if not lbl:
                return
            # Parse free space from the label string "SHIP  (free: N)"
            try:
                free = int(lbl.split("free: ")[-1].rstrip(")"))
            except ValueError:
                free = 1
            if free <= 0:
                warn_var.set("⚠  Destination cargo is full — cannot transfer.")
                if xfer_btn_ref[0]:
                    xfer_btn_ref[0].config(state=tk.DISABLED)
            else:
                warn_var.set("")
                if xfer_btn_ref[0]:
                    xfer_btn_ref[0].config(state=tk.NORMAL)

        dest_combo.bind("<<ComboboxSelected>>", _check_dest)

        sub_status = tk.StringVar(value="")
        ttk.Label(sub, textvariable=sub_status).grid(
            row=5, column=0, columnspan=2, sticky=tk.EW, padx=10, pady=(0, 8)
        )

        def do_transfer():
            """Perform the actual transfer API call."""
            lbl = dest_var.get()
            if not lbl:
                sub_status.set("Choose a destination ship.")
                return
            dest_symbol = lbl.split("  (free:")[0].strip()
            try:
                units = int(units_var.get())
            except ValueError:
                sub_status.set("Units must be a whole number.")
                return

            sub_status.set(f"Transferring {units} × {mount_symbol}…")
            sub.update_idletasks()

            result, err = _transfer_cargo(ship_symbol, dest_symbol, mount_symbol, units, ctx)
            if result is None:
                sub_status.set(f"Transfer failed: {err}")
                return

            sub_status.set(f"Transferred {units} × {mount_symbol} to {dest_symbol}.")
            # Refresh the cargo panel in the main dialog
            new_cargo = _get_cargo_mounts(ship_symbol, ctx)
            _repopulate_cargo(new_cargo)
            _update_buttons()
            ctx.refresh_summary()
            sub.after(800, sub.destroy)  # Auto-close the sub-dialog after 0.8 s

        xfer_btn = ttk.Button(sub, text="Transfer", command=do_transfer,
                              state=(tk.NORMAL if ship_labels else tk.DISABLED))
        xfer_btn.grid(row=4, column=0, columnspan=2, sticky=tk.EW, padx=10, pady=4)
        xfer_btn_ref[0] = xfer_btn   # Store so _check_dest can enable/disable it

        # Trigger an initial check in case the first option is already full
        if ship_labels:
            _check_dest()

        sub.columnconfigure(1, weight=1)
        sub.resizable(False, False)
