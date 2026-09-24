"""Hardened application entry point for local and production serving."""
from __future__ import annotations

import os

from security_runtime import bootstrap_environment

bootstrap_environment()

from app import app  # noqa: E402
from integrity_runtime import install as install_integrity  # noqa: E402
from security_runtime import install_security  # noqa: E402

install_security(app)
install_integrity()

if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "5000"))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"

    # Printed before serving, because the commonest way to lose an hour with
    # the phone app is typing 127.0.0.1 into it (which on the phone means the
    # phone) or leaving the server bound to localhost, where nothing outside
    # this computer can reach it. Both look identical from the phone.
    import netinfo  # noqa: E402

    print(netinfo.startup_banner(host, port), flush=True)

    app.run(host=host, port=port, debug=debug)
