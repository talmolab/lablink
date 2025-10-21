from unittest.mock import patch
import base64
import os

AWS_CREDENTIALS_ENDPOINT = "/api/admin/set-aws-credentials"


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


def test_admin_auth_with_valid_auth(client, admin_headers):
    """Test the admin authentication endpoint with valid auth."""
    response = client.get("/admin", headers=admin_headers)
    assert response.status_code == 200


def test_set_aws_credentials_empty_field(client, admin_headers):
    """Test setting AWS credentials with empty fields."""
    response = client.post(
        AWS_CREDENTIALS_ENDPOINT,
        headers=admin_headers,
        json={"aws_access_key_id": "", "aws_secret_access_key": ""},
    )
    assert response.status_code == 400
    assert response.is_json
    assert response.json == {"error": "AWS Access Key and Secret Key are required"}


@patch(
    "lablink_allocator_service.main.validate_aws_credentials",
    return_value={"valid": True},
)
def test_admin_set_aws_credentials_success_long_lasting(
    mock_validate, client, admin_headers, monkeypatch
):
    """Test setting AWS credentials as an admin."""
    # Check env variables are clear
    for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        monkeypatch.delenv(k, raising=False)

    response = client.post(
        AWS_CREDENTIALS_ENDPOINT,
        headers=admin_headers,
        data={
            "aws_access_key_id": "test_access_key",
            "aws_secret_access_key": "test_secret_key",
            "aws_token": "",
        },
    )
    mock_validate.assert_called_once()
    assert response.status_code == 200

    # env vars should be set on success
    assert os.environ.get("AWS_ACCESS_KEY_ID") == "test_access_key"
    assert os.environ.get("AWS_SECRET_ACCESS_KEY") == "test_secret_key"
    assert os.environ.get("AWS_SESSION_TOKEN") == ""


@patch(
    "lablink_allocator_service.main.validate_aws_credentials",
    return_value={"valid": True},
)
def test_admin_set_aws_credentials_success_long_lasting_error(
    mock_validate, client, admin_headers, monkeypatch
):
    """Test setting AWS credentials as an admin."""
    # Check env variables are clear
    for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        monkeypatch.delenv(k, raising=False)

    response = client.post(
        AWS_CREDENTIALS_ENDPOINT,
        headers=admin_headers,
        data={
            "aws_access_key_id": "test_access_key",
            "aws_secret_access_key": "test_secret_key",
            "aws_token": "test_session_token",
        },
    )
    mock_validate.assert_called_once()
    assert response.status_code == 200

    # env vars should be set on success
    assert os.environ.get("AWS_ACCESS_KEY_ID") == "test_access_key"
    assert os.environ.get("AWS_SECRET_ACCESS_KEY") == "test_secret_key"
    assert os.environ.get("AWS_SESSION_TOKEN") == "test_session_token"


@patch(
    "lablink_allocator_service.main.validate_aws_credentials",
    return_value={"valid": False, "message": "Invalid AWS credentials"},
)
def test_admin_set_aws_credentials_failure_invalid_credentials(
    mock_validate, client, admin_headers, monkeypatch, caplog
):
    """Test setting AWS credentials as an admin."""

    # Check env variables are clear
    for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        monkeypatch.delenv(k, raising=False)

    with caplog.at_level("ERROR"):
        client.post(
            AWS_CREDENTIALS_ENDPOINT,
            headers=admin_headers,
            data={
                "aws_access_key_id": "test_access_key",
                "aws_secret_access_key": "test_secret_key",
                "aws_token": "test_session_token",
            },
        )
    mock_validate.assert_called_once()

    # Check logs for error messages
    assert "Invalid AWS credentials" in caplog.text

    # env vars should be set on success
    assert os.environ.get("AWS_ACCESS_KEY_ID") is None
    assert os.environ.get("AWS_SECRET_ACCESS_KEY") is None
    assert os.environ.get("AWS_SESSION_TOKEN") is None


@patch(
    "lablink_allocator_service.main.validate_aws_credentials",
    return_value={
        "valid": False,
        "message": "AWS credentials are temporary but no session token provided.",
    },
)
def test_admin_set_aws_credentials_failure_no_token(
    mock_validate, client, admin_headers, monkeypatch, caplog
):
    """Test setting AWS credentials as an admin."""

    # Check env variables are clear
    for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        monkeypatch.delenv(k, raising=False)

    with caplog.at_level("ERROR"):
        client.post(
            AWS_CREDENTIALS_ENDPOINT,
            headers=admin_headers,
            data={
                "aws_access_key_id": "test_access_key",
                "aws_secret_access_key": "test_secret_key",
                "aws_token": "",
            },
        )
    mock_validate.assert_called_once()

    # Check logs for error messages
    assert "Invalid AWS credentials" in caplog.text

    # env vars should be set on success
    assert os.environ.get("AWS_ACCESS_KEY_ID") is None
    assert os.environ.get("AWS_SECRET_ACCESS_KEY") is None


def test_admin_unset_aws_credentials(client, admin_headers, monkeypatch):
    """Test unsetting AWS credentials as an admin."""
    # Set env variables
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test_access_key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test_secret_key")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "test_session_token")

    client.post(
        "/api/admin/unset-aws-credentials",
        headers=admin_headers,
    )

    # env vars should be unset
    assert os.environ.get("AWS_ACCESS_KEY_ID") is None
    assert os.environ.get("AWS_SECRET_ACCESS_KEY") is None
    assert os.environ.get("AWS_SESSION_TOKEN") is None
