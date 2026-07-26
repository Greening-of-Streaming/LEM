"""Shelly smart plug implementation of BaseDevice.

Uses direct async HTTP — requires the optional aiohttp dependency
(pip install 'measure[shelly]').

Supports:
  Gen1  (Shelly Plug S, Plug US)  — GET /meter/0
  Gen2/3 — metering lives under different components depending on the model:
    switch:0  Switch.GetStatus (apower)     — relays w/ metering (Plug S/Plus/Pro)
    pm1:0     PM1.GetStatus    (apower)     — metering-only plugs (Plug PM G3)
    em1:0     EM1.GetStatus    (act_power)  — energy monitors

Generation and metering component are auto-detected on connect().
Credentials are optional (many Shelly devices ship with no auth).
"""

import aiohttp

from lem.devices.base import BaseDevice

# Gen2/3 metering component -> (RPC status path, power field). Checked in order;
# the first component present on the device wins. Some models (e.g. the Shelly
# Plug PM G3) have no Switch at all and expose power only under pm1:0 — querying
# Switch.GetStatus there 404s, which previously read as a silent 0 W.
_GEN2_METERS = (
    ("switch:0", "Switch.GetStatus?id=0", "apower"),
    ("pm1:0", "PM1.GetStatus?id=0", "apower"),
    ("em1:0", "EM1.GetStatus?id=0", "act_power"),
)
_GEN2_METER_DEFAULT = ("Switch.GetStatus?id=0", "apower")


def _select_gen2_meter(status: dict) -> tuple[str, str]:
    """Pick the metering component from a Shelly.GetStatus body."""
    for key, path, field in _GEN2_METERS:
        if key in status:
            return path, field
    return _GEN2_METER_DEFAULT


class ShellyDevice(BaseDevice):

    def __init__(self):
        self._ip = None
        self._auth = None    # aiohttp.BasicAuth or None
        self._gen = None     # 1 or 2
        self._meter = None   # (rpc path, field) for Gen2/3
        self._session = None

    async def connect(self, ip: str, username: str = None, password: str = None) -> bool:
        self._ip = ip
        self._auth = aiohttp.BasicAuth(username, password) if username and password else None

        if self._session and not self._session.closed:
            await self._session.close()
        self._session = aiohttp.ClientSession()

        timeout = aiohttp.ClientTimeout(total=5)

        # Try Gen2/3 first — the same call tells us which metering component exists.
        try:
            async with self._session.get(
                f"http://{ip}/rpc/Shelly.GetStatus", auth=self._auth, timeout=timeout
            ) as r:
                if r.status == 200:
                    self._gen = 2
                    status = await r.json(content_type=None)
                    self._meter = _select_gen2_meter(status)
                    return True
        except Exception:
            pass

        # Fall back to Gen1
        try:
            async with self._session.get(
                f"http://{ip}/status", auth=self._auth, timeout=timeout
            ) as r:
                if r.status == 200:
                    self._gen = 1
                    return True
        except Exception:
            pass

        raise ConnectionError(f"Could not reach Shelly device at {ip}")

    async def get_power_mw(self) -> float:
        timeout = aiohttp.ClientTimeout(total=5)
        if self._gen == 2:
            path, field = self._meter
            url = f"http://{self._ip}/rpc/{path}"
        else:
            url, field = f"http://{self._ip}/meter/0", "power"

        async with self._session.get(url, auth=self._auth, timeout=timeout) as r:
            r.raise_for_status()  # don't let a 404 masquerade as 0 W
            data = await r.json(content_type=None)

        return round(float(data.get(field, 0.0)) * 1000, 2)

    async def disconnect(self):
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None
