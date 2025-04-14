from lablink_client_service.database import PostgresqlDatabase
import socket


def main():
    # Connect to the PostgreSQL database
    database = PostgresqlDatabase(
        dbname="lablink_db",
        user="lablink",
        password="lablink",
        host="",
        port=5432,
        table_name="vm_requests",
    )

    # Step 1: Add itself to the database
    database.insert_vm(hostname=socket.gethostname())

    # Step 2: Listen to the message and send back if message is received
    # When a message is received, the callback function will be called (connect to CRD)
    channel = "vm_updates"
    database.listen_for_notifications(channel)


if __name__ == "__main__":
    main()
else:
    print("This script is not intended to be imported as a module.")
    exit(1)
