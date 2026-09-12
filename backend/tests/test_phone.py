import pytest

from app.phone import InvalidPhoneNumber, mask, normalise


@pytest.mark.parametrize("raw,expected", [
    ("9876543210", "+919876543210"),            # bare Indian mobile
    ("09876543210", "+919876543210"),           # national trunk zero
    ("+91 98765 43210", "+919876543210"),       # spaced
    ("+91-98765-43210", "+919876543210"),       # dashed
    ("(+91) 98765 43210", "+919876543210"),     # bracketed
    ("0091 98765 43210", "+919876543210"),      # 00 international prefix
    ("+919876543210", "+919876543210"),         # already E.164
    ("  9876543210  ", "+919876543210"),        # padded
    ("+14155552671", "+14155552671"),           # another country, untouched
    ("+442071838750", "+442071838750"),
])
def test_every_spelling_collapses_to_one(raw, expected):
    assert normalise(raw, "+91") == expected


def test_same_number_never_makes_two_accounts():
    spellings = ["9876543210", "09876543210", "+91 98765 43210",
                 "0091-98765-43210", "+919876543210"]
    assert len({normalise(s, "+91") for s in spellings}) == 1


@pytest.mark.parametrize("raw", [
    "", "   ", "abcdefghij", "+", "++919876543210", "12", "+0123456789",
    "9876543210+91", None,
])
def test_rubbish_is_rejected(raw):
    with pytest.raises(InvalidPhoneNumber):
        normalise(raw, "+91")


def test_default_country_is_configurable():
    assert normalise("4155552671", "+1") == "+14155552671"


def test_mask_hides_the_middle():
    m = mask("+919876543210")
    assert m.endswith("3210") and "98765" not in m
