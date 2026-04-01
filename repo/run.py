#!/usr/bin/env python3
"""MeridianCare application entry point."""

import os
import ssl
from app import create_app
from app.utils.certs import generate_self_signed_cert

app = create_app(os.environ.get("FLASK_ENV", "production"))

if __name__ == "__main__":
    cert_dir = os.path.join(os.path.dirname(__file__), "certs")
    cert_path, key_path = generate_self_signed_cert(cert_dir)

    ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ssl_ctx.load_cert_chain(cert_path, key_path)

    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        ssl_context=ssl_ctx,
    )
