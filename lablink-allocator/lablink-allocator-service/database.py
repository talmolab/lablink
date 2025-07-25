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

    def get_row_count(self) -> int:
        """Get the number of rows in the table.
        Returns:
            int: The number of rows in the table.
        """
        self.cursor.execute(f"SELECT COUNT(*) FROM {self.table_name};")
        return self.cursor.fetchone()[0]

    def get_column_names(self, table_name=None) -> list:
        """Get the column names of a table.

        Args:
            table_name (str): The name of the table.

        Returns:
            list: A list of column names.
        """
        if table_name is None:
            table_name = self.table_name

        # Query to get the column names from the information schema
        with self.conn.cursor() as cursor:
            cursor.execute(
                f"SELECT column_name FROM information_schema.columns WHERE table_name = '{table_name}'"
            )
            return [row[0] for row in cursor.fetchall()]

    def insert_vm(self, hostname) -> None:
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

    def listen_for_notifications(self, channel, target_hostname) -> dict:
        """Listen for notifications on a specific channel.

        Args:
            channel (str): The name of the notification channel.
            target_hostname (str): The hostname of the VM to connect to.

        Returns:
            dict: A dictionary containing the status, pin, and command if the connection is successful.

        Raises:
            psycopg2.Error: If there is an error connecting to the database or listening for notifications.
            json.JSONDecodeError: If there is an error decoding the JSON payload from the notification.
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

    def get_crd_command(self, hostname) -> str:
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

    def get_unassigned_vms(self) -> list:
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

    def vm_exists(self, hostname) -> bool:
        """Check if a VM with the given hostname exists in the table.

        Args:
            hostname (str): The hostname of the VM.

        Returns:
            bool: True if the VM exists, False otherwise.
        """
        query = f"SELECT EXISTS (SELECT 1 FROM {self.table_name} WHERE hostname = %s)"
        self.cursor.execute(query, (hostname,))
        return self.cursor.fetchone()[0]

    def get_assigned_vms(self) -> list:
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
            list: A list containing the hostname, pin, and CRD command of the VM assigned to the user.
        """
        query = f"SELECT * FROM {self.table_name} WHERE useremail = %s"
        self.cursor.execute(query, (email,))
        row = self.cursor.fetchone()
        if row:
            hostname, pin, crdcommand, _, _, _ = row
            return [
                hostname,
                pin,
                crdcommand,
            ]
        else:
            raise ValueError(f"No VM found for email in the database: {email}")

    def assign_vm(self, email, crd_command, pin) -> None:
        """Assign a VM to a user.

        Args:
            hostname (str): The hostname of the VM.
            email (str): The email of the user.
            crd_command (str): The CRD command to assign.
            pin (str): The PIN for the VM.
        """
        # Gets the first available VM that is not in use
        hostname = self.get_first_available_vm()

        # Check if a VM is available
        if not hostname:
            logger.error("No available VMs found to assign.")
            raise ValueError("No available VMs to assign.")

        # SQL query to update the VM record with the user's email, CRD command, and pin
        query = f"""
        UPDATE {self.table_name}
        SET useremail = %s, crdcommand = %s, pin = %s, inuse = FALSE, healthy = NULL
        WHERE hostname = %s;
        """
        try:
            self.cursor.execute(query, (email, crd_command, pin, hostname))
            self.conn.commit()
            logger.debug(f"Assigned VM '{hostname}' to user '{email}'.")
        except Exception as e:
            logger.error(f"Error assigning VM: {e}")
            self.conn.rollback()

    def get_first_available_vm(self) -> str:
        """Get the first available VM that is not assigned.

        Returns:
            str: The hostname of the first available VM.
        """
        query = (
            f"SELECT hostname FROM {self.table_name} WHERE useremail IS NULL LIMIT 1"
        )
        self.cursor.execute(query)
        row = self.cursor.fetchone()
        return row[0] if row else None

    def update_vm_in_use(self, hostname: str, in_use: bool) -> None:
        """Update the in-use status of a VM.

        Args:
            hostname (str): The hostname of the VM.
            in_use (bool): The in-use status to set.
        """
        query = f"UPDATE {self.table_name} SET inuse = %s WHERE hostname = %s"
        try:
            self.cursor.execute(query, (in_use, hostname))
            self.conn.commit()
            logger.debug(f"Updated VM '{hostname}' in-use status to {in_use}.")
        except Exception as e:
            logger.error(f"Error updating VM in-use status: {e}")
            self.conn.rollback()

    def clear_database(self) -> None:
        """Delete all VMs from the table."""
        query = f"DELETE FROM {self.table_name};"
        try:
            self.cursor.execute(query)
            self.conn.commit()
            logger.debug("All VMs deleted from the table.")
        except Exception as e:
            logger.error(f"Error deleting VMs: {e}")
            self.conn.rollback()

    def update_health(self, hostname: str, healthy: str) -> None:
        """Modify the health status of a VM.

        Args:
            hostname (str): The hostname of the VM.
            healthy (str): The health status to set for the VM.
        """
        query = f"UPDATE {self.table_name} SET healthy = %s WHERE hostname = %s;"
        try:
            self.cursor.execute(query, (healthy, hostname))
            self.conn.commit()
            logger.debug(f"Updated health status for VM '{hostname}' to {healthy}.")
        except Exception as e:
            logger.error(f"Error updating health status: {e}")
            self.conn.rollback()

    def get_gpu_health(self, hostname: str) -> str:
        """Get the GPU health status of a VM.

        Args:
            hostname (str): The hostname of the VM.

        Returns:
            str: The health status of the GPU for the specified VM, or None if not found.
        """
        query = f"SELECT healthy FROM {self.table_name} WHERE hostname = %s;"
        try:
            self.cursor.execute(query, (hostname,))
            result = self.cursor.fetchone()
            if result:
                return result[0]
            else:
                logger.error(f"No VM found with hostname '{hostname}'.")
                return None
        except Exception as e:
            logger.error(f"Error retrieving GPU health: {e}")
            return None

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
