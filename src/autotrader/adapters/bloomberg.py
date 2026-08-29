from __future__ import annotations

import os
import platform
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any


_VALID_MODES = {"auto", "dapi", "sapi"}


def _env_bool(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class BloombergConfig:
    """Licensed Bloomberg research connection settings.

    The adapter is deliberately read-only. It does not submit orders and it
    never treats a successful data connection as permission to enable live
    trading.
    """

    enabled: bool = False
    license_acknowledged: bool = False
    research_only: bool = True
    mode: str = "auto"
    host: str = "127.0.0.1"
    port: int = 8194
    connect_timeout_ms: int = 5000
    reference_data_service: str = "//blp/refdata"
    market_data_service: str = "//blp/mktdata"
    auth_options: str = ""
    application_name: str = ""

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "BloombergConfig":
        source = os.environ if env is None else env
        mode = str(source.get("BLOOMBERG_MODE", "auto")).strip().lower()
        if mode not in _VALID_MODES:
            mode = "auto"
        try:
            port = int(source.get("BLOOMBERG_PORT", "8194"))
        except (TypeError, ValueError):
            port = 8194
        try:
            timeout = int(source.get("BLOOMBERG_CONNECT_TIMEOUT_MS", "5000"))
        except (TypeError, ValueError):
            timeout = 5000
        return cls(
            enabled=_env_bool(source.get("BLOOMBERG_ENABLED")),
            license_acknowledged=_env_bool(source.get("BLOOMBERG_LICENSE_ACK")),
            research_only=_env_bool(source.get("BLOOMBERG_RESEARCH_ONLY"), default=True),
            mode=mode,
            host=str(source.get("BLOOMBERG_HOST", "127.0.0.1")).strip() or "127.0.0.1",
            port=port,
            connect_timeout_ms=timeout,
            reference_data_service=str(
                source.get("BLOOMBERG_REFERENCE_DATA_SERVICE", "//blp/refdata")
            ).strip()
            or "//blp/refdata",
            market_data_service=str(
                source.get("BLOOMBERG_MARKET_DATA_SERVICE", "//blp/mktdata")
            ).strip()
            or "//blp/mktdata",
            auth_options=str(source.get("BLOOMBERG_AUTH_OPTIONS", "")).strip(),
            application_name=str(source.get("BLOOMBERG_APPLICATION_NAME", "")).strip(),
        )

    def validation_errors(self, *, system: str | None = None) -> tuple[str, ...]:
        errors: list[str] = []
        operating_system = (system or platform.system()).strip().lower()
        if self.enabled and not self.license_acknowledged:
            errors.append("Bloomberg access requires an acknowledged, authorized Bloomberg data license")
        if not self.research_only:
            errors.append("Bloomberg adapter must remain research-only")
        if self.mode == "dapi" and operating_system == "linux":
            errors.append(
                "Bloomberg Desktop API is not supported directly on Linux; use an authorized Windows Terminal host or licensed SAPI/B-PIPE"
            )
        if not 1 <= self.port <= 65535:
            errors.append("Bloomberg port must be between 1 and 65535")
        if not 1 <= self.connect_timeout_ms <= 120000:
            errors.append("Bloomberg connect timeout must be between 1 and 120000 milliseconds")
        return tuple(errors)

    def public_summary(self) -> dict[str, object]:
        """Return non-secret configuration suitable for health telemetry."""
        payload = asdict(self)
        payload.pop("auth_options", None)
        payload["application_name_configured"] = bool(self.application_name)
        payload.pop("application_name", None)
        return payload


@dataclass(frozen=True)
class BloombergConnectionStatus:
    state: str
    connected: bool
    mode: str
    host: str
    port: int
    reference_data_service: str
    market_data_service: str
    reason: str
    research_only: bool = True

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


class BloombergAdapter:
    """Optional BLPAPI connection probe for licensed research data.

    ``blpapi`` is imported lazily so the core paper platform remains usable
    without Bloomberg software. The adapter only verifies connectivity and
    service availability; it cannot place orders or change trading modes.
    """

    def __init__(self, config: BloombergConfig | None = None) -> None:
        self.config = config or BloombergConfig.from_env()

    def _status(self, state: str, connected: bool, reason: str) -> BloombergConnectionStatus:
        return BloombergConnectionStatus(
            state=state,
            connected=connected,
            mode=self.config.mode.upper(),
            host=self.config.host,
            port=self.config.port,
            reference_data_service=self.config.reference_data_service,
            market_data_service=self.config.market_data_service,
            reason=reason,
            research_only=True,
        )

    def build_session_options(self, blpapi_module: Any) -> Any:
        errors = self.config.validation_errors()
        if errors:
            raise RuntimeError("; ".join(errors))

        options = blpapi_module.SessionOptions()
        options.setServerHost(self.config.host)
        options.setServerPort(self.config.port)
        options.setConnectTimeout(self.config.connect_timeout_ms)

        client_mode = getattr(blpapi_module.SessionOptions, self.config.mode.upper())
        options.setClientMode(client_mode)
        if hasattr(options, "setAutoRestartOnDisconnection"):
            options.setAutoRestartOnDisconnection(True)
        if hasattr(options, "setRecordSubscriptionDataReceiveTimes"):
            options.setRecordSubscriptionDataReceiveTimes(True)

        if self.config.application_name:
            auth_type = getattr(blpapi_module, "AuthOptions", None)
            if auth_type is None or not hasattr(options, "setSessionIdentityOptions"):
                raise RuntimeError("Installed BLPAPI does not support application identity options")
            options.setSessionIdentityOptions(auth_type.createWithApp(self.config.application_name))
        elif self.config.auth_options:
            options.setAuthenticationOptions(self.config.auth_options)
        return options

    def probe(self) -> BloombergConnectionStatus:
        if not self.config.enabled:
            return self._status("DISABLED", False, "BLOOMBERG_ENABLED is false")

        errors = self.config.validation_errors()
        if errors:
            return self._status("BLOCKED", False, "; ".join(errors))

        try:
            import blpapi  # type: ignore[import-not-found]
        except ImportError:
            return self._status(
                "UNAVAILABLE",
                False,
                "BLPAPI is not installed; install the optional Bloomberg dependency on an authorized host",
            )

        session = None
        try:
            session = blpapi.Session(self.build_session_options(blpapi))
            if not session.start():
                return self._status("UNAVAILABLE", False, "Bloomberg session did not start")
            if not session.openService(self.config.reference_data_service):
                return self._status(
                    "UNAVAILABLE",
                    False,
                    f"Bloomberg service unavailable: {self.config.reference_data_service}",
                )
            return self._status(
                "CONNECTED",
                True,
                "Licensed Bloomberg session and reference-data service are available",
            )
        except Exception as exc:
            return self._status("UNAVAILABLE", False, f"Bloomberg connection failed: {type(exc).__name__}: {exc}")
        finally:
            if session is not None:
                try:
                    session.stop()
                except Exception:
                    pass
