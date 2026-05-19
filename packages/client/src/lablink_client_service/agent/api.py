"""Client agent HTTP server.

Listens on :7070 inside the container. The allocator calls
POST /api/session/start with a fresh KasmVNC password before
handing the seat to a student; the agent rewrites the local
`kasmvncpasswd` file. KasmVNC re-reads that file on each HTTP
Basic Auth check, so no signal-based reload is needed (and SIGHUP
would in fact terminate Xvnc — its reset path is unsupported).

Auth: Bearer = deployment-wide agent-control token AGENT_TOKEN (same
value the allocator generates at startup and bakes into the client
VM's docker env via Terraform). Any caller who knows the token
can rotate the password; that's adequate because the token is only
ever set on the client VM by Terraform and only ever sent by the
allocator. /healthz is unauthenticated for ALB / Docker healthchecks.
"""
import logging
import os

from flask import Flask, request, jsonify

from lablink_client_service.agent.kasmvnc import rotate_kasmvnc_password


logger = logging.getLogger(__name__)


def create_app() -> Flask:
    app = Flask(__name__)
    expected = os.environ.get("AGENT_TOKEN", "")

    @app.post("/api/session/start")
    def session_start():
        # Constant-time-ish check: short-circuit on the prefix to keep
        # the path uniform-ish for malformed headers, then compare the
        # token. We don't bother with hmac.compare_digest because the
        # token's already randomly generated and the agent is one-call-
        # per-seat — timing-channel risk is negligible.
        auth = request.headers.get("Authorization", "")
        if not expected:
            logger.error("AGENT_TOKEN env var is not set; rejecting all calls")
            return jsonify(error="server misconfigured"), 500
        if not auth.startswith("Bearer ") or auth[7:] != expected:
            return jsonify(error="unauthorized"), 401

        body = request.get_json(silent=True) or {}
        password = body.get("password")
        if not password:
            return jsonify(error="password required"), 400

        try:
            rotate_kasmvnc_password(password=password)
        except Exception as exc:
            logger.exception("KasmVNC password rotation failed")
            return jsonify(error=f"rotation failed: {exc}"), 500
        return jsonify(ok=True), 200

    @app.get("/healthz")
    def healthz():
        return "ok", 200

    return app


def main():
    create_app().run(host="0.0.0.0", port=7070)


if __name__ == "__main__":
    main()
