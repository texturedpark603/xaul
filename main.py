from __future__ import annotations
import sys
import os
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from auth import XboxAuth, _AUTH_FILE
from api import XboxAPI, is_event_based, is_360_title
from achievements import AchievementManager, update_events_data, print_achievements, print_achievements_360
from spoof import Spoofer
from server import XaulServer, DEFAULT_PORT


def clear():
    os.system("cls" if os.name == "nt" else "clear")


def header(title=""):
    print("\n" + "═" * 60)
    if title:
        pad = (60 - len(title) - 2) // 2
        print(" " * pad + f" {title} ")
        print("═" * 60)


def prompt(text, default=""):
    suffix = f" [{default}]" if default else ""
    try:
        val = input(f"  {text}{suffix}: ").strip()
    except (KeyboardInterrupt, EOFError):
        print()
        return default
    return val if val else default


def choose(options):
    for key, label in options:
        print(f"  {key:>2}.  {label}")
    print()
    while True:
        choice = prompt("Choice").upper()
        keys = [k.upper() for k, _ in options]
        if choice in keys:
            return choice
        print("  Invalid choice, try again.")


def pause():
    try:
        input("\n  Press Enter to continue...")
    except (KeyboardInterrupt, EOFError):
        pass


def yn(text):
    ans = prompt(f"{text} [y/N]").lower()
    return ans in ("y", "yes")


class Session:
    def __init__(self):
        self.xauth = ""
        self.xuid = ""
        self.gamertag = ""
        self.api: XboxAPI | None = None
        self.ach: AchievementManager | None = None
        self.spoofer: Spoofer | None = None
        self.server: XaulServer | None = None
        self.server_port = DEFAULT_PORT
        self.fake_signature = True
        self.region_override = False

    @property
    def logged_in(self):
        return bool(self.xauth and self.xuid)


_session = Session()


def do_login():
    header("LOGIN")
    print("  Logging in via Microsoft OAuth2.")
    print("  Your browser will open for authentication.")
    print("  If it doesn't open, follow the printed URL manually.\n")

    auth = XboxAuth()
    try:
        xauth, xuid, gamertag = auth.ensure_authenticated()
    except Exception as exc:
        print(f"\n  [!] Login failed: {exc}")
        pause()
        return

    _session.xauth = xauth
    _session.xuid = xuid
    _session.gamertag = gamertag
    _session.api = XboxAPI(xauth, _session.region_override, _session.fake_signature)
    _session.ach = AchievementManager(_session.api, xuid, _session.fake_signature)
    _session.spoofer = Spoofer(_session.api, xuid)
    _session.server = XaulServer(
        _session.api, _session.ach, xuid, xauth, _session.server_port
    )

    print(f"\n  Logged in as: {gamertag}  (XUID: {xuid})")
    pause()


def menu_profile():
    while True:
        header("PROFILE")
        choice = choose([
            ("1", "Show my profile"),
            ("2", "Look up profile by XUID"),
            ("3", "Look up profile by gamertag"),
            ("B", "Back"),
        ])

        if choice == "B":
            return

        elif choice == "1":
            try:
                data = _session.api.get_profile_by_xuid(_session.xuid)
                print_profile(data)
            except Exception as exc:
                print(f"\n  [!] {exc}")

        elif choice == "2":
            xuid = prompt("XUID")
            if xuid:
                try:
                    data = _session.api.get_profile_by_xuid(xuid)
                    print_profile(data)
                except Exception as exc:
                    print(f"\n  [!] {exc}")

        elif choice == "3":
            gt = prompt("Gamertag")
            if gt:
                try:
                    xuid = _session.api.get_xuid_for_gamertag(gt)
                    if not xuid:
                        print(f"\n  [!] Gamertag '{gt}' not found.")
                    else:
                        data = _session.api.get_profile_by_xuid(xuid)
                        print_profile(data)
                except Exception as exc:
                    print(f"\n  [!] {exc}")

        pause()


