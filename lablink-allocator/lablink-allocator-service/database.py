import select
import json
import logging
import psycopg2

# Set up logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

try:
    import psycopg2
except ImportError as e:
    logger.error(
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

        try:
            sql = f"INSERT INTO {self.table_name} ({columns}) VALUES ({placeholders});"
            self.cursor.execute(sql, values)
            self.conn.commit()
            logger.debug(f"Inserted data: {values}")
        except Exception as e:
            logger.error(f"Error inserting data: {e}")
            self.conn.rollback()

    def listen_for_notifications(self, channel, target_hostname):
        """Listen for notifications on a specific channel.

        Args:
            channel (str): The name of the notification channel.
            target_hostname (str): The hostname of the VM to connect to.
        """

        # Create a new connection to listen for notifications in order to avoid blocking the main connection
        logger.debug(f"Creating new connection to listen for notifications...")
        listen_conn = psycopg2.connect(
            dbname=self.dbname,
            user=self.user,
            password=self.password,
            host=self.host,
            port=self.port,
        )
        listen_conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
        listen_cursor = listen_conn.cursor()

        # Infinite loop to wait for notifications
        try:
            listen_cursor.execute(f"LISTEN {channel};")
            logger.debug(f"Listening for notifications on '{channel}'...")

            while True:
                # Wait for notifications
                if select.select([listen_conn], [], [], 10) == ([], [], []):
                    continue
                else:
                    listen_conn.poll()  # Process any pending notifications
                    while listen_conn.notifies:
                        notify = listen_conn.notifies.pop(0)
                        logger.debug(
                            f"Received notification: {notify.payload} from channel {notify.channel}"
                        )
                        # Parse the JSON payload
                        try:
                            payload_data = json.loads(notify.payload)
                            logger.debug(f"Payload data: {payload_data}")
                            hostname = payload_data.get("HostName")
                            pin = payload_data.get("Pin")
                            command = payload_data.get("CrdCommand")

                            if hostname is None or pin is None or command is None:
                                logger.error(
                                    "Invalid payload data. Missing required fields."
                                )
                                continue

                            # Check if the hostname matches the current hostname
                            if hostname != target_hostname:
                                logger.debug(
                                    f"Hostname '{hostname}' does not match the current hostname '{target_hostname}'."
                                )
                                continue

                            logger.debug(
                                "Chrome Remote Desktop connected successfully. Exiting listener loop."
                            )
                            return {
                                "status": "success",
                                "pin": pin,
                                "command": command,
                            }

                        except json.JSONDecodeError as e:
                            logger.error(f"Error decoding JSON payload: {e}")
                            continue
                        except Exception as e:
                            logger.error(f"Error processing notification: {e}")
                            continue
        finally:
            # Close the listener connection
            listen_cursor.close()
            listen_conn.close()
            logger.debug("Listener connection closed.")

    def get_crd_command(self, hostname):
        """Get the command assigned to a VM.

        Args:
            hostname (str): The hostname of the VM.

        Returns:
            str: The command assigned to the VM.
        """
        if not self.vm_exists(hostname):
            logger.error(f"VM with hostname '{hostname}' does not exist.")
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
            logger.error(f"Error retrieving unassigned VMs: {e}")
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
            logger.error(f"Error retrieving assigned VMs: {e}")

    def get_vm_details(self, email: str) -> list:
        """Get VM details based on the email provided.

        Args:
            email (str): The email of the user.

        Returns:
            dict: A dictionary containing VM details.
        """
        query = f"SELECT * FROM {self.table_name} WHERE useremail = %s"
        self.cursor.execute(query, (email,))
        row = self.cursor.fetchone()
        if row:
            hostname, pin, crdcommand, _, _ = row
            return [
                hostname,
                pin,
                crdcommand,
            ]
        else:
            raise ValueError(f"No VM found for email in the database: {email}")

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
        logger.debug("Database connection closed.")
