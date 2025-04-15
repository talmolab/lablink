from lablink_client_service.database import PostgresqlDatabase
import socket
import os
from dotenv import load_dotenv


def main():
    load_dotenv()

    host = os.getenv("DB_HOST")
    password = os.getenv("DB_PASSWORD")

    if not all([host, password]):
        raise ValueError("Missing required environment variables.")

    # Connect to the PostgreSQL database
    database = PostgresqlDatabase(
        dbname="lablink_db",
        user="lablink",
        password=password,
        host=host,
        port=5432,
        table_name="vm_requests",
    )

    # Insert the hostname to the database
    database.insert_vm(hostname=socket.gethostname())

    # Listen to the message and send back if message is received
    # When a message is received, the callback function will be called (connect to CRD)
    # TODO: Which channel to listen to?
    channel = "vm_updates"
    database.listen_for_notifications(channel)


if __name__ == "__main__":
    main()
else:
    print("This script is not intended to be imported as a module.")
    exit(1)
