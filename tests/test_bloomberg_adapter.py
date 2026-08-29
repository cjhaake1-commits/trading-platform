from __future__ import annotations

from types import SimpleNamespace

from autotrader.adapters.bloomberg import BloombergAdapter, BloombergConfig


class FakeSessionOptions:
    AUTO = 0
    DAPI = 1
    SAPI = 2

    def __init__(self) -> None:
        self.host = None
        self.port = None
        self.timeout = None
        self.client_mode = None
        self.auto_restart = None
        self.receive_times = None
        self.auth = None
        self.identity = None

    def setServerHost(self, value):
        self.host = value

    def setServerPort(self, value):
        self.port = value

    def setConnectTimeout(self, value):
        self.timeout = value

    def setClientMode(self, value):
        self.client_mode = value

    def setAutoRestartOnDisconnection(self, value):
        self.auto_restart = value

    def setRecordSubscriptionDataReceiveTimes(self, value):
        self.receive_times = value

    def setAuthenticationOptions(self, value):
        self.auth = value

    def setSessionIdentityOptions(self, value):
        self.identity = value


class FakeAuthOptions:
    @classmethod
    def createWithApp(cls, app_name):
        return ("app", app_name)


FAKE_BLPAPI = SimpleNamespace(SessionOptions=FakeSessionOptions, AuthOptions=FakeAuthOptions)


def test_bloomberg_disabled_by_default():
    config = BloombergConfig.from_env({})
    status = BloombergAdapter(config).probe()
    assert status.state == "DISABLED"
    assert status.connected is False
    assert status.research_only is True


def test_enabled_connection_requires_license_acknowledgement():
    config = BloombergConfig.from_env({"BLOOMBERG_ENABLED": "true"})
    assert config.validation_errors(system="Windows") == (
        "Bloomberg access requires an acknowledged, authorized Bloomberg data license",
    )


def test_desktop_api_is_blocked_on_linux():
    config = BloombergConfig.from_env(
        {
            "BLOOMBERG_ENABLED": "true",
            "BLOOMBERG_LICENSE_ACK": "true",
            "BLOOMBERG_MODE": "dapi",
        }
    )
    assert any("Desktop API" in item for item in config.validation_errors(system="Linux"))


def test_builds_read_only_sapi_options():
    config = BloombergConfig.from_env(
        {
            "BLOOMBERG_ENABLED": "true",
            "BLOOMBERG_LICENSE_ACK": "true",
            "BLOOMBERG_MODE": "sapi",
            "BLOOMBERG_HOST": "bloomberg.internal",
            "BLOOMBERG_PORT": "8194",
            "BLOOMBERG_CONNECT_TIMEOUT_MS": "9000",
            "BLOOMBERG_AUTH_OPTIONS": "AuthenticationType=OS_LOGON",
        }
    )
    options = BloombergAdapter(config).build_session_options(FAKE_BLPAPI)
    assert options.host == "bloomberg.internal"
    assert options.port == 8194
    assert options.timeout == 9000
    assert options.client_mode == FakeSessionOptions.SAPI
    assert options.auto_restart is True
    assert options.receive_times is True
    assert options.auth == "AuthenticationType=OS_LOGON"


def test_application_identity_is_configured_without_exposing_it():
    config = BloombergConfig.from_env(
        {
            "BLOOMBERG_ENABLED": "true",
            "BLOOMBERG_LICENSE_ACK": "true",
            "BLOOMBERG_MODE": "sapi",
            "BLOOMBERG_APPLICATION_NAME": "example-app",
        }
    )
    options = BloombergAdapter(config).build_session_options(FAKE_BLPAPI)
    assert options.identity == ("app", "example-app")
    summary = config.public_summary()
    assert summary["application_name_configured"] is True
    assert "application_name" not in summary
    assert "auth_options" not in summary


def test_research_only_cannot_be_disabled():
    config = BloombergConfig.from_env(
        {
            "BLOOMBERG_ENABLED": "true",
            "BLOOMBERG_LICENSE_ACK": "true",
            "BLOOMBERG_RESEARCH_ONLY": "false",
        }
    )
    assert "Bloomberg adapter must remain research-only" in config.validation_errors(system="Windows")
