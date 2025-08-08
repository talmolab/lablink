from unittest.mock import patch
import base64


def get_basic_auth_header(username, password):
    auth_str = f"{username}:{password}"
    b64_auth = base64.b64encode(auth_str.encode("utf-8")).decode("utf-8")
    return {"Authorization": f"Basic {b64_auth}"}


def test_home(client):
    """Test the home endpoint."""
    response = client.get("/")
    assert response.status_code == 200


def test_admin_auth_without_auth(client):
    """Test the admin authentication endpoint without auth."""
    response = client.get("/admin")
    assert response.status_code == 401
    assert response.data.decode("utf-8") == "Unauthorized Access"


def test_admin_auth_with_invalid_auth(client):
    """Test the admin authentication endpoint with invalid auth."""
    response = client.get("/admin", headers={"Authorization": "Bearer invalid_token"})
    assert response.status_code == 401
    assert response.data.decode("utf-8") == "Unauthorized Access"