def print_profile(data):
    try:
        people = data.get("people", [])
        if not people:
            print("\n  No profile data returned.")
            return
        p = people[0]
        print(f"\n  Gamertag      : {p.get('gamertag', '?')}")
        print(f"  XUID          : {p.get('xuid', '?')}")
        print(f"  Gamerscore    : {p.get('gamerScore', '?')}")
        print(f"  Reputation    : {p.get('xboxOneRep', '?')}")
        presence = p.get("presenceDetails", [{}])
        if presence:
            state = presence[0].get("state", "?")
            title = presence[0].get("titleName", "")
            print(f"  Presence      : {state}" + (f" — {title}" if title else ""))
        detail = p.get("detail", {})
        if detail:
            print(f"  Bio           : {detail.get('bio', '')}")
            print(f"  Location      : {detail.get('location', '')}")
            print(f"  Followers     : {detail.get('followerCount', '?')}")
            print(f"  Following     : {detail.get('followingCount', '?')}")
    except Exception as exc:
        print(f"\n  (Could not parse profile: {exc})")
        import json
        print(json.dumps(data, indent=2)[:1000])


def menu_games():
    while True:
        header("GAMES")
        choice = choose([
            ("1", "List my games"),
            ("2", "Look up title by Title ID"),
            ("3", "Search titles by name (dbox.tools)"),
            ("B", "Back"),
        ])

        if choice == "B":
            return

        elif choice == "1":
            try:
                print("\n  Fetching games list (may take a moment)...")
                data = _session.api.get_games_list(_session.xuid)
                titles = data.get("titles", [])
                if not titles:
                    print("  No games found.")
                else:
                    print(f"\n  {len(titles)} game(s) found:\n")
                    for t in titles:
                        devices = ", ".join(t.get("devices", []))
                        ach = t.get("achievement", {})
                        prog = ach.get("progressPercentage", "?")
                        current_g = ach.get("currentGamerscore", "?")
                        total_g = ach.get("totalGamerscore", "?")
                        print(
                            f"  {t.get('titleId','?'):>12}  {t.get('name','?'):<40}"
                            f"  {prog}%  {current_g}/{total_g}G  [{devices}]"
                        )
            except Exception as exc:
                print(f"\n  [!] {exc}")

        elif choice == "2":
            tid = prompt("Title ID")
            if tid:
                try:
                    data = _session.api.get_title_info(_session.xuid, tid)
                    print_title_info(data)
                except Exception as exc:
                    print(f"\n  [!] {exc}")

        elif choice == "3":
            query = prompt("Game name")
            if query:
                try:
                    results = _session.api.search_titles(query)
                    if not results:
                        print("  No results.")
                    else:
                        print(f"\n  {len(results)} result(s):\n")
                        for r in results[:30]:
                            print(f"  TitleID: {r.get('title_id','?'):>12}  {r.get('name','?')}")
                except Exception as exc:
                    print(f"\n  [!] {exc}")

        pause()


def print_title_info(data):
    titles = data.get("Titles", [])
    if not titles:
        print("\n  No title info returned.")
        return
    t = titles[0]
    print(f"\n  Name          : {t.get('name', '?')}")
    print(f"  Title ID      : {t.get('titleId', '?')}")
    print(f"  SCID          : {t.get('serviceConfigId', '?')}")
    print(f"  Devices       : {', '.join(t.get('devices', []))}")
    ach = t.get("achievement", {})
    if ach:
        print(f"  Achievements  : {ach.get('currentAchievements','?')}/{ach.get('totalAchievements','?')}")
        print(f"  Gamerscore    : {ach.get('currentGamerscore','?')}/{ach.get('totalGamerscore','?')}")
        print(f"  Progress      : {ach.get('progressPercentage','?')}%")
    gp = t.get("gamePass", {})
    if gp:
        print(f"  Game Pass     : {'Yes' if gp.get('isGamePass') else 'No'}")


