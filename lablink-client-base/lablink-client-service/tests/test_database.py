"""Module that tests the database functionalities."""

import pytest
from lablink_client_service.database import PostgresqlDatabase
from unittest import mock


# Fixture to mock the database connection
@pytest.fixture
def mock_db_connection():
    with mock.patch("lablink_client_service.database.psycopg2.connect") as mock_connect:
        mock_conn = mock.MagicMock()
        mock_cursor = mock.MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.cursor.return_value = mock_cursor
        yield mock_connect, mock_conn, mock_cursor


def test_init_database(mock_db_connection):
    mock_connect, mock_conn, mock_cursor = mock_db_connection

    # Instantiate the PostgresqlDatabase class
    db = PostgresqlDatabase(
        dbname="test_db",
        user="test_user",
        password="test_pass",
        host="localhost",
        port=5432,
        table_name="test_table",
    )

    mock_connect.assert_called_once_with(
        dbname="test_db",
        user="test_user",
        password="test_pass",
        host="localhost",
        port=5432,
    )

    # Check if the connection was established
    assert db.conn == mock_conn
    assert db.cursor == mock_cursor


def test_get_column_names(mock_db_connection):
    _, _, mock_cursor = mock_db_connection
    mock_cursor.fetchall.return_value = [
        ("hostname",),
        ("pin",),
        ("crdcommand",),
        ("useremail",),
        ("inuse",),
    ]

    db = PostgresqlDatabase(
        dbname="test_db",
        user="test_user",
        password="test_pass",
        host="localhost",
        port=5432,
        table_name="test_table",
    )
    result = db.get_column_names()

    mock_cursor.execute.assert_called_once()
    assert result == ["hostname", "pin", "crdcommand", "useremail", "inuse"]
    assert len(result) == 5


def test_insert_vm(mock_db_connection):
    _, _, mock_cursor = mock_db_connection

    # For extracting column names
    mock_cursor.fetchall.return_value = [
        ("hostname",),
        ("pin",),
        ("crdcommand",),
        ("useremail",),
        ("inuse",),
    ]

    db = PostgresqlDatabase(
        dbname="test_db",
        user="test_user",
        password="test_pass",
        host="localhost",
        port=5432,
        table_name="test_table",
    )

    db.insert_vm("test-hostname")

    expected_values = ["test-hostname", None, None, None, False]

    print(f"Expected values: {expected_values}")
    # Check if the cursor.execute was called with the expected SQL command
    mock_cursor.execute.assert_called_with(
        "INSERT INTO test_table (hostname, pin, crdcommand, useremail, inuse) VALUES (%s, %s, %s, %s, %s);",
        expected_values,
    )

    # Check that values were inserted correctly
    insert_calls = [
        call
        for call in mock_cursor.execute.call_args_list
        if len(call.args) > 1 and call.args[1] == expected_values
    ]

    assert mock_cursor.execute.call_count == 2  # column fetch + insert
    assert len(insert_calls) == 1


def test_get_crd_command(mock_db_connection):
    _, _, mock_cursor = mock_db_connection
    mock_cursor.fetchone.return_value = ["sample_crd_command"]

    db = PostgresqlDatabase(
        dbname="test_db",
        user="test_user",
        password="test_pass",
        host="localhost",
        port=5432,
        table_name="test_table",
    )
    result = db.get_crd_command("host1")

    # Check if the cursor.execute was called with the expected SQL command
    mock_cursor.execute.assert_called_with(
        "SELECT crdcommand FROM test_table WHERE hostname = %s", ("host1",)
    )
    assert result == "sample_crd_command"


def test_get_crd_command_no_result(mock_db_connection):
    _, _, mock_cursor = mock_db_connection

    db = PostgresqlDatabase(
        dbname="test_db",
        user="test_user",
        password="test_pass",
        host="localhost",
        port=5432,
        table_name="test_table",
    )

    with mock.patch.object(db, "vm_exists", return_value=False):
        result = db.get_crd_command("nonexistent-vm")

    assert result is None
    mock_cursor.execute.assert_not_called()


def test_get_assigned_vms(mock_db_connection):
    _, _, mock_cursor = mock_db_connection
    mock_cursor.fetchall.return_value = [("vm01",), ("vm03",)]

    db = PostgresqlDatabase(
        dbname="test_db",
        user="test_user",
        password="test_pass",
        host="localhost",
        port=5432,
        table_name="test_table",
    )

    result = db.get_assigned_vms()

    # Check if the cursor.execute was called with the expected SQL command
    mock_cursor.execute.assert_called_with(
        "SELECT hostname FROM test_table WHERE crdcommand IS NOT NULL"
    )
    assert result == ["vm01", "vm03"]


def test_get_unassigned_vms(mock_db_connection):
    _, _, mock_cursor = mock_db_connection
    mock_cursor.fetchall.return_value = [("vm02",), ("vm04",)]
    mock_cursor.execute.return_value = None
    db = PostgresqlDatabase(
        dbname="test_db",
        user="test_user",
        password="test_pass",
        host="localhost",
        port=5432,
        table_name="test_table",
    )
    result = db.get_unassigned_vms()

    # Check if the cursor.execute was called with the expected SQL command
    mock_cursor.execute.assert_called_with(
        "SELECT hostname FROM test_table WHERE crdcommand IS NULL"
    )
    assert result == ["vm02", "vm04"]


def test_vm_exists(mock_db_connection):
    _, _, mock_cursor = mock_db_connection
    mock_cursor.fetchone.return_value = [True]

    db = PostgresqlDatabase(
        dbname="test_db",
        user="test_user",
        password="test_pass",
        host="localhost",
        port=5432,
        table_name="test_table",
    )

    result = db.vm_exists("existing-vm")

    # Check if the cursor.execute was called with the expected SQL command
    mock_cursor.execute.assert_called_with(
        "SELECT EXISTS (SELECT 1 FROM test_table WHERE hostname = %s)", ("existing-vm",)
    )
    assert result is True
