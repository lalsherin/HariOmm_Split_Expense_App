"""OTP delivery, behind an interface so the provider is a config change.

Verification is OFF by default (REQUIRE_OTP=false) — the deliberate choice for
this build is sign-in by mobile number and name alone. Everything needed to
turn it on is here: set REQUIRE_OTP=true and point SMS_PROVIDER at a real
provider.

To add one, subclass SmsProvider, implement send(), and register it in
`build_provider`. No other file changes.
"""
import logging
from typing import Protocol

from ..config import Settings

log = logging.getLogger("otp")


class SmsProvider(Protocol):
    def send(self, mobile_number: str, message: str) -> bool:
        ...


class ConsoleProvider:
    """Development delivery: the code goes to the log, not to a phone."""

    def __init__(self, settings: Settings):
        self.settings = settings

    def send(self, mobile_number: str, message: str) -> bool:
        log.warning("SMS (console provider, not delivered) to %s: %s", mobile_number, message)
        return True


class UnconfiguredProvider:
    """Named provider with no credentials — fail loudly rather than silently
    dropping the message."""

    def __init__(self, name: str):
        self.name = name

    def send(self, mobile_number: str, message: str) -> bool:
        raise RuntimeError(
            f"SMS_PROVIDER is '{self.name}' but no working integration is configured. "
            "Set SMS_API_KEY / SMS_API_SECRET and add the provider in otp_service.py."
        )


def build_provider(settings: Settings) -> SmsProvider:
    name = (settings.sms_provider or "console").strip().lower()
    if name in ("", "console", "log", "dev"):
        return ConsoleProvider(settings)
    return UnconfiguredProvider(name)


class OTPService:
    """sendOTP / verifyOTP / resendOTP, as the spec's abstraction layer.

    The database work lives in auth/service.py; this class owns the code
    itself and how it is delivered.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.provider = build_provider(settings)

    def message(self, code: str) -> str:
        return f"{code} is your Split Ledger verification code. It expires in {self.settings.otp_expiry_minutes} minutes."

    def deliver(self, mobile_number: str, code: str) -> bool:
        return self.provider.send(mobile_number, self.message(code))

    @property
    def echo_codes(self) -> bool:
        """With the console provider there is no way for a tester to read the
        code off a phone, so the API returns it. Never true once a real
        provider is configured."""
        return isinstance(self.provider, ConsoleProvider)
