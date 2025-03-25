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

    # Listen for notifications on the specified channel
    # channel = "message_channel"
    # database.listen_for_notifications(channel)

    # Get the unassigned VMs from the database
    assigned_vms = database.get_assigned_vms()
    print("Assigned VMs:", assigned_vms)

    print("Exist: ", database.vm_exists("vm-test-2"))


if __name__ == "__main__":
    main()
else:
    print("This script is not intended to be imported as a module.")
    exit(1)
