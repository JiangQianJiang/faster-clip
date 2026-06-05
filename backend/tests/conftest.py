import os

# Set a test encryption key for all tests so app.crypto doesn't crash.
# This is a Fernet key — not a real secret, only used in tests.
os.environ.setdefault(
    "API_KEY_ENCRYPTION_KEY",
    "gCW0ZvxPWL4R5PMVxpLNMCNQ2xhT1NWK_vDXI5_OHOk=",
)

# Set test auth token and pytest flag so auth middleware allows requests
os.environ.setdefault("PYTEST_RUNNING", "true")
os.environ.setdefault("ACCESS_TOKEN", "test-token-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