def menu_achievements():
    while True:
        header("ACHIEVEMENTS")
        choice = choose([
            ("1", "List achievements for a title"),
            ("2", "Unlock one achievement (title-based)"),
            ("3", "Unlock ALL achievements (title-based)"),
            ("4", "Unlock one achievement (event-based)"),
            ("5", "Unlock ALL achievements (event-based)"),
            ("6", "Events submenu"),
            ("B", "Back"),
        ])

        if choice == "B":
            return

        elif choice == "1":
            tid = prompt("Title ID")
            if not tid:
                continue
            print("\n  Fetching achievements...")
            try:
                data, is_360, event_based = _session.ach.fetch_achievements(tid)
                if not data:
                    print("  No achievements returned.")
                elif is_360:
                    print("  (Xbox 360 title — display only, cannot unlock here)")
                    print_achievements_360(data)
                else:
                    kind = "event-based" if event_based else "title-based"
                    print(f"  Achievement type: {kind}")
                    print_achievements(data)
            except Exception as exc:
                print(f"\n  [!] {exc}")
            pause()

        elif choice == "2":
            tid = prompt("Title ID")
            aid = prompt("Achievement ID")
            if tid and aid:
                try:
                    _session.ach.unlock_one(tid, aid)
                except Exception as exc:
                    print(f"\n  [!] {exc}")
                pause()

        elif choice == "3":
            tid = prompt("Title ID")
            if not tid:
                continue
            if not yn(f"  Unlock ALL achievements for title {tid}?"):
                continue
            try:
                count = _session.ach.unlock_all(tid)
                print(f"\n  Unlocked {count} achievement(s).")
            except Exception as exc:
                print(f"\n  [!] {exc}")
            pause()

        elif choice == "4":
            tid = prompt("Title ID")
            aid = prompt("Achievement ID")
            if tid and aid:
                try:
                    _session.ach.unlock_event_achievement(tid, aid)
                except Exception as exc:
                    print(f"\n  [!] {exc}")
                pause()

        elif choice == "5":
            tid = prompt("Title ID")
            if not tid:
                continue
            if not yn(f"  Unlock ALL event achievements for title {tid}?"):
                continue
            try:
                count = _session.ach.unlock_all_event_achievements(tid)
                print(f"\n  Sent {count} event unlock(s).")
            except Exception as exc:
                print(f"\n  [!] {exc}")
            pause()

        elif choice == "6":
            menu_events()


def menu_events():
    while True:
        header("EVENTS")
        token_status = "Set" if _session.ach.events_token else "Not set"
        print(f"  Events token  : {token_status}")
        print()
        choice = choose([
            ("1", "Set events token manually"),
            ("2", "Show current events token"),
            ("3", "Update events data from GitHub"),
            ("4", "List supported event titles"),
            ("B", "Back"),
        ])

        if choice == "B":
            return

        elif choice == "1":
            print("\n  Paste your events token (starts with x:XBL3.0 x=):")
            try:
                token = input("  > ").strip()
            except (KeyboardInterrupt, EOFError):
                print()
                continue
            if token:
                _session.ach.set_events_token(token)
            pause()

        elif choice == "2":
            t = _session.ach.events_token
            if t:
                print(f"\n  {t[:80]}...")
            else:
                print("\n  No events token set.")
            pause()

        elif choice == "3":
            force = yn("  Force re-download even if up to date?")
            update_events_data(_session.api, force=force)
            pause()

        elif choice == "4":
            _session.ach.list_supported_event_titles()
            pause()


def menu_spoof():
    while True:
        header("PRESENCE SPOOF")
        active = _session.spoofer.is_active
        status = f"ACTIVE — TitleID {_session.spoofer.current_title_id}" if active else "Inactive"
        print(f"  Status        : {status}")
        print()

        opts = []
        if active:
            opts.append(("1", "Stop spoofing"))
        else:
            opts.append(("1", "Start spoofing a title"))
        opts.append(("2", "Send one heartbeat (without loop)"))
        opts.append(("B", "Back"))

        choice = choose(opts)

        if choice == "B":
            return

        elif choice == "1":
            if active:
                _session.spoofer.stop()
            else:
                tid = prompt("Title ID to spoof")
                if tid:
                    _session.spoofer.start(tid)
            pause()

        elif choice == "2":
            tid = prompt("Title ID")
            if tid:
                try:
                    _session.api.send_heartbeat(_session.xuid, tid)
                    print(f"  Heartbeat sent for TitleID {tid}.")
                except Exception as exc:
                    print(f"\n  [!] {exc}")
            pause()


def menu_server():
    while True:
        header("HTTP SERVER")
        running = _session.server.is_running
        status = f"Running on http://127.0.0.1:{_session.server_port}/" if running else "Stopped"
        print(f"  Status        : {status}")
        print(f"  Port          : {_session.server_port}")
        print()

        opts = []
        if running:
            opts.append(("1", "Stop server"))
        else:
            opts.append(("1", "Start server"))
        opts.append(("2", f"Change port (current: {_session.server_port})"))
        opts.append(("B", "Back"))

        choice = choose(opts)

        if choice == "B":
            return

        elif choice == "1":
            if running:
                _session.server.stop()
            else:
                if _session.server is None:
                    _session.server = XaulServer(
                        _session.api, _session.ach,
                        _session.xuid, _session.xauth,
                        _session.server_port,
                    )
                _session.server.start()
            pause()

        elif choice == "2":
            new_port = prompt("New port", str(_session.server_port))
            try:
                port = int(new_port)
                if not (1024 <= port <= 65535):
                    raise ValueError("Port must be 1024–65535")
                _session.server_port = port
                if running:
                    _session.server.stop()
                _session.server = XaulServer(
                    _session.api, _session.ach,
                    _session.xuid, _session.xauth,
                    port,
                )
                print(f"  Port set to {port}.")
            except ValueError as exc:
                print(f"\n  [!] Invalid port: {exc}")
            pause()


