from __future__ import annotations

import base64
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from .config import KalshiConfig


@dataclass(frozen=True)
class KalshiAuthReference:
    api_key_id: str | None
    private_key_path: str | None

    @classmethod
    def from_config(cls, config: KalshiConfig) -> "KalshiAuthReference":
        return cls(config.api_key_id, config.private_key_path)

    def private_key_available(self) -> bool:
        return bool(self.private_key_path and Path(self.private_key_path).is_file())

    def require_credentials(self):
        if not self.api_key_id or not self.private_key_path:
            raise RuntimeError("Kalshi authenticated request requires KALSHI_API_KEY_ID and KALSHI_PRIVATE_KEY_PATH")
        path = Path(self.private_key_path)
        if not path.is_file():
            raise RuntimeError("Kalshi private key path is invalid")

    def sign(self, method: str, path: str, *, timestamp_ms: int | None = None) -> dict[str, str]:
        self.require_credentials()
        timestamp = str(timestamp_ms if timestamp_ms is not None else int(time.time() * 1000))
        clean_path = urlparse(path).path.split("?")[0]
        if not clean_path.startswith("/"):
            clean_path = "/" + clean_path
        message = f"{timestamp}{method.upper()}{clean_path}".encode()
        try:
            completed = subprocess.run(
                ["openssl", "dgst", "-sha256", "-sign", str(self.private_key_path),
                 "-sigopt", "rsa_padding_mode:pss", "-sigopt", "rsa_pss_saltlen:32"],
                input=message, capture_output=True, check=True,
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            raise RuntimeError("Kalshi private key could not be loaded for signing") from exc
        signature = completed.stdout
        return {"KALSHI-ACCESS-KEY": self.api_key_id, "KALSHI-ACCESS-TIMESTAMP": timestamp, "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode()}
