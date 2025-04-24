import select
from lablink_client_service import connect_crd
import json
import socket

try:
    import psycopg2
except ImportError as e:
    print(
        "psycopg2 is not installed in the development environment. "
        "Please install it using `pip install psycopg2`"
    )
    raise e


class PostgresqlDatabase:
    """Class to interact with a PostgreSQL database.
    This class provides methods to connect to the database, insert data,
    retrieve data, and listen for notifications.
    """

    def __init__(
        self,
        dbname: str,
        user: str,
        password: str,
        host: str,
        port: int,
        table_name: str,
    ):
        """Initialize the database connection.

        Args:
            dbname (str): The name of the database.
            user (str): The username to connect to the database.
            password (str): The password for the user.
            host (str): The host where the database is located.
            port (int): The port number for the database connection.
            table_name (str): The name of the table to interact with.
        """
        self.dbname = dbname
        self.user = user
        self.password = password
        self.host = host
        self.port = port
        self.table_name = table_name

        # Connect to the PostgreSQL database
        self.conn = psycopg2.connect(
            dbname=dbname,
            user=user,
            password=password,
            host=host,
            port=port,
        )

        # Set the isolation level to autocommit so that each SQL command is immediately executed
        self.conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
        self.cursor = self.conn.cursor()

    def get_column_names(self, table_name=None):
        """Get the column names of a table.

        Args:
            table_name (str): The name of the table.

        Returns:
            list: A list of column names.
        """
        if table_name is None:
            table_name = self.table_name

        # Query to get the column names from the information schema
        self.cursor.execute(
            f"SELECT column_name FROM information_schema.columns WHERE table_name = '{table_name}'"
        )
        return [row[0] for row in self.cursor.fetchall()]

    def insert_vm(self, hostname):
        """Insert a new row into the table.

        Args:
            hostname (str): The hostname of the VM.
        """
        column_names = self.get_column_names()

        values = []

        for col in column_names:
            # Find the column that corresponds to the hostname and set its value
            if col == "hostname":
                values.append(hostname)
            elif col == "inuse":
                values.append(False)
            else:
                values.append(None)

        # Construct the SQL query
        columns = ", ".join(column_names)
        placeholders = ", ".join(["%s" for _ in column_names])

        sql = f"INSERT INTO {self.table_name} ({columns}) VALUES ({placeholders});"
        self.cursor.execute(sql, values)
        self.conn.commit()
        print(f"Inserted data: {values}")

    def listen_for_notifications(self, channel):
        """Listen for notifications on a specific channel.

        Args:
            channel (str): The name of the notification channel.
        """
        self.cursor.execute(f"LISTEN {channel};")
        print(f"Listening for notifications on '{channel}'...")

        # Infinite loop to wait for notifications
        try:
            while True:
                # Wait for notifications
                if select.select([self.conn], [], [], 10) == ([], [], []):
                    continue
                else:
                    self.conn.poll()  # Process any pending notifications
                    while self.conn.notifies:
                        notify = self.conn.notifies.pop(0)
                        print(
                            f"Received notification: {notify.payload} from channel {notify.channel}"
                        )
                        # Parse the JSON payload
                        try:
                            payload_data = json.loads(notify.payload)
                            print(f"Payload data: {payload_data}")
                            hostname = payload_data.get("HostName")
                            pin = payload_data.get("Pin")
                            command = payload_data.get("CrdCommand")

                            if hostname is None or pin is None or command is None:
                                print("Invalid payload data. Missing required fields.")
                                continue

                            # Check if the hostname matches the current hostname
                            current_hostname = socket.gethostname()
                            if hostname != current_hostname:
                                print(
                                    f"Hostname '{hostname}' does not match the current hostname '{current_hostname}'."
                                )
                                continue

                            connect_crd.connect_to_crd(
                                pin=pin,
                                command=command,
                            )

                        except json.JSONDecodeError as e:
                            print(f"Error decoding JSON payload: {e}")
                            continue
                        except Exception as e:
                            print(f"Error processing notification: {e}")
                            continue
        except KeyboardInterrupt:
            print("Exiting...")
        finally:
            self.cursor.close()
            self.conn.close()

    def get_crd_command(self, hostname):
        """Get the command assigned to a VM.

        Args:
            hostname (str): The hostname of the VM.

        Returns:
            str: The command assigned to the VM.
        """
        if not self.vm_exists(hostname):
            print(f"VM with hostname '{hostname}' does not exist.")
            return None

        query = f"SELECT crdcommand FROM {self.table_name} WHERE hostname = %s"
        self.cursor.execute(query, (hostname,))
        return self.cursor.fetchone()[0]

    def get_unassigned_vms(self):
        """Get the VMs that are not assigned to any command.

        Returns:
            list: A list of VMs that are not assigned to any command.
        """
        query = f"SELECT hostname FROM {self.table_name} WHERE crdcommand IS NULL"
        try:
            self.cursor.execute(query)
            return [row[0] for row in self.cursor.fetchall()]
        except Exception as e:
            print(f"Error retrieving unassigned VMs: {e}")
            return []

    def vm_exists(self, hostname):
        """Check if a VM with the given hostname exists in the table.

        Args:
            hostname (str): The hostname of the VM.

        Returns:
            bool: True if the VM exists, False otherwise.
        """
        query = f"SELECT EXISTS (SELECT 1 FROM {self.table_name} WHERE hostname = %s)"
        self.cursor.execute(query, (hostname,))
        return self.cursor.fetchone()[0]

    def get_assigned_vms(self):
        """Get the VMs that are assigned to a command.

        Returns:
            list: A list of VMs that are assigned to a command.
        """
        query = f"SELECT hostname FROM {self.table_name} WHERE crdcommand IS NOT NULL"
        try:
            self.cursor.execute(query)
            return [row[0] for row in self.cursor.fetchall()]
        except Exception as e:
            print(f"Error retrieving assigned VMs: {e}")

    @classmethod
    def load_database(cls, dbname, user, password, host, port, table_name):
        """Loads an existing database from PostgreSQL.

        Args:
            dbname (str): The name of the database.
            user (str): The username to connect to the database.
            password (str): The password for the user.
            host (str): The host where the database is located.
            port (int): The port number for the database connection.
            table_name (str): The name of the table to interact with.

        Returns:
            PostgresqlDtabase: An instance of the PostgresqlDtabase class.
        """
        return cls(dbname, user, password, host, port, table_name)

    def __del__(self):
        """Close the database connection when the object is deleted."""
        self.cursor.close()
        self.conn.close()
        print("Database connection closed.")
