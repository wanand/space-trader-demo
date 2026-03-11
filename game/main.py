"""
main.py — Io Space Trading Game
================================
Entry point for the desktop GUI.  Builds the main window and all six tabs:

  0 Welcome    — Register a new agent or log in with a saved one
  1 Summary    — Your agent info, contracts, and ships (double-click a ship to upgrade)
  2 Leaderboard— Top agents by credits and chart submissions (public data)
  3 Factions   — Browse all factions and their activity scores (public data)
  4 Shipyard   — Explore shipyards in your system, buy ships, install mounts
  5 Navigation — Move your ships between shipyard waypoints

All network logic for the Shipyard and Navigation tabs lives in their own
modules (shipyard.py, navigation.py) to keep files manageable.
The upgrade dialog (double-click a ship) is in upgrade.py.

Running
--------
    python main.py
"""

# =============================================================================
# Standard library imports
# =============================================================================
import json
import locale
import os
from collections import defaultdict
from datetime import datetime
from itertools import zip_longest

# =============================================================================
# Third-party imports
# =============================================================================
import tkinter as tk
from tkinter import ttk
import requests

# =============================================================================
# Local module imports  (upgrade, shipyard, navigation each define a Context
# dataclass + a build/open function which we call further down)
# =============================================================================
from upgrade import UpgradeContext, open_upgrade_dialog
from shipyard import ShipyardContext, build_shipyard_tab
from navigation import NavigationContext, build_navigation_tab

# Use the system locale so numbers format nicely with commas (e.g. 1,234,567)
locale.setlocale(locale.LC_ALL, "")  # '' = auto-detect from OS settings
 
# =============================================================================
# File paths and environment variable names
# =============================================================================

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
AGENT_FILE = os.path.join(BASE_DIR, "agents.json")  # Saved agent name→token map

# We look for a .env file in the project root OR the game/ subfolder
ENV_FILE_CANDIDATES = (
    os.path.join(os.path.dirname(BASE_DIR), ".env"),
    os.path.join(BASE_DIR, ".env"),
)
TOKEN_ENV_KEY        = "AGENT_TOKEN"    # .env key for an existing agent token
ACCOUNT_TOKEN_ENV_KEY = "ACCOUNT_TOKEN" # .env key for the account-level token
 
# =============================================================================
# SpaceTraders API URL constants
# =============================================================================
# Most URLs with {} placeholders are used as templates:
#   e.g.  SHIP_ORBIT.format("MY-SHIP-1")  → ".../my/ships/MY-SHIP-1/orbit"
# Two-placeholder URLs like SHIPYARD use two .format() arguments:
#   e.g.  SHIPYARD.format("X1-DF55", "X1-DF55-A1")  → ".../systems/.../shipyard"

API_STATUS         = "https://api.spacetraders.io/v2/"                          # GET server status + leaderboards
LIST_FACTIONS      = "https://api.spacetraders.io/v2/factions"                  # GET all factions (public)
FACTION_DETAIL     = "https://api.spacetraders.io/v2/factions/{}"               # GET single faction
LIST_AGENTS        = "https://api.spacetraders.io/v2/agents"                    # GET all public agent profiles
CLAIM_USER         = "https://api.spacetraders.io/v2/register"                  # POST register new agent
MY_ACCOUNT         = "https://api.spacetraders.io/v2/my/agent"                  # GET your agent details
MY_CONTRACTS       = "https://api.spacetraders.io/v2/my/contracts"              # GET your contracts
MY_SHIPS           = "https://api.spacetraders.io/v2/my/ships"                  # GET your ships / POST buy
SHIP_MOUNTS        = "https://api.spacetraders.io/v2/my/ships/{}/mounts"        # GET/DELETE mounts on a ship
SHIP_CARGO         = "https://api.spacetraders.io/v2/my/ships/{}/cargo"         # GET cargo inventory
SHIP_INSTALL_MOUNT = "https://api.spacetraders.io/v2/my/ships/{}/mounts/install" # POST install mount from cargo
SHIP_REMOVE_MOUNT  = "https://api.spacetraders.io/v2/my/ships/{}/mounts/remove" # POST remove mount into cargo
SHIP_ORBIT         = "https://api.spacetraders.io/v2/my/ships/{}/orbit"         # POST move ship to orbit
SHIP_DOCK          = "https://api.spacetraders.io/v2/my/ships/{}/dock"          # POST dock ship
SHIP_NAVIGATE      = "https://api.spacetraders.io/v2/my/ships/{}/navigate"      # POST navigate to waypoint
SHIP_REFUEL        = "https://api.spacetraders.io/v2/my/ships/{}/refuel"        # POST refuel ship
SHIP_TRANSFER      = "https://api.spacetraders.io/v2/my/ships/{}/transfer"      # POST transfer cargo
SHIPYARD           = "https://api.spacetraders.io/v2/systems/{}/waypoints/{}/shipyard" # GET shipyard details
SYSTEM_WAYPOINTS   = "https://api.spacetraders.io/v2/systems/{}/waypoints"      # GET waypoints in system

# =============================================================================
# Date / time format strings
# =============================================================================
# SpaceTraders returns ISO-8601 timestamps; we show a friendly day/month/year format.
UTC_FORMAT     = "%Y-%m-%dT%H:%M:%S.%f%z"  # e.g. "2024-01-15T08:30:00.000Z"
DISPLAY_FORMAT = " %B, %Y"                  # e.g. " January, 2024" (day added separately)

# =============================================================================
# App-level state
# =============================================================================
FACTION_LOOKUPS = {}          # Cache: {symbol: name}, e.g. {"COSMIC": "The Cosmic Syndicate"}
_faction_data:   dict = {}    # Cache: {symbol: full_faction_dict} for the Factions detail panel


# =============================================================================
# Environment / .env helpers
# =============================================================================

