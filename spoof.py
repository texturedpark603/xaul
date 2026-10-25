from __future__ import annotations
import threading
import time
from typing import Optional
from api import XboxAPI
HEARTBEAT_INTERVAL = 300
class Spoofer:
    def __init__(self, api: XboxAPI, xuid: str) -> None:
        self._api = api
        self._xuid = xuid
        self._title_id: Optional[str] = None
        self._active = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self.status = "Not spoofing"
    @property
    def is_active(self) -> bool:
        return self._active
    @property
    def current_title_id(self) -> Optional[str]:
        return self._title_id
    def start(self, title_id: str) -> None:
        if self._active:
            self.stop()
        self._title_id = title_id
        self._stop_event.clear()
        self._active = True
        self.status = f"Spoofing TitleID {title_id}"

        self._thread = threading.Thread(
            target=self._loop,
            name="spoof-heartbeat",
            daemon=True,
        )
        self._thread.start()
        print(f"[spoof] Started spoofing TitleID {title_id}.")
    def stop(self) -> None:
        if not self._active:
            return
        self._active = False
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        try:
            self._api.stop_heartbeat(self._xuid)
            print("[spoof] Presence cleared (DELETE heartbeat sent).")
        except Exception as exc:
            print(f"[spoof] Warning: DELETE heartbeat failed — {exc}")
        self.status = "Not spoofing"
        self._title_id = None
    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._api.send_heartbeat(self._xuid, self._title_id)
            except Exception as exc:
                print(f"[spoof] Heartbeat failed: {exc}")
            for _ in range(HEARTBEAT_INTERVAL):
                if self._stop_event.is_set():
                    return
                time.sleep(1)