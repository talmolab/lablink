from lablink_client_service.database import PostgresqlDatabase


def main():
    # Connect to the PostgreSQL database
    database = PostgresqlDatabase(
        dbname="lablink_db",
        user="lablink",
        password="lablink",
        host="localhost",
        port=5432,
        table_name="vm_requests",
    )

    # Listen for notifications on the specified channel
    channel = "vm_updates"
    database.listen_for_notifications(channel)

    # Get the unassigned VMs from the database
    # assigned_vms = database.get_assigned_vms()
    # print("Assigned VMs:", assigned_vms)

    # print("Exist: ", database.vm_exists("vm-test-2"))

    # # Get the command assigned to a VM
    # crd_command = database.get_crd_command("vm-test-2")
    # print("CRD Command:", crd_command)


if __name__ == "__main__":
    main()
else:
    print("This script is not intended to be imported as a module.")
    exit(1)
