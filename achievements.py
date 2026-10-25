from __future__ import annotations

import io
import json
import os
import random
import re
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from api import XboxAPI, extract_scid_from_achievements, is_event_based, is_360_title
from auth import is_events_token

data_dir = Path.home() / "Documents" / "xaul"
events_dir = data_dir / "Events"
data_json_path = events_dir / "Data.json"
meta_json_path = events_dir / "meta.json"
settings_path = data_dir / "settings.json"


def load_data_json():
    if not data_json_path.exists():
        raise FileNotFoundError(
            f"Events Data.json not found at {data_json_path}.\n"
            "Run 'Update events data' from the Events menu to download it."
        )
    return json.loads(data_json_path.read_text(encoding="utf-8"))


def load_events_template(title_id):
    path = events_dir / f"{title_id}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"No event template for title {title_id} at {path}.\n"
            "This title may not be supported yet."
        )
    return path.read_text(encoding="utf-8")


def load_events_token():
    if settings_path.exists():
        try:
            s = json.loads(settings_path.read_text(encoding="utf-8"))
            return s.get("cached_events_token")
        except Exception:
            pass
    return None


def save_events_token(token):
    data_dir.mkdir(parents=True, exist_ok=True)
    settings = {}
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    settings["cached_events_token"] = token
    settings["events_token_obtained_at"] = datetime.utcnow().isoformat()
    settings_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")


def update_events_data(api: XboxAPI, force=False):
    print("[events] Checking for events data updates...")
    try:
        remote_meta = api.get_events_meta()
    except Exception as exc:
        print(f"[events] Could not reach GitHub: {exc}")
        return False

    local_timestamp = 0
    if meta_json_path.exists():
        try:
            local_meta = json.loads(meta_json_path.read_text(encoding="utf-8"))
            local_timestamp = int(local_meta.get("Timestamp", 0))
        except Exception:
            pass

    remote_timestamp = int(remote_meta.get("Timestamp", 0))

    if not force and remote_timestamp <= local_timestamp:
        print("[events] Events data is already up to date.")
        return False

    print(f"[events] Downloading events data (remote ts={remote_timestamp})...")
    events_dir.mkdir(parents=True, exist_ok=True)
    zip_path = data_dir / "Events.zip"

    try:
        api.download_events_zip(str(zip_path))
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(data_dir)
        zip_path.unlink(missing_ok=True)
        meta_json_path.write_text(json.dumps(remote_meta, indent=2), encoding="utf-8")
        print("[events] Events data updated successfully.")
        return True
    except Exception as exc:
        print(f"[events] Update failed: {exc}")
        return False


def get_supported_titles():
    try:
        data = load_data_json()
        return [int(t) for t in data.get("SupportedTitleIDs", [])]
    except Exception:
        return []


def fmt_date(iso_str):
    if not iso_str:
        return "Not unlocked"
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return iso_str or "Not unlocked"


def fmt_rarity(pct_str, category):
    try:
        pct = float(pct_str or "0")
        return f"{pct:.1f}% ({category or '?'})"
    except Exception:
        return category or "?"


def print_achievements(achievements_data, show_locked_only=False):
    achs = achievements_data.get("achievements", [])
    if not achs:
        print("  (no achievements returned)")
        return

    locked = [a for a in achs if a.get("progressState") != "Achieved"]
    unlocked = [a for a in achs if a.get("progressState") == "Achieved"]

    print(f"\n  Total: {len(achs)}  |  Unlocked: {len(unlocked)}  |  Locked: {len(locked)}")
    print()

    display = locked if show_locked_only else achs
    for a in display:
        state = "✓" if a.get("progressState") == "Achieved" else "✗"
        gs = ""
        for r in a.get("rewards", []):
            if r.get("type") == "Gamerscore":
                gs = f"  [{r.get('value', '?')}G]"
                break
        secret = " [SECRET]" if a.get("isSecret") else ""
        rarity = fmt_rarity(
            a.get("rarity", {}).get("currentPercentage"),
            a.get("rarity", {}).get("currentCategory"),
        )
        unlocked_at = fmt_date(a.get("progression", {}).get("timeUnlocked"))
        print(f"  [{state}] ID:{a.get('id','?'):>4}  {a.get('name','?')}{gs}{secret}")
        print(f"          {a.get('description','')}")
        print(f"          Rarity: {rarity}  |  Unlocked: {unlocked_at}")
        print()