def load_dotenv_if_present():
    """
    Read a .env file (if one exists) and set any KEY=VALUE pairs as environment
    variables.  This lets developers put their tokens in a .env file rather than
    typing them into the UI every time they launch the app.

    We try two locations: the project root and the game/ folder.
    Existing environment variables are never overwritten (setdefault).
    """
    for env_file in ENV_FILE_CANDIDATES:
        if not os.path.exists(env_file):
            continue

        try:
            with open(env_file, encoding="utf-8") as dotenv_file:
                for raw_line in dotenv_file:
                    line = raw_line.strip()
                    if not line or line.startswith("#"):
                        continue

                    if line.startswith("export "):
                        line = line[7:].strip()

                    if "=" not in line:
                        continue

                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip()

                    if not key:
                        continue

                    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"\"", "'"}:
                        value = value[1:-1]

                    os.environ.setdefault(key, value)
        except OSError:
            continue


def get_env_token():
    """Return the AGENT_TOKEN from the environment (set from .env or the OS), or ''."""
    return os.environ.get(TOKEN_ENV_KEY, "").strip()


def get_account_token():
    """Return the account-level token used for agent registration."""
    # UI field takes priority, then ACCOUNT_TOKEN env, then TOKEN env as fallback
    if "account_token_var" in globals():
        ui_val = account_token_var.get().strip()
        if ui_val:
            return ui_val

    env_val = os.environ.get(ACCOUNT_TOKEN_ENV_KEY, "").strip()
    if env_val:
        return env_val

    return get_env_token()


# Kick off .env loading immediately so tokens are available before the UI is built
load_dotenv_if_present()


# =============================================================================
# Date formatting helpers
# =============================================================================

def parse_datetime(dt):
    """Parse a SpaceTraders timestamp string into a Python datetime object."""
    return datetime.strptime(dt, UTC_FORMAT)
 
 
def format_datetime(dt_text):
    """
    Convert a raw UTC timestamp string into a human-friendly date like
    "15th January, 2024".

    The ordinal suffix (st/nd/rd/th) is computed with a small dict lookup.
    """
    dt = parse_datetime(dt_text)
    d = dt.day
    return (
        str(d)
        + ("th" if 11 <= d <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(d % 10, "th"))
        + datetime.strftime(dt, DISPLAY_FORMAT)
    )
 
 # =============================================================================
# Agent file helpers  (agents.json stores known agent name → token mappings)
# =============================================================================

def load_player_logins():
    """
    Load the agents.json file and return a dict of {agent_symbol: token}.

    The file may not exist yet (first run), or may be corrupted, so we
    return an empty dict rather than raising an exception in those cases.
    """
    if not os.path.exists(AGENT_FILE):
        return {}

    try:
        with open(AGENT_FILE, encoding="utf-8") as json_agents:
            known_agents = json.load(json_agents)
    except (OSError, json.JSONDecodeError):
        return {}

    if not isinstance(known_agents, dict):
        return {}

    clean_agents = {}
    for symbol, token in known_agents.items():
        if isinstance(symbol, str) and isinstance(token, str):
            symbol = symbol.strip()
            token = token.strip()
            if symbol and token:
                clean_agents[symbol] = token

    return clean_agents
 
 
def store_agent_login(json_result):
    """
    Save an agent’s symbol and token to agents.json so they can log in again
    without re-entering the token.  Merges with any existing entries.
    """
    symbol = json_result.get("symbol")
    token = json_result.get("token")

    if not isinstance(symbol, str) or not isinstance(token, str):
        return

    symbol = symbol.strip()
    token = token.strip()
    if not symbol or not token:
        return

    known_agents = load_player_logins()
    known_agents[symbol] = token
 
    with open(AGENT_FILE, "w", encoding="utf-8") as json_agents:
        json.dump(known_agents, json_agents)


# =============================================================================
# Auth header builder
# =============================================================================

def request_headers(require_token=False, token=None):
    """
    Build and return the HTTP headers dict needed for API requests.

    The SpaceTraders API accepts unauthenticated requests for public data
    (e.g. factions, leaderboard) but requires a Bearer token for anything
    that touches your agent account.

    Priority for finding the token:
      1. The *token* argument, if passed explicitly
      2. The player_token Tk variable (set when you log in)
      3. The AGENT_TOKEN environment variable / .env file

    If *require_token* is True and no token is found, returns None so the
    caller can bail out early rather than making an unauthenticated request.
    """
    headers = {"Accept": "application/json"}

    if token is None:
        token = player_token.get() if "player_token" in globals() else ""

    token = token.strip() if isinstance(token, str) else ""
    if not token:
        token = get_env_token()

    if token:
        headers["Authorization"] = f"Bearer {token}"
        return headers

    if require_token:
        print("Missing token. Select a saved agent or paste a valid SpaceTraders token.")
        return None

    return headers
 
 
# =============================================================================
# Faction helpers
# =============================================================================

def get_faction_lookups():
    """
    Return a dict of {faction_symbol: faction_name}, fetched once and then
    cached for the lifetime of the app.

    Used to look up human-readable faction names from symbol codes like
    "COSMIC" → "The Cosmic Syndicate".
    """
    global FACTION_LOOKUPS
    if len(FACTION_LOOKUPS) > 0:
        return FACTION_LOOKUPS
 
    try:
        response = requests.get(
            LIST_FACTIONS,
            params={"limit": 20},
            headers=request_headers(),
        )
 
        if response.status_code == 200:
            faction_json = response.json()
            for faction in faction_json["data"]:
               FACTION_LOOKUPS[faction["symbol"]] = faction["name"]
 
        else:
            print("Failed:", response.status_code, response.reason, response.text)
 
    except ConnectionError as ce:
        print("Failed:", ce)
 
    return FACTION_LOOKUPS
 
 
