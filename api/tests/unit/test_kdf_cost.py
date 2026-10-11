"""The production key-stretching cost is unchanged (T-08-26).

conftest lowers bcrypt and Argon2id costs for speed; this pins what the app
itself ships with, read before conftest swaps them.
"""
from tests.conftest import PRODUCTION_KDF


def test_argon2id_production_parameters():
    assert PRODUCTION_KDF["argon2"] == (3, 64 * 1024, 1)  # time, memory (KiB), parallelism


def test_bcrypt_production_rounds():
    context = PRODUCTION_KDF["pwd_context"]
    assert context.schemes() == ("bcrypt",)
    assert context.handler("bcrypt").default_rounds == 12


def test_tests_really_use_the_cheaper_cost():
    from app.core import security, user_crypto

    assert user_crypto._ARGON2_MEMORY_COST < PRODUCTION_KDF["argon2"][1]
    assert security.pwd_context.hash("x").startswith("$2b$04$")