def menu_settings():
    while True:
        header("SETTINGS")
        print(f"  Fake signature header  : {'ON' if _session.fake_signature else 'OFF'}")
        print(f"  Region override (en-GB): {'ON' if _session.region_override else 'OFF'}")
        print()
        choice = choose([
            ("1", "Toggle fake signature header"),
            ("2", "Toggle region override (force en-GB)"),
            ("3", "Show Xbox token (xauth)"),
            ("4", "Re-login / switch account"),
            ("B", "Back"),
        ])

        if choice == "B":
            return

        elif choice == "1":
            _session.fake_signature = not _session.fake_signature
            if _session.api:
                _session.api._fake_sig = _session.fake_signature
            if _session.ach:
                _session.ach._fake_sig = _session.fake_signature
            state = "ON" if _session.fake_signature else "OFF"
            print(f"  Fake signature header is now {state}.")
            pause()

        elif choice == "2":
            _session.region_override = not _session.region_override
            if _session.api:
                _session.api._lang = "en-GB" if _session.region_override else "en-US"
            state = "ON" if _session.region_override else "OFF"
            print(f"  Region override is now {state}.")
            pause()

        elif choice == "3":
            print(f"\n  Xbox token (xauth):\n  {_session.xauth}")
            pause()

        elif choice == "4":
            if _session.spoofer and _session.spoofer.is_active:
                _session.spoofer.stop()
            if _session.server and _session.server.is_running:
                _session.server.stop()
            _session.xauth = ""
            _session.xuid = ""
            _session.gamertag = ""
            _session.api = None
            _session.ach = None
            _session.spoofer = None
            _session.server = None
            do_login()


def do_logout():
    if not yn("  Log out and clear saved session?"):
        return
    if _session.spoofer and _session.spoofer.is_active:
        _session.spoofer.stop()
    if _session.server and _session.server.is_running:
        _session.server.stop()

    try:
        if _AUTH_FILE.exists():
            _AUTH_FILE.unlink()
    except Exception as exc:
        print(f"\n  [!] Could not delete auth file: {exc}")

    _session.xauth = ""
    _session.xuid = ""
    _session.gamertag = ""
    _session.api = None
    _session.ach = None
    _session.spoofer = None
    _session.server = None
    print("\n  Logged out.")
    pause()


def main_menu():
    while True:
        clear()
        header("xaul — Xbox Achievement Unlocker")
        if _session.logged_in:
            print(f"  Logged in as  : {_session.gamertag}  ({_session.xuid})")
            if _session.spoofer:
                print(f"  Spoof status  : {_session.spoofer.status}")
        else:
            print("  Not logged in.")
        print()

        if not _session.logged_in:
            opts = [
                ("L", "Login"),
                ("Q", "Quit"),
            ]
        else:
            opts = [
                ("1", "Profile"),
                ("2", "Games"),
                ("3", "Achievements"),
                ("4", "Presence spoof"),
                ("5", "HTTP server"),
                ("6", "Settings"),
                ("O", "Logout"),
                ("Q", "Quit"),
            ]

        choice = choose(opts)

        if choice == "L":
            do_login()
        elif choice == "O":
            do_logout()
        elif choice == "Q":
            shutdown()
            sys.exit(0)
        elif choice == "1":
            menu_profile()
        elif choice == "2":
            menu_games()
        elif choice == "3":
            menu_achievements()
        elif choice == "4":
            menu_spoof()
        elif choice == "5":
            menu_server()
        elif choice == "6":
            menu_settings()


def shutdown():
    print("\n  Shutting down...")
    try:
        if _session.spoofer and _session.spoofer.is_active:
            _session.spoofer.stop()
    except Exception:
        pass
    try:
        if _session.server and _session.server.is_running:
            _session.server.stop()
    except Exception:
        pass
    print("  Bye.")


if __name__ == "__main__":
    import signal

    def sig_handler(sig, frame):
        shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)

    print("\n  xaul")
    print()

    if _AUTH_FILE.exists():
        print("  Found saved session, attempting auto-login...")
        do_login()

    main_menu()
