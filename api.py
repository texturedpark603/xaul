from __future__ import annotations

import json
import re
from typing import Optional

import requests

GAMERTAG_URL = "https://profile.xboxlive.com/users/me/profile/settings?settings=Gamertag"
PROFILE_BY_XUID = "https://peoplehub.xboxlive.com/users/me/people/xuids({xuid})/decoration/detail,preferredColor,presenceDetail,multiplayerSummary"
PROFILE_BY_GT = "https://profile.xboxlive.com/users/gt({gamertag})/profile/settings?settings=GameDisplayPicRaw,Gamerscore,Gamertag"
TITLE_INFO = "https://titlehub.xboxlive.com/users/xuid({xuid})/titles/batch/decoration/GamePass,Achievement,Stats"
TITLES_HISTORY = "https://titlehub.xboxlive.com/users/xuid({xuid})/titles/titleHistory/decoration/Achievement,detail,scid?maxItems=10000"
GAMEPASS_MEMBERSHIP = "https://xgrant.xboxlive.com/users/xuid({xuid})/programInfo?filter=profile,activities,catalog"
ACHIEVEMENTS = "https://achievements.xboxlive.com/users/xuid({xuid})/achievements?titleId={title_id}&maxItems=1000"
ACHIEVEMENTS_360 = "https://achievements.xboxlive.com/users/xuid({xuid})/titleachievements?titleId={title_id}&maxItems=1000"
UNLOCK_ACHIEVEMENTS = "https://achievements.xboxlive.com/users/xuid({xuid})/achievements/{scid}/update"
HEARTBEAT = "https://presence-heartbeat.xboxlive.com/users/xuid({xuid})/devices/current/"
USER_STATS = "https://userstats.xboxlive.com/batch"
EVENTS_TELEMETRY = "https://v20.events.data.microsoft.com/OneCollector/1.0/"
GAMEPASS_CATALOG = "https://catalog.gamepass.com/products?market=GB&language=en-GB&hydration=PCHome"

GITHUB_RELEASES = "https://api.github.com/repos/Fumo-Unlockers/Xbox-Achievement-unlocker/releases"
GITHUB_EVENTS_META = "https://raw.githubusercontent.com/Fumo-Unlockers/Xbox-Achievement-Unlocker/Events-Data/meta.json"
GITHUB_EVENTS_ZIP = "https://github.com/Fumo-Unlockers/Xbox-Achievement-Unlocker/raw/Events-Data/Events.zip"
GITHUB_XBOX_GAMES_CONTENTS = "https://api.github.com/repos/Fumo-Unlockers/XboxGames/contents"

DBOX_SEARCH = "https://dbox.tools/api/title_ids/?name={query}&limit=100&offset=0"

FAKE_SIGNATURE = (
    "RGFtbklHb3R0YU1ha2VUaGlzU3RyaW5nU3VwZXJMb25nSHVoLkRvbnRFdmVu"
    "S25vd1doYXRTaG91bGRCZUhlcmVEcmFmZlN0cmluZw=="
)

EVENTS_APIKEY = (
    "0890af88a9ed4cc886a14f5e174a2827-9de66c5e-f867-43a8-a7b8-e0ddd481cca4-7548,"
    "95c1f21d6cb047a09e7b423c1cb2222e-9965f07b-54fa-498e-9727-9e8d24dec39e-7027"
)
EVENTS_CLIENT_VERSION = (
    "EUTC-Windows-C++-no-10.0.22621.3296.amd64fre.ni_release.220506-1250-no"
)


def make_session(accept_language="en-US"):
    s = requests.Session()
    s.headers.update({
        "Accept": "application/json",
        "Accept-Encoding": "gzip, deflate",
        "Accept-Language": accept_language,
    })
    return s


def make_events_session():
    s = requests.Session()
    s.verify = False
    s.headers.update({
        "User-Agent": "MSDW",
        "Cache-Control": "no-cache",
        "Accept": "application/json",
        "Accept-Encoding": "gzip, deflate",
        "Reliability-Mode": "standard",
        "Client-Version": EVENTS_CLIENT_VERSION,
        "apikey": EVENTS_APIKEY,
        "Client-Id": "NO_AUTH",
        "Host": "v20.events.data.microsoft.com",
        "Connection": "close",
    })
    return s


