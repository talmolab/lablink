import psycopg2
import select
from database import PostgresqlDtabase


def main():
    # Connect to the PostgreSQL database
    database = PostgresqlDtabase(
        dbname="lablink--test",
        user="postgres",
        password="031011",
        host="localhost",
        port=5432,
        table_name="lablink_client_test",
    )

    # Get the column names from the database
    column_names = database.get_column_names()
    print("Column names:", column_names)

    # Insert a new VM into the database
    database.insert_vm("vm-test-2")

    # Listen for notifications on the specified channel
    channel = "message_channel"
    database.listen_for_notifications(channel)


if __name__ == "__main__":
    main()
else:
    print("This script is not intended to be imported as a module.")
    exit(1)
