"""Client agent HTTP server.

Listens on :7070 inside the container. The allocator (and only the
allocator, by SG isolation) calls POST /api/session/start with a
fresh KasmVNC password before handing a seat to a student.

Auth: Bearer = deployment-wide register token (PR A stopgap).
PR C replaces this with a per-client client_secret.
"""
import os

from flask import Flask, request, jsonify

from lablink_client_service.agent.kasmvnc import rotate_kasmvnc_password


def create_app() -> Flask:
    app = Flask(__name__)
    expected = os.environ.get("REGISTER_TOKEN", "")

    @app.post("/api/session/start")
    def session_start():
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer ") or auth[7:] != expected:
            return jsonify(error="unauthorized"), 401
        body = request.get_json(silent=True) or {}
        password = body.get("vnc_password")
        browser_token = body.get("browser_token")
        if not password or not browser_token:
            return (jsonify(error="vnc_password and browser_token required"),
                    400)
        rotate_kasmvnc_password(password=password)
        return jsonify(ok=True), 200

    @app.get("/healthz")
    def healthz():
        return "ok", 200

    return app


def main():
    create_app().run(host="0.0.0.0", port=7070)


if __name__ == "__main__":
    main()