class XboxAPI:
    def __init__(self, xauth: str, region_override=False, fake_signature=True):
        self._xauth = xauth
        self._lang = "en-GB" if region_override else "en-US"
        self._fake_sig = fake_signature

    def _get(self, url, contract=None, extra=None):
        headers = self._base_headers(contract, extra)
        r = requests.get(url, headers=headers, timeout=30)
        r.raise_for_status()
        return r.json()

    def _post(self, url, body, contract=None, extra=None, content_type="application/json"):
        headers = self._base_headers(contract, extra)
        headers["Content-Type"] = content_type
        r = requests.post(url, json=body, headers=headers, timeout=30)
        return r

    def _post_raw(self, url, body_str, content_type, extra=None):
        headers = self._base_headers(extra=extra)
        headers["Content-Type"] = content_type
        r = requests.post(url, data=body_str.encode("utf-8"), headers=headers, timeout=30)
        return r

    def _delete(self, url, contract=None):
        headers = self._base_headers(contract)
        r = requests.delete(url, headers=headers, timeout=30)
        return r

    def _base_headers(self, contract=None, extra=None):
        h = {
            "Authorization": self._xauth,
            "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate",
            "Accept-Language": self._lang,
        }
        if contract:
            h["x-xbl-contract-version"] = contract
        if extra:
            h.update(extra)
        return h

    def get_basic_profile(self):
        return self._get(
            GAMERTAG_URL,
            contract="2",
            extra={"Host": "profile.xboxlive.com", "Connection": "Keep-Alive"},
        )

    def get_profile_by_xuid(self, xuid):
        url = PROFILE_BY_XUID.format(xuid=xuid)
        return self._get(
            url,
            contract="5",
            extra={"Host": "peoplehub.xboxlive.com", "Connection": "Keep-Alive"},
        )

    def get_profile_by_gamertag(self, gamertag):
        url = PROFILE_BY_GT.format(gamertag=gamertag)
        return self._get(
            url,
            contract="2",
            extra={"Host": "profile.xboxlive.com"},
        )

    def get_xuid_for_gamertag(self, gamertag):
        try:
            data = self.get_profile_by_gamertag(gamertag)
            return data["profileUsers"][0]["id"]
        except Exception:
            return None

    def get_title_info(self, xuid, title_id):
        url = TITLE_INFO.format(xuid=xuid)
        r = self._post(url, body={"Pfns": None, "TitleIds": [title_id]}, contract="2")
        r.raise_for_status()
        return r.json()

    def get_games_list(self, xuid):
        url = TITLES_HISTORY.format(xuid=xuid)
        return self._get(
            url,
            contract="2",
            extra={"Host": "titlehub.xboxlive.com", "Connection": "Keep-Alive"},
        )

    def get_gamepass_membership(self, xuid):
        url = GAMEPASS_MEMBERSHIP.format(xuid=xuid)
        return self._get(url)

    def get_game_stats(self, xuid, title_id):
        body = {
            "ArrangeByField": "xuid",
            "Xuids": [xuid],
            "Stats": [{"Name": "MinutesPlayed", "TitleId": title_id}],
        }
        r = self._post(USER_STATS, body=body, contract="2")
        r.raise_for_status()
        return r.json()

    def get_gamepass_catalog(self, product_id):
        r = self._post(GAMEPASS_CATALOG, body={"Products": [product_id]})
        r.raise_for_status()
        return r.json()

    def get_achievements(self, xuid, title_id):
        url = ACHIEVEMENTS.format(xuid=xuid, title_id=title_id)
        return self._get(
            url,
            contract="4",
            extra={"Host": "achievements.xboxlive.com", "Connection": "Keep-Alive"},
        )

    def get_achievements_360(self, xuid, title_id):
        url = ACHIEVEMENTS_360.format(xuid=xuid, title_id=title_id)
        return self._get(
            url,
            contract="3",
            extra={"Host": "achievements.xboxlive.com", "Connection": "Keep-Alive"},
        )

    def unlock_achievements(self, xuid, scid, title_id, achievement_ids, use_fake_signature=True):
        url = UNLOCK_ACHIEVEMENTS.format(xuid=xuid, scid=scid)
        extra = {
            "Host": "achievements.xboxlive.com",
            "Connection": "Keep-Alive",
            "User-Agent": "XboxServicesAPI/2021.10.20211005.0 c",
        }
        if use_fake_signature or self._fake_sig:
            extra["Signature"] = FAKE_SIGNATURE

        chunk_size = 50
        for i in range(0, len(achievement_ids), chunk_size):
            chunk = achievement_ids[i: i + chunk_size]
            body = {
                "action": "progressUpdate",
                "serviceConfigId": scid,
                "titleId": title_id,
                "userId": xuid,
                "achievements": [
                    {"id": aid, "percentComplete": "100"} for aid in chunk
                ],
            }
            body_str = json.dumps(body, separators=(",", ":"))
            headers = self._base_headers(contract="2", extra=extra)
            headers["Content-Type"] = "application/json"
            r = requests.post(url, data=body_str.encode(), headers=headers, timeout=30)
            if r.status_code != 200:
                raise RuntimeError(
                    f"Unlock failed for title {title_id}: HTTP {r.status_code} — {r.text[:300]}"
                )

    def unlock_event_achievement(self, events_token, body_str):
        auth_xtoken = re.sub(r"XBL3\.0 x=\d+;", "XBL3.0 x=-;", events_token)

        s = make_events_session()
        s.headers["authxtoken"] = auth_xtoken
        s.headers["tickets"] = f'"1"="{events_token}"'
        s.headers["Content-Type"] = "application/x-json-stream"

        r = s.post(EVENTS_TELEMETRY, data=body_str.encode("utf-8"), timeout=30)
        return r

    def send_heartbeat(self, xuid, title_id):
        url = HEARTBEAT.format(xuid=xuid)
        body = {
            "titles": [
                {
                    "expiration": 600,
                    "id": title_id,
                    "state": "active",
                    "sandbox": "RETAIL",
                }
            ]
        }
        r = self._post(url, body=body, contract="3")
        if r.status_code not in (200, 204):
            raise RuntimeError(f"Heartbeat failed: HTTP {r.status_code}")

    def stop_heartbeat(self, xuid):
        url = HEARTBEAT.format(xuid=xuid)
        self._delete(url, contract="3")

    def get_latest_release(self):
        r = requests.get(GITHUB_RELEASES, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        r.raise_for_status()
        return r.json()

    def get_events_meta(self):
        r = requests.get(GITHUB_EVENTS_META, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        r.raise_for_status()
        return r.json()

    def download_events_zip(self, dest_path):
        r = requests.get(GITHUB_EVENTS_ZIP, headers={"User-Agent": "Mozilla/5.0"}, stream=True, timeout=60)
        r.raise_for_status()
        with open(dest_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=65536):
                f.write(chunk)

    def search_titles(self, query):
        url = DBOX_SEARCH.format(query=requests.utils.quote(query))
        r = requests.get(url, headers={"Accept": "application/json"}, timeout=30)
        r.raise_for_status()
        return r.json()


def extract_scid_from_achievements(achievements_data):
    try:
        return achievements_data["achievements"][0]["serviceConfigId"]
    except (KeyError, IndexError):
        return None


def is_event_based(achievements_data):
    zero_uid = "00000000-0000-0000-0000-000000000000"
    try:
        for ach in achievements_data.get("achievements", []):
            reqs = ach.get("progression", {}).get("requirements", [])
            if reqs and reqs[0].get("id") != zero_uid:
                return True
    except Exception:
        pass
    return False


def is_360_title(title_info):
    try:
        devices = title_info["Titles"][0].get("Devices", [])
        return "Xbox360" in devices or "Mobile" in devices
    except (KeyError, IndexError):
        return False