def refresh_factions():
    """Fetch all factions and all public agents; compute per-faction reputation scores."""
    global _faction_data
    factions_status_var.set("Loading factions\u2026")
    root.update_idletasks()

    headers = request_headers(require_token=False)
    try:
        # ---- 1. Fetch all factions ----
        page = 1
        all_factions = []
        while True:
            response = requests.get(
                LIST_FACTIONS,
                headers=headers,
                params={"limit": 20, "page": page},
            )
            if response.status_code == 200:
                data = response.json()
                batch = data["data"]
                all_factions.extend(batch)
                total = data.get("meta", {}).get("total", len(all_factions))
                if len(all_factions) >= total or not batch:
                    break
                page += 1
            else:
                factions_status_var.set(
                    f"Failed to load factions: {response.status_code} {response.reason}"
                )
                return

        # ---- 2. Fetch all public agents and aggregate per-faction ----
        factions_status_var.set("Fetching agent activity for reputation scores\u2026")
        root.update_idletasks()

        faction_stats: dict = {}  # symbol -> {agent_count, total_credits, total_ships}
        page = 1
        agents_fetched = 0
        while True:
            resp = requests.get(
                LIST_AGENTS,
                headers=headers,
                params={"limit": 20, "page": page},
            )
            if resp.status_code != 200:
                break
            data = resp.json()
            batch = data["data"]
            if not batch:
                break
            for agent in batch:
                sym = agent.get("startingFaction", "")
                if sym not in faction_stats:
                    faction_stats[sym] = {"agent_count": 0, "total_credits": 0, "total_ships": 0}
                faction_stats[sym]["agent_count"]   += 1
                faction_stats[sym]["total_credits"]  += agent.get("credits", 0)
                faction_stats[sym]["total_ships"]    += agent.get("shipCount", 0)
            agents_fetched += len(batch)
            total = data.get("meta", {}).get("total", 0)
            if agents_fetched >= total or not batch:
                break
            page += 1
            if page % 5 == 0:  # update status every 100 agents
                factions_status_var.set(f"Scoring\u2026 {agents_fetched} agents processed")
                root.update_idletasks()

        # ---- 3. Attach stats to faction dicts and populate treeview ----
        for f in all_factions:
            f["_stats"] = faction_stats.get(
                f["symbol"], {"agent_count": 0, "total_credits": 0, "total_ships": 0}
            )

        # Sort descending by agent count so the most active factions appear first
        all_factions.sort(key=lambda f: f["_stats"]["agent_count"], reverse=True)

        faction_view.delete(*faction_view.get_children())
        _faction_data = {f["symbol"]: f for f in all_factions}

        player_start = player_faction.get()
        for f in all_factions:
            st   = f["_stats"]
            tags = ("player_faction",) if f["name"] == player_start else ()
            avg  = (st["total_credits"] // st["agent_count"]) if st["agent_count"] else 0
            faction_view.insert(
                "",
                "end",
                iid=f["symbol"],
                text="faction",
                values=(
                    f["name"],
                    f.get("headquarters", "\u2014"),
                    "\u2713 Recruiting" if f.get("isRecruiting") else "Closed",
                    f"{st['agent_count']:n}",
                    f"{avg:n}",
                    f"{st['total_ships']:n}",
                ),
                tags=tags,
            )

        faction_view.tag_configure("player_faction", background="#cce5ff")
        total_agents_scored = sum(s["agent_count"] for s in faction_stats.values())
        factions_status_var.set(
            f"{len(all_factions)} factions  \u00b7  {total_agents_scored:n} agents scored."
            + ("  Your starting faction is highlighted." if player_start else "")
        )

    except ConnectionError as ce:
        factions_status_var.set(f"Connection error: {ce}")


def on_faction_select(event=None):
    """Populate the detail panel when the user clicks a faction row."""
    sel = faction_view.selection()
    if not sel:
        return
    symbol = sel[0]
    f = _faction_data.get(symbol)
    if not f:
        return
    st = f.get("_stats", {"agent_count": 0, "total_credits": 0, "total_ships": 0})
    faction_detail_text.config(state=tk.NORMAL)
    faction_detail_text.delete("1.0", tk.END)
    recruiting = "Yes" if f.get("isRecruiting") else "No"
    faction_detail_text.insert(tk.END, f"{f['name']}\n", "heading")
    hq = f.get("headquarters", "\u2014")
    faction_detail_text.insert(tk.END, f"Symbol: {f['symbol']}\n")
    faction_detail_text.insert(tk.END, f"Headquarters: {hq}\n")
    faction_detail_text.insert(tk.END, f"Recruiting: {recruiting}\n\n")
    desc = f.get("description", "No description available.")
    faction_detail_text.insert(tk.END, f"{desc}\n")
    # Reputation / activity scores
    faction_detail_text.insert(tk.END, "\nReputation Scores\n", "subheading")
    agent_count   = st["agent_count"]
    total_credits = st["total_credits"]
    total_ships   = st["total_ships"]
    avg_credits   = (total_credits // agent_count) if agent_count else 0
    faction_detail_text.insert(tk.END, f"  Agents  in faction : {agent_count:n}\n")
    faction_detail_text.insert(tk.END, f"  Total   credits    : {total_credits:n}\n")
    faction_detail_text.insert(tk.END, f"  Avg     credits    : {avg_credits:n}\n")
    faction_detail_text.insert(tk.END, f"  Total   ships      : {total_ships:n}\n")
    traits = f.get("traits", [])
    if traits:
        faction_detail_text.insert(tk.END, "\nTraits\n", "subheading")
        for t in traits:
            faction_detail_text.insert(tk.END, f"  \u2022 {t['name']}")
            detail = t.get("description", "")
            if detail:
                faction_detail_text.insert(tk.END, f": {detail}")
            faction_detail_text.insert(tk.END, "\n")
    faction_detail_text.config(state=tk.DISABLED)


# =============================================================================
# Combobox population helpers
# =============================================================================

def generate_faction_combobox():
    """Fill the faction dropdown with human-readable faction names (sorted A–Z)."""
    faction_combobox["values"] = sorted(get_faction_lookups().values())
 
 
def generate_login_combobox():
    """Fill the login dropdown with known agent names loaded from agents.json."""
    known_agents = load_player_logins()
    agent_list   = sorted(known_agents.keys(), key=str.casefold)
    id_login["values"] = agent_list
 
 
def show_agent_summary(json_result):
    """
    Called after a successful login or registration to activate the main tabs
    and store the logged-in agent’s details in the Tk variables.

    *json_result* is the agent dict returned by the API, with a "token" key
    merged in by the calling function.
    """
    global FACTION_LOOKUPS
    # Re-enable tabs that require authentication
    tabs.tab(0, state=tk.DISABLED)  # Welcome (hidden while logged in)
    tabs.tab(1, state=tk.NORMAL)    # Summary
    tabs.tab(2, state=tk.NORMAL)    # Leaderboard
    tabs.tab(4, state=tk.NORMAL)    # Shipyard
    tabs.tab(5, state=tk.NORMAL)    # Navigation
 
    player_token.set(json_result["token"])
    player_login.set(json_result["symbol"])
    player_faction.set(
        get_faction_lookups().get(json_result["startingFaction"], json_result["startingFaction"])
    )
    player_worth.set(f"{json_result['credits']:n}")
 
    tabs.select(1)
 
 
# =============================================================================
# Registration + Login + Logout
# =============================================================================

def register_agent():
    """
    Register a brand-new agent with SpaceTraders.

    Reads the agent name and faction from the Welcome tab form fields.
    Requires an account-level token (different from an agent token).
    On success, saves the new agent’s token and switches to the Summary tab.
    """
    try:
        username = agent_name.get().strip()
        if not username:
            print("Please enter an agent name before registering.")
            return

        acct_token = get_account_token()
        if not acct_token:
            print(
                "Registration requires an account token. "
                "Paste it into the Account Token field or set ACCOUNT_TOKEN in .env."
            )
            return

        print("Registering agent:", username)
        # The combobox shows faction *names* but the API needs faction *symbols*.
        # We reverse-look up: find the symbol whose value matches the chosen name.
        faction = next(
            (
                symbol
                for symbol, name in get_faction_lookups().items()
                if name == agent_faction.get()
            ),
            None,
        )
        if faction is None:
            print("Please pick a faction from the dropdown first.")
            return

        response = requests.post(
            CLAIM_USER,
            json={"faction": faction, "symbol": username},
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {acct_token}",
            },
        )
        if response.status_code < 400:
            result = response.json()
            # used to hold the token for later
            result["data"]["agent"]["token"] = result["data"]["token"]
            store_agent_login(result["data"]["agent"])
            show_agent_summary(result["data"]["agent"])
            agent_name.set("")
        else:
            print("Failed:", response.status_code, response.reason, response.text)

    except ConnectionError as ce:
        print("Failed:", ce)
 
 
def login_agent():
    """
    Log in as an existing agent.

    The player can either:
      - Select a saved agent name from the dropdown (token looked up from agents.json)
      - Paste a raw token string directly into the dropdown field

    On success, fetches the agent’s profile and switches to the Summary tab.
    """
    selected_agent_or_token = player_login.get().strip()
    token_to_use = selected_agent_or_token
    env_token = get_env_token()
 
    # -1 -> user entered a new token, so there won't be a name selected
    if id_login.current() != -1:
        known_agents = load_player_logins()
        token_to_use = known_agents.get(selected_agent_or_token, "").strip()

    if not token_to_use:
        token_to_use = env_token

    if not token_to_use:
        print(
            "Missing token. Select a saved agent, paste a valid SpaceTraders token, "
            "or set TOKEN in .env."
        )
        return

    if token_to_use == env_token and id_login.current() == -1 and not selected_agent_or_token:
        print("Using SpaceTraders token from .env")

    player_token.set(token_to_use)

    headers = request_headers(require_token=True, token=token_to_use)
    if headers is None:
        return
 
    try:
        response = requests.get(
            MY_ACCOUNT,
            headers=headers,
        )
        if response.status_code == 200:
            result = response.json()
            # used to hold the token for later
            result["data"]["token"] = player_token.get()
            show_agent_summary(result["data"])
            # print(result)
 
            # -1, so now store the agent name / token for future runs
            if id_login.current() == -1:
               store_agent_login(result["data"])
 
        else:
            print("Failed:", response.status_code, response.reason, response.text)
 
    except ConnectionError as ce:
        print("Failed:", ce)
 
 
def logout_agent():
    """
    Log out the current agent.

    Clears the stored token, disables auth-required tabs, and returns
    the user to the Welcome tab.
    """
    tabs.tab(0, state=tk.NORMAL)
    tabs.tab(1, state=tk.DISABLED)
    tabs.tab(2, state=tk.DISABLED)
    tabs.tab(4, state=tk.DISABLED)
    tabs.tab(5, state=tk.DISABLED)
 
    player_login.set("")
    player_token.set("")
 
    tabs.select(0)
 
 
# =============================================================================
# Tab switching handlers
# =============================================================================

def refresh_tabs(event):
    """
    Called every time the player clicks a different tab.

    Each tab needs slightly different data, so we fetch/refresh only what
    the newly selected tab requires rather than loading everything upfront.
    """
    selected_index = tabs.index(tabs.select())
    if selected_index == 1:
        refresh_player_summary()
 
    elif selected_index == 2:
        refresh_leaderboard()

    elif selected_index == 3:
        refresh_factions()

    elif selected_index == 4:
        _shipyard_reload()

    elif selected_index == 5:
        _navigation_reload()


def refresh_player_summary(*args):
    """
    Refresh all data on the Summary tab: agent credits, contracts, and ships.

    Also called from the upgrade dialog’s context so the credits display
    updates after buying mounts.
    """
    headers = request_headers(require_token=True)
    if headers is None:
        return

    try:
        response = requests.get(
            MY_ACCOUNT,
            headers=headers,
        )
        if response.status_code == 200:
            result = response.json()
 
            player_worth.set(f"{result['data']['credits']:n}")
 
        response = requests.get(
            MY_CONTRACTS,
            headers=headers,
        )
        if response.status_code == 200:
            result = response.json()
            contract_view.delete(*contract_view.get_children())
            for row in result["data"]:
                if len(row["terms"]["deliver"]) > 0:
                    remaining = (
                       row["terms"]["deliver"][0]["unitsRequired"]
                        - row["terms"]["deliver"][0]["unitsFulfilled"]
                    )
                    contract_view.insert(
                        "",
                        "end",
                       iid=row["id"],
                       text="contract_values",
                        open=True,
                        values=(
                           get_faction_lookups()[row["factionSymbol"]],
                           row["type"],
                           format_datetime(row["terms"]["deadline"]),
                           row["terms"]["deliver"][0]["tradeSymbol"],
                           row["terms"]["deliver"][0]["destinationSymbol"],
                           f"{remaining:n}",
                        ),
                    )
                for subrow, item in enumerate(row["terms"]["deliver"][1:]):
                    contract_view.insert(
                        row["id"],
                        "end",
                       iid=f'{row["id"]}#{subrow}',
                       text="extra_items",
                        values=(
                            "",
                            "",
                            "",
                           item["tradeSymbol"],
                           item["destinationSymbol"],
                           f"{(item['unitsRequired']-item['unitsFulfilled']):n}",
                        ),
                    )
 
        else:
            print("Failed:", response.status_code, response.reason, response.text)
 
        response = requests.get(
            MY_SHIPS,
            headers=headers,
        )
        if response.status_code == 200:
            result = response.json()
            ship_view.delete(*ship_view.get_children())
            for row in result["data"]:
                # zip_longest pairs up modules and mounts side-by-side.
                # A ship may have more modules than mounts or vice versa;
                # zip_longest fills the shorter list with defaultdict(str) so
                # missing entries produce an empty string instead of an error.
                modules_and_mounts = list(
                    zip_longest(
                       row["modules"], row["mounts"], fillvalue=defaultdict(str)
                    )
                )
                if len(modules_and_mounts) > 0:
                    module, mount = modules_and_mounts[0]

                # iid=row["symbol"] makes the ship symbol both the row identifier
                # and lets us look up the row directly by symbol later.
                ship_view.insert(
                    "",
                    "end",
                   iid=row["symbol"],
                   text="ship_values",
                    open=True,
                    values=(
                       row["symbol"],
                       row["registration"]["role"],
                       row["frame"]["name"],
                       row["reactor"]["name"],
                       row["engine"]["name"],
                       module["name"],
                       mount["name"],
                       f'{row["fuel"]["current"]} / {row["fuel"]["capacity"]}',
                       f'{row["cargo"]["units"]} / {row["cargo"]["capacity"]}',
                    ),
                )
                # Extra module/mount pairs go on child rows under the ship row
                for subrow, (module, mount) in enumerate(modules_and_mounts[1:]):
                    ship_view.insert(
                       row["symbol"],
                        "end",
                       iid=f'{row["symbol"]}#{subrow}',  # '#' marks these as sub-rows
                       text="modules_and_mounts",
                        values=(
                            "", "", "", "", "",
                           module["name"],
                           mount["name"],
                            "", "",
                        ),
                    )
 
        else:
            print("Failed:", response.status_code, response.reason, response.text)
 
    except ConnectionError as ce:
        print("Failed:", ce)
 
 
# =============================================================================
# Summary tab click handlers
# =============================================================================

def display_clicked_contract(*args):
    """Placeholder handler for double-clicking a contract row (not yet implemented)."""
    print(contract_view.index(contract_view.focus()), contract_view.focus())


def display_clicked_ship(*args):
    """
    Called when the player double-clicks a row in the ships treeview.

    Opens the upgrade dialog for the selected ship.  Sub-rows (showing
    extra modules/mounts that didn’t fit on row 0) have a '#' in their iid
    and are ignored — the dialog should only open for top-level ship rows.
    """
    iid = ship_view.focus()
    if not iid:
        return
    # Only open the dialog for top-level ship rows (not sub-rows like modules_and_mounts)
    if "#" in iid:
        return
    open_upgrade_dialog(iid, upgrade_ctx)


# =============================================================================
# Leaderboard
# =============================================================================

def refresh_leaderboard(*args):
    """
    Fetch the server status endpoint, which includes two leaderboards:
      - Most credits (top agents by total credits)
      - Most submitted charts (top agents by chart count)
    Both are public — no token required.
    """
    try:
        response = requests.get(
            API_STATUS,
            params={"token": player_token.get()},
        )
        if response.status_code == 200:
            result = response.json()
            credits_leaderboard_view.delete(*credits_leaderboard_view.get_children())
            for rank, row in enumerate(result["leaderboards"]["mostCredits"]):
               credits_leaderboard_view.insert(
                    "",
                    "end",
                    text="values",
                    values=(rank + 1, row["agentSymbol"], f"{row['credits']:n}"),
                )

            charts_leaderboard_view.delete(*charts_leaderboard_view.get_children())
            for rank, row in enumerate(result["leaderboards"]["mostSubmittedCharts"]):
                charts_leaderboard_view.insert(
                    "",
                    "end",
                    text="values",
                    values=(rank + 1, row["agentSymbol"], f"{row['chartCount']:n}"),
                )

        else:
            print("Failed:", response.status_code, response.reason, response.text)

    except ConnectionError as ce:
        print("Failed:", ce)
 
 
# =============================================================================
# UI Construction
# =============================================================================
# Everything below builds the actual window and widgets.
# tkinter.Tk() is the root window; all other widgets live inside it.
# ttk.Notebook creates the tabbed layout; each tab is a plain ttk.Frame.
# "weight=1" on columnconfigure/rowconfigure lets that row/column stretch
# when the window is resized.

# ── Root window ──────────────────────────────────────────────────────────────

root = tk.Tk()
root.title("Io Space Trading")

# A single frame that fills the whole window
main = ttk.Frame(root, padding="3 3 12 12")
main.grid(sticky=tk.NSEW)

# Allow the frame (and everything in it) to resize with the window
root.columnconfigure(0, weight=1)
root.rowconfigure(0, weight=1)

# ── Tab notebook ─────────────────────────────────────────────────────────────
# ttk.Notebook displays one "page" (Frame) at a time.
# We bind <<NotebookTabChanged>> to refresh_tabs so each tab loads fresh data
# when the player switches to it.
tabs = ttk.Notebook(main)
tabs.grid(sticky=tk.NSEW)
tabs.bind("<<NotebookTabChanged>>", refresh_tabs)

main.columnconfigure(0, weight=1)
main.rowconfigure(0, weight=1)

# Create a frame for each tab (contents are added further below)
welcome        = ttk.Frame(tabs)
summary        = ttk.Frame(tabs)
leaderboard    = ttk.Frame(tabs)
factions_tab   = ttk.Frame(tabs)
shipyard_tab   = ttk.Frame(tabs)
navigation_tab = ttk.Frame(tabs)

tabs.add(welcome,        text="Welcome")
tabs.add(summary,        text="Summary")
tabs.add(leaderboard,    text="Leaderboard")
tabs.add(factions_tab,   text="Factions")
tabs.add(shipyard_tab,   text="Shipyard")
tabs.add(navigation_tab, text="Navigation")

# Tabs 1, 2, 4, 5 require a logged-in agent — start disabled.
# Tab 3 (Factions) uses only public API data, so it stays always enabled.
tabs.tab(1, state=tk.DISABLED)
tabs.tab(2, state=tk.DISABLED)
tabs.tab(4, state=tk.DISABLED)
tabs.tab(5, state=tk.DISABLED)
 
# ── Welcome tab — Register / Login ───────────────────────────────────────────
# Two side-by-side panels: Register (left) and Login (right).

welcome_frame = ttk.Frame(welcome)
welcome_frame.grid(row=0, column=0, columnspan=2, sticky=tk.NSEW)

# Left side: register a brand-new agent
register = ttk.LabelFrame(welcome_frame, text="Register", relief="groove", padding=5)
register.grid(sticky=tk.NSEW)
 
# Tk StringVars are special variables that tkinter widgets can watch.
# Changing a StringVar automatically updates any widget that displays it.
agent_name    = tk.StringVar()
agent_faction = tk.StringVar()
ttk.Label(
    register, text="Enter a new agent name\nto start a new account", anchor=tk.CENTER
).grid(sticky=tk.EW)
faction_combobox = ttk.Combobox(
    register, textvariable=agent_faction, postcommand=generate_faction_combobox
)
faction_combobox.grid(row=1, column=0, sticky=tk.EW)
ttk.Entry(register, textvariable=agent_name).grid(row=2, column=0, sticky=tk.EW)

# Account token is required by the SpaceTraders /register endpoint.
# Pre-populate from ACCOUNT_TOKEN (or TOKEN) env if already set.
account_token_var = tk.StringVar(value=get_account_token())
ttk.Label(register, text="Account token", anchor=tk.W).grid(row=3, column=0, sticky=tk.EW)
ttk.Entry(register, textvariable=account_token_var, show="*").grid(row=4, column=0, sticky=tk.EW)

ttk.Button(register, text="Register new agent", command=register_agent).grid(
    row=5, column=0, columnspan=2, sticky=tk.EW
)
 
register.columnconfigure(0, weight=1)
register.rowconfigure(0, weight=1)
 
ttk.Label(welcome_frame, text="or", padding=10, anchor=tk.CENTER).grid(
    row=0, column=1, sticky=tk.EW
)
 
# Right side: log in with an existing agent
login = ttk.LabelFrame(welcome_frame, text="Login", relief=tk.GROOVE, padding=5)
login.grid(row=0, column=2, sticky=tk.NSEW)

# player_token is the core auth state for the whole app.
# When set (after login), request_headers() uses it for Bearer auth.
player_login = tk.StringVar()  # Agent name shown in the UI
player_token = tk.StringVar()  # Auth token sent with authenticated API requests
ttk.Label(login, text="Choose the agent to play as\nor paste an existing id").grid(
    sticky=tk.EW
)
id_login = ttk.Combobox(
    login, textvariable=player_login, postcommand=generate_login_combobox
)
id_login.grid(row=1, column=0, sticky=tk.EW)
ttk.Button(login, text="Login agent", command=login_agent).grid(
    row=2, column=0, columnspan=2, sticky=tk.EW
)
 
login.columnconfigure(0, weight=1)
login.rowconfigure(0, weight=1)
 
welcome_frame.columnconfigure(0, weight=1)
welcome_frame.columnconfigure(2, weight=1)
welcome_frame.rowconfigure(0, weight=1)
 
welcome.columnconfigure(0, weight=1)
welcome.rowconfigure(0, weight=1)
 
# ── Summary tab — Agent info, Contracts, Ships ───────────────────────────────

player_summary = ttk.LabelFrame(summary, text="Agent", relief=tk.GROOVE, padding=5)
 
player_faction = tk.StringVar()
player_worth = tk.StringVar()
 
ttk.Label(player_summary, textvariable=player_login, anchor=tk.CENTER).grid(
    columnspan=2, sticky=tk.EW
)
ttk.Label(player_summary, text="Faction:").grid(row=1, column=0, sticky=tk.W)
ttk.Label(player_summary, textvariable=player_faction, anchor=tk.CENTER).grid(
    row=1, column=1, sticky=tk.EW
)
ttk.Label(player_summary, text="Credits:").grid(row=2, column=0, sticky=tk.W)
ttk.Label(player_summary, textvariable=player_worth, anchor=tk.CENTER).grid(
    row=2, column=1, sticky=tk.EW
)
ttk.Button(player_summary, text="Logout", command=logout_agent).grid(
    row=3, column=0, columnspan=2, sticky=tk.EW
)
 
player_summary.columnconfigure(0, weight=1)
 
contract_summary = ttk.LabelFrame(
    summary, text="Contracts", relief=tk.GROOVE, padding=5
)
 
contract_view = ttk.Treeview(
    contract_summary,
    height=3,
    columns=("Faction", "Type", "Deadline", "Goods", "Destination", "Owing"),
    show="headings",
)
contract_view.column("Faction", anchor=tk.W, width=20)
contract_view.column("Type", anchor=tk.W, width=20)
contract_view.column("Deadline", anchor=tk.W, width=20)
contract_view.column("Goods", anchor=tk.W, width=30)
contract_view.column("Destination", anchor=tk.W, width=20)
contract_view.column("Owing", anchor=tk.E, width=20)
contract_view.heading("#1", text="Faction")
contract_view.heading("#2", text="Type")
contract_view.heading("#3", text="Deadline")
contract_view.heading("#4", text="Goods")
contract_view.heading("#5", text="Destination")
contract_view.heading("#6", text="Owing")
contract_view.grid(sticky=tk.NSEW)
contract_scroll = ttk.Scrollbar(
    contract_summary, orient=tk.VERTICAL, command=contract_view.yview
)
contract_scroll.grid(column=1, row=0, sticky=tk.NS)
contract_view.config(yscrollcommand=contract_scroll.set)
contract_view.bind("<Double-1>", display_clicked_contract)
 
contract_summary.columnconfigure(0, weight=1)
contract_summary.rowconfigure(0, weight=1)
 
ship_summary = ttk.LabelFrame(summary, text="Ships  (double-click a ship to upgrade)", relief=tk.GROOVE, padding=5)
ship_view = ttk.Treeview(
    ship_summary,
    height=3,
    columns=(
        "Registration",
        "Role",
        "Frame",
        "Reactor",
        "Engine",
        "Modules",
        "Mounts",
        "Fuel",
        "Cargo",
    ),
    show="headings",
)
ship_view.column("Registration", anchor=tk.W, width=30)
ship_view.column("Role", anchor=tk.W, width=30)
ship_view.column("Frame", anchor=tk.W, width=30)
ship_view.column("Reactor", anchor=tk.W, width=30)
ship_view.column("Engine", anchor=tk.W, width=30)
ship_view.column("Modules", anchor=tk.W, width=30)
ship_view.column("Mounts", anchor=tk.W, width=30)
ship_view.column("Fuel", anchor=tk.E, width=20)
ship_view.column("Cargo", anchor=tk.E, width=20)
ship_view.heading("#1", text="Registration")
ship_view.heading("#2", text="Role")
ship_view.heading("#3", text="Frame")
ship_view.heading("#4", text="Reactor")
ship_view.heading("#5", text="Engine")
ship_view.heading("#6", text="Modules")
ship_view.heading("#7", text="Mounts")
ship_view.heading("#8", text="Fuel")
ship_view.heading("#9", text="Cargo")
ship_view.grid(sticky=tk.NSEW)
ship_scroll = ttk.Scrollbar(ship_summary, orient=tk.VERTICAL, command=ship_view.yview)
ship_scroll.grid(column=1, row=0, sticky=tk.NS)
ship_view.config(yscrollcommand=ship_scroll.set)
ship_view.bind("<Double-1>", display_clicked_ship)
 
ship_summary.columnconfigure(0, weight=1)
ship_summary.rowconfigure(0, weight=1)
 
 
player_summary.grid(row=0, column=0, sticky=tk.NSEW)
contract_summary.grid(row=0, column=1, sticky=tk.NSEW)
ship_summary.grid(row=1, column=0, columnspan=2, sticky=tk.NSEW)
 
summary.columnconfigure(0, weight=1)
summary.columnconfigure(1, weight=3)
summary.rowconfigure(0, weight=2)
summary.rowconfigure(1, weight=3)
 
# ── Leaderboard tab ───────────────────────────────────────────────────────────

credits_leaderboard_view = ttk.Treeview(
    leaderboard, height=6, columns=("Rank", "Agent", "Credits"), show="headings"
)
credits_leaderboard_view.column("Rank", anchor=tk.CENTER, width=10)
credits_leaderboard_view.column("Agent", anchor=tk.W, width=100)
credits_leaderboard_view.column("Credits", anchor=tk.E, width=100)
credits_leaderboard_view.heading("#1", text="Rank")
credits_leaderboard_view.heading("#2", text="Agent")
credits_leaderboard_view.heading("#3", text="Credits")
credits_leaderboard_view.grid(sticky=tk.NSEW)
credits_scroll = ttk.Scrollbar(
    leaderboard, orient=tk.VERTICAL, command=credits_leaderboard_view.yview
)
credits_scroll.grid(column=1, row=0, sticky=tk.NS)
credits_leaderboard_view.config(yscrollcommand=credits_scroll.set)
 
charts_leaderboard_view = ttk.Treeview(
    leaderboard, height=6, columns=("Rank", "Agent", "Chart Count"), show="headings"
)
charts_leaderboard_view.column("Rank", anchor=tk.CENTER, width=10)
charts_leaderboard_view.column("Agent", anchor=tk.W, width=100)
charts_leaderboard_view.column("Chart Count", anchor=tk.E, width=100)
charts_leaderboard_view.heading("#1", text="Rank")
charts_leaderboard_view.heading("#2", text="Agent")
charts_leaderboard_view.heading("#3", text="Chart Count")
charts_leaderboard_view.grid(sticky=tk.NSEW)
charts_scroll = ttk.Scrollbar(
    leaderboard, orient=tk.VERTICAL, command=charts_leaderboard_view.yview
)
charts_scroll.grid(column=1, row=1, sticky=tk.NS)
charts_leaderboard_view.config(yscrollcommand=charts_scroll.set)
 
refresh = ttk.Button(leaderboard, text="Refresh", command=refresh_leaderboard)
refresh.grid(column=0, row=2, sticky=tk.EW)
 
leaderboard.columnconfigure(0, weight=1)
leaderboard.rowconfigure((0, 1), weight=1)

# ── Factions tab ─────────────────────────────────────────────────────────────
# Left panel: sortable treeview of all factions.
# Right panel: detail text for the selected faction.

# Left panel — treeview of all factions
factions_tree_frame = ttk.LabelFrame(factions_tab, text="All Factions", padding=5)
factions_tree_frame.grid(row=0, column=0, sticky=tk.NSEW, padx=(6, 3), pady=6)

faction_view = ttk.Treeview(
    factions_tree_frame,
    height=18,
    columns=("Name", "Headquarters", "Recruiting", "Agents", "Avg Credits", "Ships"),
    show="headings",
    selectmode="browse",
)
faction_view.column("Name",         anchor=tk.W,      width=120)
faction_view.column("Headquarters", anchor=tk.W,      width=100)
faction_view.column("Recruiting",   anchor=tk.CENTER, width=80)
faction_view.column("Agents",       anchor=tk.E,      width=60)
faction_view.column("Avg Credits",  anchor=tk.E,      width=95)
faction_view.column("Ships",        anchor=tk.E,      width=55)
faction_view.heading("#1", text="Name")
faction_view.heading("#2", text="Headquarters")
faction_view.heading("#3", text="Recruiting")
faction_view.heading("#4", text="Agents \u25bc")
faction_view.heading("#5", text="Avg Credits")
faction_view.heading("#6", text="Ships")
faction_view.grid(row=0, column=0, sticky=tk.NSEW)
fact_scroll = ttk.Scrollbar(factions_tree_frame, orient=tk.VERTICAL, command=faction_view.yview)
fact_scroll.grid(row=0, column=1, sticky=tk.NS)
faction_view.config(yscrollcommand=fact_scroll.set)
faction_view.bind("<<TreeviewSelect>>", on_faction_select)

factions_tree_frame.columnconfigure(0, weight=1)
factions_tree_frame.rowconfigure(0, weight=1)

# Right panel — faction detail
factions_detail_frame = ttk.LabelFrame(factions_tab, text="Faction Details", padding=5)
factions_detail_frame.grid(row=0, column=1, sticky=tk.NSEW, padx=(3, 6), pady=6)

faction_detail_text = tk.Text(
    factions_detail_frame,
    wrap=tk.WORD,
    width=38,
    height=18,
    state=tk.DISABLED,
    relief=tk.FLAT,
    cursor="arrow",
)
faction_detail_text.tag_configure("heading",    font=("TkDefaultFont", 11, "bold"))
faction_detail_text.tag_configure("subheading", font=("TkDefaultFont", 10, "bold"))
faction_detail_text.grid(row=0, column=0, sticky=tk.NSEW)
detail_scroll = ttk.Scrollbar(factions_detail_frame, orient=tk.VERTICAL, command=faction_detail_text.yview)
detail_scroll.grid(row=0, column=1, sticky=tk.NS)
faction_detail_text.config(yscrollcommand=detail_scroll.set)

factions_detail_frame.columnconfigure(0, weight=1)
factions_detail_frame.rowconfigure(0, weight=1)

# Bottom bar — status + refresh button
factions_status_var = tk.StringVar(value="Click \u2018Refresh\u2019 to load factions.")
ttk.Label(factions_tab, textvariable=factions_status_var, anchor=tk.W).grid(
    row=1, column=0, sticky=tk.EW, padx=6, pady=(0, 4)
)
ttk.Button(factions_tab, text="Refresh", command=refresh_factions).grid(
    row=1, column=1, sticky=tk.EW, padx=6, pady=(0, 4)
)

factions_tab.columnconfigure(0, weight=1)
factions_tab.columnconfigure(1, weight=1)
factions_tab.rowconfigure(0, weight=1)

# =============================================================================
# Context objects — wire together URLs + helpers and pass to each tab module
# =============================================================================
# Each context dataclass bundles everything the sub-module needs from main.py.
# This avoids circular imports: the sub-modules don't import main.py;
# instead main.py imports them and injects the context.

upgrade_ctx = UpgradeContext(
    root=root,
    request_headers=request_headers,
    player_worth_var=player_worth,
    refresh_summary=refresh_player_summary,
    my_ships_url=MY_SHIPS,
    ship_mounts_url=SHIP_MOUNTS,
    ship_cargo_url=SHIP_CARGO,
    install_mount_url=SHIP_INSTALL_MOUNT,
    remove_mount_url=SHIP_REMOVE_MOUNT,
    ship_orbit_url=SHIP_ORBIT,
    ship_dock_url=SHIP_DOCK,
    ship_transfer_url=SHIP_TRANSFER,
    shipyard_url=SHIPYARD,
)

# build_shipyard_tab / build_navigation_tab construct all the tab widgets and
# return a reload() callable.  We store the callable so refresh_tabs() can
# call it when the player switches to that tab.
_shipyard_reload = build_shipyard_tab(
    shipyard_tab,
    ShipyardContext(
        root=root,
        request_headers=request_headers,
        my_ships_url=MY_SHIPS,
        system_waypoints_url=SYSTEM_WAYPOINTS,
        shipyard_url=SHIPYARD,
        ship_cargo_url=SHIP_CARGO,
        ship_mounts_url=SHIP_MOUNTS,
        ship_install_mount_url=SHIP_INSTALL_MOUNT,
        ship_dock_url=SHIP_DOCK,
    ),
)

_navigation_reload = build_navigation_tab(
    navigation_tab,
    NavigationContext(
        root=root,
        request_headers=request_headers,
        my_ships_url=MY_SHIPS,
        ship_orbit_url=SHIP_ORBIT,
        ship_navigate_url=SHIP_NAVIGATE,
        ship_dock_url=SHIP_DOCK,
        ship_refuel_url=SHIP_REFUEL,
        system_waypoints_url=SYSTEM_WAYPOINTS,
    ),
)

# =============================================================================
# Start the app
# =============================================================================
# root.mainloop() hands control to tkinter's event loop.
# It waits for user events (clicks, key presses, etc.), calls the appropriate
# handlers, and keeps the window alive until the user closes it.
root.mainloop()