def print_achievements_360(achievements_data):
    achs = achievements_data.get("achievements", [])
    if not achs:
        print("  (no 360 achievements returned)")
        return

    locked = sum(1 for a in achs if not a.get("timeUnlocked") or a["timeUnlocked"].startswith("0001"))
    print(f"\n  Total: {len(achs)}  |  Locked: {locked}  (360 titles cannot be unlocked here)")
    print()
    for a in achs:
        unlocked = not (not a.get("timeUnlocked") or a["timeUnlocked"].startswith("0001"))
        state = "✓" if unlocked else "✗"
        secret = " [SECRET]" if a.get("isSecret") else ""
        gs = a.get("gamerscore", "?")
        rarity = fmt_rarity(
            a.get("rarity", {}).get("currentPercentage"),
            a.get("rarity", {}).get("currentCategory"),
        )
        print(f"  [{state}] ID:{a.get('id','?'):>4}  {a.get('name','?')}  [{gs}G]{secret}")
        print(f"          {a.get('description','')}")
        print(f"          Rarity: {rarity}")
        print()


class AchievementManager:
    def __init__(self, api: XboxAPI, xuid: str, fake_signature=True):
        self._api = api
        self._xuid = xuid
        self._fake_sig = fake_signature
        self._events_token: Optional[str] = load_events_token()
        self._scid_cache: dict[str, str] = {}
        self._ach_cache: dict[str, dict] = {}

    @property
    def events_token(self):
        return self._events_token

    def set_events_token(self, token):
        token = token.strip()
        if not is_events_token(token):
            print("[events] WARNING: Token did not pass x5t validation. It may be for the wrong RP.")
            print("[events] Storing it anyway — it may still work if you know what you're doing.")
        self._events_token = token
        save_events_token(token)
        print("[events] Events token saved.")
        return True

    def require_events_token(self):
        if not self._events_token:
            raise RuntimeError(
                "No events token set. Use 'Set events token' from the Events menu."
            )
        return self._events_token

    def fetch_achievements(self, title_id):
        try:
            data = self._api.get_achievements(self._xuid, title_id)
            if data.get("achievements"):
                event_based = is_event_based(data)
                self._ach_cache[title_id] = data
                scid = extract_scid_from_achievements(data)
                if scid:
                    self._scid_cache[title_id] = scid
                return data, False, event_based
        except Exception as exc:
            print(f"[achievements] OneCore fetch failed ({exc}), trying 360...")

        try:
            data360 = self._api.get_achievements_360(self._xuid, title_id)
            if data360.get("achievements"):
                return data360, True, False
        except Exception as exc:
            print(f"[achievements] 360 fetch also failed: {exc}")

        return {}, False, False

    def get_scid(self, title_id):
        if title_id in self._scid_cache:
            return self._scid_cache[title_id]
        data, is_360, _ = self.fetch_achievements(title_id)
        if is_360 or not data:
            raise RuntimeError(f"Cannot resolve SCID for title {title_id}")
        scid = extract_scid_from_achievements(data)
        if not scid:
            raise RuntimeError(f"No SCID in achievement data for title {title_id}")
        self._scid_cache[title_id] = scid
        return scid

    def unlock_one(self, title_id, achievement_id):
        scid = self.get_scid(title_id)
        self._api.unlock_achievements(self._xuid, scid, title_id, [achievement_id], self._fake_sig)
        print(f"[unlock] Achievement {achievement_id} unlocked for title {title_id}.")

    def unlock_all(self, title_id):
        data, is_360, event_based = self.fetch_achievements(title_id)

        if is_360:
            raise RuntimeError("Xbox 360 titles are not supported for unlocking.")
        if event_based:
            raise RuntimeError("This is an event-based title. Use 'Unlock event achievement' instead.")
        if not data.get("achievements"):
            raise RuntimeError("No achievements found for this title.")

        scid = extract_scid_from_achievements(data)
        if not scid:
            raise RuntimeError("Could not determine serviceConfigId.")

        locked_ids = [
            a["id"]
            for a in data["achievements"]
            if a.get("progressState") != "Achieved"
        ]

        if not locked_ids:
            print("[unlock] All achievements are already unlocked.")
            return 0

        print(f"[unlock] Unlocking {len(locked_ids)} achievement(s) for title {title_id}...")
        self._api.unlock_achievements(self._xuid, scid, title_id, locked_ids, self._fake_sig)
        print(f"[unlock] Done. {len(locked_ids)} achievement(s) unlocked.")
        return len(locked_ids)

    def unlock_event_achievement(self, title_id, achievement_id):
        events_token = self.require_events_token()

        data_json = load_data_json()
        supported = [str(t) for t in data_json.get("SupportedTitleIDs", [])]
        if title_id not in supported:
            raise RuntimeError(
                f"Title {title_id} is not in the supported events titles list.\n"
                "Check Data.json or run an events data update."
            )

        title_data = data_json.get(title_id, {})
        achievements_section = title_data.get("Achievements", {})

        if achievement_id not in achievements_section:
            raise RuntimeError(
                f"Achievement {achievement_id} has no criteria defined for title {title_id}."
            )

        body = load_events_template(title_id)
        criteria = achievements_section[achievement_id]
        body = self.apply_criteria(body, criteria)

        now = datetime.utcnow()
        body = body.replace("REPLACETIME", now.strftime("%Y-%m-%dT%H:%M:%S.0000000Z"))
        body = body.replace("REPLACESEQ", str(int(time.time())))
        body = body.replace("REPLACEXUID", self._xuid)

        try:
            body = json.dumps(json.loads(body), separators=(",", ":"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Template JSON is invalid after replacements: {exc}")

        r = self._api.unlock_event_achievement(events_token, body)
        print(f"[events] POST {r.url} => HTTP {r.status_code}")
        if not r.ok:
            print(f"[events] Response: {r.text[:500]}")
            raise RuntimeError(f"Event unlock failed: HTTP {r.status_code}")
        print(f"[events] Achievement {achievement_id} event sent successfully.")

    def unlock_all_event_achievements(self, title_id):
        events_token = self.require_events_token()

        data_json = load_data_json()
        supported = [str(t) for t in data_json.get("SupportedTitleIDs", [])]
        if title_id not in supported:
            raise RuntimeError(f"Title {title_id} is not supported for event-based unlocking.")

        data, is_360, _ = self.fetch_achievements(title_id)
        already_unlocked = set()
        if not is_360 and data.get("achievements"):
            already_unlocked = {
                a["id"] for a in data["achievements"]
                if a.get("progressState") == "Achieved"
            }

        title_data = data_json.get(title_id, {})
        achievements_section = title_data.get("Achievements", {})

        sent = 0
        for ach_id, criteria in achievements_section.items():
            if ach_id in already_unlocked:
                print(f"[events] Achievement {ach_id} already unlocked, skipping.")
                continue
            try:
                self.unlock_event_achievement(title_id, ach_id)
                sent += 1
                time.sleep(0.5)
            except Exception as exc:
                print(f"[events] Failed to unlock achievement {ach_id}: {exc}")

        return sent

    @staticmethod
    def apply_criteria(body, criteria):
        for key, replacement_data in criteria.items():
            if key == "EventReplacement":
                target = replacement_data.get("Target", "")
                replacement = str(replacement_data.get("Replacement", ""))
                body = body.replace(target, replacement)
                continue

            if key == "DataReplacement":
                for _, sub in replacement_data.items():
                    body = AchievementManager.apply_single_replacement(body, sub)
                continue

            if key == "CriteriaReplacement":
                body = AchievementManager.apply_single_replacement(body, replacement_data)
                continue

            if isinstance(replacement_data, dict) and "ReplacementType" in replacement_data:
                body = AchievementManager.apply_single_replacement(body, replacement_data)

        return body

    @staticmethod
    def apply_single_replacement(body, rd):
        rtype = rd.get("ReplacementType", "Replace")
        target = rd.get("Target", "")

        if not target:
            return body

        if rtype == "Replace":
            replacement = str(rd.get("Replacement", ""))
            return body.replace(target, replacement)

        elif rtype == "RangeInt":
            lo = int(rd.get("Min", 0))
            hi = int(rd.get("Max", 1))
            return body.replace(target, str(random.randint(lo, hi)))

        elif rtype == "RangeFloat":
            lo = float(rd.get("Min", 0))
            hi = float(rd.get("Max", 1))
            return body.replace(target, str(random.uniform(lo, hi)))

        elif rtype == "StupidFuckingLDAPTimestamp":
            EPOCH_DIFF = 116_444_736_000_000_000
            ldap_ts = int(time.time() * 10_000_000) + EPOCH_DIFF
            return body.replace(target, str(ldap_ts))

        else:
            print(f"[events] Unknown replacement type '{rtype}', skipping.")
            return body

    def list_supported_event_titles(self):
        supported = get_supported_titles()
        if not supported:
            print("  No supported event titles found. Run an events data update.")
            return
        print(f"\n  {len(supported)} supported event title(s):")
        for tid in supported:
            data_json = load_data_json()
            title_data = data_json.get(str(tid), {})
            fully = "✓ Fully" if title_data.get("FullySupported") else "~ Partial"
            ach_count = len(title_data.get("Achievements", {}))
            print(f"    TitleID: {tid:>12}  |  {fully}  |  {ach_count} achievement(s) defined")
        print()
