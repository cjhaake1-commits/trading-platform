from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

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

