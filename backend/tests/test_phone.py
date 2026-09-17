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


# --- deployment: the connection string a managed host actually gives you ----

from app.config import normalise_database_url


def test_neon_style_url_is_translated_for_asyncpg():
    out = normalise_database_url(
        "postgresql://u:p@ep-x.aws.neon.tech/splitledger"
        "?sslmode=require&channel_binding=require"
    )
    assert out == "postgresql+asyncpg://u:p@ep-x.aws.neon.tech/splitledger?ssl=require"


def test_heroku_style_postgres_scheme_is_upgraded():
    assert normalise_database_url("postgres://u:p@host:5432/db") == \
        "postgresql+asyncpg://u:p@host:5432/db"


def test_sslmode_disable_does_not_force_tls():
    assert normalise_database_url("postgresql://u@h/d?sslmode=disable") == \
        "postgresql+asyncpg://u@h/d"


def test_sqlite_and_explicit_drivers_are_left_alone():
    for url in ("sqlite+aiosqlite:///./split_ledger.db",
                "postgresql+asyncpg://u@h/d", ""):
        assert normalise_database_url(url) == url
