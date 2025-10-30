from datetime import datetime
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
        message_channel: str,
    ):
        """Initialize the database connection.
        Args:
            dbname (str): The name of the database.
            user (str): The username to connect to the database.
            password (str): The password for the user.
            host (str): The host where the database is located.
            port (int): The port number for the database connection.
            table_name (str): The name of the table to interact with.
            message_channel (str): The name of the message channel to listen to.
        """
        self.dbname = dbname
        self.user = user
        self.password = password
        self.host = host
        self.port = port
        self.table_name = table_name
        self.message_channel = message_channel

        # Connect to the PostgreSQL database
        self.conn = psycopg2.connect(
            dbname=dbname,
            user=user,
            password=password,
            host=host,
            port=port,
        )

        # Set the isolation level to autocommit
        self.conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
        self.cursor = self.conn.cursor()

    def get_all_vms(self) -> list:
        """Get all VMs from the table.

        Returns:
            list: A list of all VMs in the table in the form of dictionaries.
        """
        self.cursor.execute(f"SELECT * FROM {self.table_name};")
        rows = self.cursor.fetchall()
        column_names = [desc[0] for desc in self.cursor.description]
        return [dict(zip(column_names, row)) for row in rows]

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
        self.cursor.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = %s",
                (table_name,),
            )
        return [row[0] for row in self.cursor.fetchall()]

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

    def get_vm_by_hostname(self, hostname: str) -> dict:
        """Get a VM by its hostname.

        Args:
            hostname (str): The hostname of the VM.

        Returns:
            dict: A dictionary containing the VM details.
        """
        query = f"SELECT * FROM {self.table_name} WHERE hostname = %s;"
        self.cursor.execute(query, (hostname,))
        row = self.cursor.fetchone()
        if row:
            return {
                "hostname": row[0],
                "pin": row[1],
                "crdcommand": row[2],
                "useremail": row[3],
                "inuse": row[4],
                "healthy": row[5],
                "status": row[6],
                "logs": row[7],
                "terraform_apply_start_time": row[8],
                "terraform_apply_end_time": row[9],
                "terraform_apply_duration_seconds": row[10],
                "cloud_init_start_time": row[11],
                "cloud_init_end_time": row[12],
                "cloud_init_duration_seconds": row[13],
                "container_start_time": row[14],
                "container_end_time": row[15],
                "container_startup_duration_seconds": row[16],
                "total_startup_duration_seconds": row[17],
                "created_at": row[18],
            }
        else:
            logger.error(f"No VM found with hostname '{hostname}'.")
            return None

    def listen_for_notifications(self, channel, target_hostname) -> dict:
        """Listen for notifications on a specific channel.

        Args:
            channel (str): The name of the notification channel.
            target_hostname (str): The hostname of the VM to connect to.

        Returns:
            dict: A dictionary containing the status, pin, and command.

        Raises:
            psycopg2.Error: If there is an error in the database.
            json.JSONDecodeError: If there is an error decoding the JSON payload.
        """

        # Create a new connection to listen for notifications
        logger.debug("Creating new connection to listen for notifications...")
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
                            f"Received notification: {notify.payload} from "
                            f"channel {notify.channel}"
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
                                    f"Hostname '{hostname}' does not match the current"
                                    f"hostname '{target_hostname}'."
                                )
                                continue

                            logger.debug(
                                "Chrome Remote Desktop connected successfully."
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
        query = (
            f"SELECT hostname FROM {self.table_name} WHERE "
            f"crdcommand IS NULL AND status = 'running'"
        )
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
            list: A list containing the hostname, pin, and CRD command of the VM
            assigned to the given user.
        """
        query = f"SELECT * FROM {self.table_name} WHERE useremail = %s"
        self.cursor.execute(query, (email,))
        row = self.cursor.fetchone()
        if row:
            hostname, pin, crdcommand, user_email, inuse, healthy, status, logs = row
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
            f"SELECT hostname FROM {self.table_name} WHERE useremail IS NULL AND "
            f"status = 'running' LIMIT 1"
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
            str: The health status of the GPU for the specified VM or None if not found.
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

    def get_status_by_hostname(self, hostname: str) -> str:
        """Get the status of a VM by its hostname.

        Args:
            hostname (str): The hostname of the VM.

        Returns:
            str: The status of the VM, or None if not found.
        """
        query = f"SELECT status FROM {self.table_name} WHERE hostname = %s;"
        try:
            self.cursor.execute(query, (hostname,))
            result = self.cursor.fetchone()
            if result:
                return result[0]
            else:
                logger.error(f"No VM found with hostname '{hostname}'.")
                return None
        except Exception as e:
            logger.error(f"Error retrieving status: {e}")
            return None

    def get_vm_logs(self, hostname: str) -> str:
        """Get the logs of a VM by its hostname.

        Args:
            hostname (str): The hostname of the VM.

        Returns:
            str: The logs of the VM, or None if not found.
        """
        query = f"SELECT logs FROM {self.table_name} WHERE hostname = %s;"
        try:
            self.cursor.execute(query, (hostname,))
            result = self.cursor.fetchone()
            if result:
                return result[0]
            else:
                logger.error(f"No VM found with hostname '{hostname}'.")
                return None
        except Exception as e:
            logger.error(f"Error retrieving logs: {e}")
            return None

    def save_logs_by_hostname(self, hostname: str, logs: str) -> None:
        """Save logs for a VM by its hostname.

        Args:
            hostname (str): The hostname of the VM.
            logs (str): The logs to save for the VM.
        """
        query = f"UPDATE {self.table_name} SET logs = %s WHERE hostname = %s;"
        try:
            self.cursor.execute(query, (logs, hostname))
            self.conn.commit()
            logger.debug(f"Saved logs for VM '{hostname}'.")
        except Exception as e:
            logger.error(f"Error saving logs: {e}")
            self.conn.rollback()

    def get_all_vm_status(self) -> dict:
        """Get the status of all VMs in the table.

        Returns:
            dict: A dictionary containing the hostname and status of each VM.
        """
        query = f"SELECT hostname, status FROM {self.table_name};"
        try:
            self.cursor.execute(query)
            rows = self.cursor.fetchall()
            return {row[0]: row[1] for row in rows}
        except Exception as e:
            logger.error(f"Error retrieving all VM status: {e}")
            return None

    def update_vm_status(self, hostname: str, status: str) -> None:
        """Update the status of a VM by its hostname.

        Args:
            hostname (str): The hostname of the VM.
            status (str): The new status to set for the VM.
        """
        possible_statuses = ["running", "initializing", "unknown", "error"]
        if status not in possible_statuses:
            logger.error(
                f"Invalid status '{status}'. Must be one of {possible_statuses}."
            )
            return

        query = f"""
        INSERT INTO {self.table_name} (hostname, status)
        VALUES (%s, %s)
        ON CONFLICT (hostname) DO UPDATE
            SET status = EXCLUDED.status;
        """
        try:
            self.cursor.execute(query, (hostname, status))
            self.conn.commit()
            logger.debug(f"Updated status for VM '{hostname}' to {status}.")
        except Exception as e:
            logger.error(f"Error updating VM status: {e}")
            self.conn.rollback()

    @classmethod
    def load_database(
        cls, dbname, user, password, host, port, table_name, message_channel
    ) -> "PostgresqlDatabase":
        """Loads an existing database from PostgreSQL.

        Args:
            dbname (str): The name of the database.
            user (str): The username to connect to the database.
            password (str): The password for the user.
            host (str): The host where the database is located.
            port (int): The port number for the database connection.
            table_name (str): The name of the table to interact with.
            message_channel (str): The name of the message channel to listen to.

        Returns:
            PostgresqlDatabase: An instance of the PostgresqlDatabase class.
        """
        return cls(dbname, user, password, host, port, table_name, message_channel)

    def update_terraform_timing(
        self,
        hostname: str,
        per_instance_seconds: float,
        per_instance_start_time: datetime,
        per_instance_end_time: datetime,
    ) -> None:
        """Update the Terraform timing metrics for a VM.
        Args:
            hostname (str): The hostname of the VM.
            per_instance_seconds (float): The total startup duration in seconds.
            per_instance_start_time (datetime): The start time of the Terraform apply process.
            per_instance_end_time (datetime): The end time of the Terraform apply process.
        """
        query = f"""
            UPDATE {self.table_name}
            SET terraformapplydurationseconds = %s,
                terraformapplyendtime = %s,
                terraformapplystarttime = %s
            WHERE hostname = %s;
        """
        try:
            self.cursor.execute(
                query,
                (
                    per_instance_seconds,
                    per_instance_start_time,
                    per_instance_end_time,
                    hostname,
                ),
            )
            self.conn.commit()
            logger.debug(
                f"Updated Terraform timing for VM '{hostname}': "
                f"TerraformApplyDurationSeconds={per_instance_seconds}, "
                f"TerraformApplyEndTime={per_instance_end_time}."
            )
        except Exception as e:
            logger.error(f"Error updating Terraform timing: {e}")
            self.conn.rollback()


    def update_cloud_init_metrics(self, hostname: str, metrics: dict) -> None:
        """Update various timing metrics for a VM.
        Args:
            hostname (str): The hostname of the VM.
            metrics (dict): A dictionary containing the timing metrics to update.
        """
        query = f"""
            UPDATE {self.table_name}
            SET cloudinitdurationseconds = %s,
                cloudinitendtime = %s,
                cloudinitstarttime = %s,
            WHERE hostname = %s;
        """
        try:
            self.cursor.execute(
                query,
                (
                    metrics.get("cloud_init_duration_seconds"),
                    metrics.get("cloud_init_end"),
                    metrics.get("cloud_init_start"),
                    hostname,
                ),
            )
            self.conn.commit()
            logger.debug(f"Updated VM metrics for '{hostname}': {metrics}.")
        except Exception as e:
            logger.error(f"Error updating VM metrics: {e}")
            self.conn.rollback()

    def __del__(self):
        """Close the database connection when the object is deleted."""
        self.cursor.close()
        self.conn.close()
        logger.debug("Database connection closed.")
