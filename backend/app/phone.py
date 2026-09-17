"""Mobile numbers are the primary identity, so normalisation has to be exact
and total: two spellings of the same number must always collapse to the same
string, or one person ends up with two accounts.

Stored form is E.164: a leading '+', country code, subscriber number, digits
only. A bare 10-digit number is assumed to be in DEFAULT_COUNTRY_CODE.

For strict per-country length and prefix rules, swap this for the
`phonenumbers` package; the interface is the same two functions.
"""
import re

_NON_DIGIT = re.compile(r"[^\d+]")
_E164 = re.compile(r"^\+[1-9]\d{7,14}$")


class InvalidPhoneNumber(ValueError):
    pass


def normalise(raw: str, default_country_code: str = "+91") -> str:
    """Return the E.164 form, or raise InvalidPhoneNumber."""
    if raw is None:
        raise InvalidPhoneNumber("A mobile number is required.")

    if not str(raw).strip():
        raise InvalidPhoneNumber("A mobile number is required.")

    s = _NON_DIGIT.sub("", str(raw).strip())
    if not s:
        # They typed something, it just had no digits in it. Saying "required"
        # here would send them looking for an empty box.
        raise InvalidPhoneNumber("That mobile number isn't in a format we recognise.")

    # '+' is only meaningful as the first character
    if s.count("+") > 1 or ("+" in s and not s.startswith("+")):
        raise InvalidPhoneNumber("That mobile number isn't in a format we recognise.")

    if s.startswith("00"):          # international prefix used in much of the world
        s = "+" + s[2:]

    if not s.startswith("+"):
        cc = _NON_DIGIT.sub("", default_country_code)
        if not cc.startswith("+"):
            cc = "+" + cc.lstrip("+")
        digits = s
        # A national trunk '0' is dropped before the country code is applied.
        digits = digits.lstrip("0")
        if not digits:
            raise InvalidPhoneNumber("That mobile number isn't in a format we recognise.")
        s = cc + digits

    if not _E164.match(s):
        raise InvalidPhoneNumber("That mobile number isn't in a format we recognise.")
    return s


def mask(e164: str) -> str:
    """A form safe to show back to someone: +91 XXXXX X3210."""
    if not e164 or len(e164) < 5:
        return "•••••"
    return e164[:3] + " " + "X" * (len(e164) - 7) + " " + e164[-4:]
