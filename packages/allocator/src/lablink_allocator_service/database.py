from datetime import datetime, timezone
import select
import json
import logging
from typing import List, Optional

import psycopg2
import psycopg2.pool

# Set up logging
logger = logging.getLogger(__name__)

try:
    import psycopg2  # noqa: F811 (re-imported for the ImportError guard)
except ImportError as e:
    logger.error(
        "psycopg2 is not installed in the development environment. "
        "Please install it using `pip install psycopg2`"
    )
    raise e


# Pool sizing. Internal: end users deploying the allocator don't need to
# reason about this. Raise these in-code if production metrics show
# getconn blocking during traffic bursts.
POOL_MIN_SIZE = 2
POOL_MAX_SIZE = 20


class _PooledCursor:
    """Checks out an autocommit connection from the pool, opens a cursor,
    and returns both to the pool/closes on exit. Preserves the per-call
    context-manager API previously provided by _LockedCursor.
    """

    def __init__(self, pool):
        self._pool = pool
        self._conn = None
        self._cur = None

    def __enter__(self):
        self._conn = self._pool.getconn()
        try:
            # Mirror pre-refactor behavior: every connection runs in
            # autocommit. Applied per checkout — cheap, and defensive
            # against anything that ever flips isolation levels on a
            # pooled conn.
            self._conn.set_isolation_level(
                psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT
            )
            self._cur = self._conn.cursor()
            return self._cur
        except Exception:
            self._pool.putconn(self._conn)
            self._conn = None
            raise

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if self._cur is not None:
                self._cur.close()
        finally:
            if self._conn is not None:
                # On exception, discard the conn so a bad connection doesn't
                # re-enter the pool. Happy path: return it for reuse.
                self._pool.putconn(
                    self._conn, close=(exc_type is not None)
                )
        return False  # don't swallow exceptions


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
        pool_min_size: int = POOL_MIN_SIZE,
        pool_max_size: int = POOL_MAX_SIZE,
    ):
        """Initialize the database connection pool.

        Args:
            dbname (str): The name of the database.
            user (str): The username to connect to the database.
            password (str): The password for the user.
            host (str): The host where the database is located.
            port (int): The port number for the database connection.
            table_name (str): The name of the table to interact with.
            message_channel (str): The name of the message channel to listen to.
            pool_min_size (int): Minimum pooled connections. Defaults to
                POOL_MIN_SIZE. Override in tests only.
            pool_max_size (int): Maximum pooled connections. Defaults to
                POOL_MAX_SIZE. Override in tests only.

        Raises:
            ValueError: If pool sizing is invalid.
        """
        if pool_min_size < 1 or pool_max_size < pool_min_size:
            raise ValueError(
                f"Invalid pool sizes: min={pool_min_size}, max={pool_max_size}"
            )

        self.dbname = dbname
        self.user = user
        self.password = password
        self.host = host
        self.port = port
        self.table_name = table_name
        self.message_channel = message_channel

        self._pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=pool_min_size,
            maxconn=pool_max_size,
            dbname=dbname,
            user=user,
            password=password,
            host=host,
            port=port,
        )

    @property
    def _cursor(self):
        """Return a context manager that checks out a pooled connection
        and yields a cursor.

        Usage:
            with self._cursor as cursor:
                cursor.execute(...)
        """
        return _PooledCursor(self._pool)

    def get_all_vms(self) -> list:
        """Get all VMs from the table, excluding logs.

        Returns:
            list: A list of all VMs in the table in the form of dictionaries.
        """
        column_names = [
            col
            for col in self.get_column_names()
            if col not in ("cloudinitlogs", "dockerlogs")
        ]
        query_columns = ", ".join(column_names)
        with self._cursor as cursor:
            cursor.execute(f"SELECT {query_columns} FROM {self.table_name};")
            rows = cursor.fetchall()
        return [dict(zip(column_names, row)) for row in rows]

    def get_all_vms_for_export(self, include_logs: bool = False) -> list:
        """Get all VMs with metrics data for export.

        Excludes sensitive columns (pin, crdcommand). Logs are excluded
        by default since the export targets quantitative metrics.

        Args:
            include_logs: Whether to include cloudinitlogs and dockerlogs.

        Returns:
            list: A list of VM dicts with metrics columns.
        """
        exclude = {"pin", "crdcommand"}
        if not include_logs:
            exclude |= {"cloudinitlogs", "dockerlogs"}
        column_names = [
            col
            for col in self.get_column_names()
            if col not in exclude
        ]
        query_columns = ", ".join(column_names)
        with self._cursor as cursor:
            cursor.execute(f"SELECT {query_columns} FROM {self.table_name};")
            rows = cursor.fetchall()
        return [dict(zip(column_names, row)) for row in rows]

    def get_row_count(self) -> int:
        """Get the number of rows in the table.
        Returns:
            int: The number of rows in the table.
        """
        with self._cursor as cursor:
            cursor.execute(f"SELECT COUNT(*) FROM {self.table_name};")
            return cursor.fetchone()[0]

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
        with self._cursor as cursor:
            cursor.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = %s",
                (table_name,),
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

        with self._cursor as cursor:
            try:
                sql = (
                    f"INSERT INTO {self.table_name} "
                    f"({columns}) VALUES ({placeholders});"
                )
                cursor.execute(sql, values)
            except Exception as e:
                logger.error(f"Failed to insert VM '{hostname}': {e}")
                raise

    def get_vm_by_hostname(self, hostname: str) -> dict:
        """Get a VM by its hostname.

        Args:
            hostname (str): The hostname of the VM.

        Returns:
            dict: A dictionary containing the VM details without logs.
        """
        query = f"SELECT * FROM {self.table_name} WHERE hostname = %s;"
        with self._cursor as cursor:
            cursor.execute(query, (hostname,))
            row = cursor.fetchone()
        if row:
            return {
                "hostname": row[0],
                "pin": row[1],
                "crdcommand": row[2],
                "useremail": row[3],
                "inuse": row[4],
                "healthy": row[5],
                "status": row[6],
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
            logger.warning(f"VM not found: '{hostname}'")
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
        listen_conn = psycopg2.connect(
            dbname=self.dbname,
            user=self.user,
            password=self.password,
            host=self.host,
            port=self.port,
        )
        listen_conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
        listen_cursor = listen_conn.cursor()

        logger.info(f"Waiting for CRD assignment for VM '{target_hostname}'")

        try:
            listen_cursor.execute(f"LISTEN {channel};")

            while True:
                if select.select([listen_conn], [], [], 10) == ([], [], []):
                    continue

                listen_conn.poll()
                while listen_conn.notifies:
                    notify = listen_conn.notifies.pop(0)

                    try:
                        payload_data = json.loads(notify.payload)
                        hostname = payload_data.get("HostName")
                        pin = payload_data.get("Pin")
                        command = payload_data.get("CrdCommand")

                        if hostname is None or pin is None or command is None:
                            logger.warning(
                                f"Invalid notification payload - missing fields: "
                                f"{list(payload_data.keys())}"
                            )
                            continue

                        if hostname != target_hostname:
                            # Notification for different VM, ignore
                            continue

                        logger.info(f"CRD command received for VM '{hostname}'")
                        return {
                            "status": "success",
                            "pin": pin,
                            "command": command,
                        }

                    except json.JSONDecodeError as e:
                        logger.error(f"Invalid JSON in notification payload: {e}")
                        continue
                    except Exception as e:
                        logger.error(f"Failed to process notification: {e}")
                        continue
        finally:
            listen_cursor.close()
            listen_conn.close()

    def get_crd_command(self, hostname) -> str:
        """Get the command assigned to a VM.

        Args:
            hostname (str): The hostname of the VM.

        Returns:
            str: The command assigned to the VM.
        """
        if not self.vm_exists(hostname):
            return None

        query = (
            f"SELECT crdcommand FROM {self.table_name} "
            f"WHERE hostname = %s"
        )
        with self._cursor as cursor:
            cursor.execute(query, (hostname,))
            return cursor.fetchone()[0]

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
            with self._cursor as cursor:
                cursor.execute(query)
                return [row[0] for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to retrieve unassigned VMs: {e}")
            return []

    def vm_exists(self, hostname) -> bool:
        """Check if a VM with the given hostname exists in the table.

        Args:
            hostname (str): The hostname of the VM.

        Returns:
            bool: True if the VM exists, False otherwise.
        """
        query = (
            f"SELECT EXISTS "
            f"(SELECT 1 FROM {self.table_name} "
            f"WHERE hostname = %s)"
        )
        with self._cursor as cursor:
            cursor.execute(query, (hostname,))
            result = cursor.fetchone()
        return result[0] if result else False

    def get_assigned_vms(self) -> list:
        """Get the VMs that are assigned to a command.

        Returns:
            list: A list of VMs that are assigned to a command.
        """
        query = (
            f"SELECT hostname FROM {self.table_name} "
            f"WHERE crdcommand IS NOT NULL"
        )
        try:
            with self._cursor as cursor:
                cursor.execute(query)
                return [row[0] for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Failed to retrieve assigned VMs: {e}")
            return []

    def get_vm_details(self, email: str) -> list:
        """Get VM details based on the email provided.

        Args:
            email (str): The email of the user.

        Returns:
            list: A list containing the hostname, pin, and CRD command of the VM
            assigned to the given user.
        """
        query = (
            f"SELECT hostname, pin, crdcommand FROM {self.table_name}"
            " WHERE useremail = %s"
        )
        with self._cursor as cursor:
            cursor.execute(query, (email,))
            row = cursor.fetchone()
        if row:
            hostname, pin, crdcommand = row
            return [
                hostname,
                pin,
                crdcommand,
            ]
        else:
            raise ValueError(
                f"No VM found for email in the database: {email}"
            )

    def get_assigned_vm_for_email(self, email: str) -> Optional[dict]:
        """Look up whether an email already has a VM assigned.

        Used by /api/request_vm to decide between reassignment (same
        hostname, new CRD) and fresh assignment (new hostname).

        Re-raises on DB error rather than swallowing: "lookup failed"
        and "no assignment exists" are semantically different states.
        Treating them identically (by returning None in both cases)
        would silently route a student with an existing assignment to
        the fresh-assignment path under a transient DB blip, producing
        a dual-assignment. The caller's outer try/except handles the
        raised exception and renders the generic error page.

        Args:
            email: The student's email address.

        Returns:
            A dict with hostname, status, reboot_count if an assignment
            exists, or None if the email has no VM.

        Raises:
            Exception: on DB connection or query failure.
        """
        query = f"""
            SELECT hostname, status, COALESCE(reboot_count, 0)
            FROM {self.table_name}
            WHERE useremail = %s
            LIMIT 1;
        """
        try:
            with self._cursor as cursor:
                cursor.execute(query, (email,))
                row = cursor.fetchone()
            if row is None:
                return None
            return {
                "hostname": row[0],
                "status": row[1],
                "reboot_count": row[2],
            }
        except Exception as e:
            logger.error(
                f"Failed to look up assigned VM for '{email}': {e}"
            )
            raise

    def assign_vm(self, email, crd_command, pin) -> None:
        """Assign a VM to a user.

        Args:
            email (str): The email of the user.
            crd_command (str): The CRD command to assign.
            pin (str): The PIN for the VM.
        """
        hostname = self.get_first_available_vm()

        if not hostname:
            logger.warning("No available VMs to assign")
            raise ValueError("No available VMs to assign.")

        query = f"""
        UPDATE {self.table_name}
        SET useremail = %s, crdcommand = %s, pin = %s,
            inuse = FALSE
        WHERE hostname = %s;
        """
        with self._cursor as cursor:
            try:
                cursor.execute(
                    query, (email, crd_command, pin, hostname)
                )
                logger.info(
                    f"Assigned VM '{hostname}' to user '{email}'"
                )
            except Exception as e:
                logger.error(
                    f"Failed to assign VM '{hostname}': {e}"
                )
                raise

    def reassign_crd(
        self,
        hostname: str,
        crd_command: str,
        pin: str,
        expected_email: str,
    ) -> bool:
        """Reassign a new CRD command and PIN to an already-assigned VM.

        Used when a student whose VM failed and was rebooted resubmits
        /api/request_vm with a newly-generated CRD enrollment code.
        The existing Postgres trigger on UPDATE OF CrdCommand fires
        pg_notify, which wakes the client's /vm_startup LISTEN loop
        (or is picked up on the next /vm_startup call after reboot).

        The UPDATE is conditional on `useremail = expected_email` to
        close the race where the auto-reboot service's
        `release_assignment` fires between the caller's
        `get_assigned_vm_for_email` and this call. If the row's
        useremail no longer matches (e.g., released and reassigned to
        a different student), the UPDATE writes zero rows and the
        method returns False so the caller can surface a retry-page
        to the student.

        Args:
            hostname: The VM whose CRD is being reassigned.
            crd_command: The newly-generated CRD enrollment command.
            pin: The PIN to pair with the command.
            expected_email: The email this row is expected to be
                assigned to at the time of the UPDATE. Serves as an
                optimistic-concurrency guard.

        Returns:
            True if the row was updated, False if the assignment has
            changed (row no longer owned by expected_email).
        """
        query = f"""
            UPDATE {self.table_name}
            SET crdcommand = %s, pin = %s
            WHERE hostname = %s AND useremail = %s;
        """
        with self._cursor as cursor:
            try:
                cursor.execute(
                    query, (crd_command, pin, hostname, expected_email)
                )
                updated = cursor.rowcount > 0
                if updated:
                    logger.info(
                        f"Reassigned CRD for VM '{hostname}'"
                    )
                else:
                    logger.warning(
                        f"Could not reassign CRD for VM '{hostname}': "
                        f"row no longer owned by '{expected_email}' "
                        f"(concurrent release or reassignment)"
                    )
                return updated
            except Exception as e:
                logger.error(
                    f"Failed to reassign CRD for '{hostname}': {e}"
                )
                raise

    def get_first_available_vm(self) -> str:
        """Get the first available VM that is not assigned.

        Returns:
            str: The hostname of the first available VM.
        """
        query = (
            f"SELECT hostname FROM {self.table_name} "
            f"WHERE useremail IS NULL AND "
            f"status = 'running' LIMIT 1"
        )
        with self._cursor as cursor:
            cursor.execute(query)
            row = cursor.fetchone()
        return row[0] if row else None

    def update_vm_in_use(self, hostname: str, in_use: bool) -> None:
        """Update the in-use status of a VM.

        Args:
            hostname (str): The hostname of the VM.
            in_use (bool): The in-use status to set.
        """
        query = (
            f"UPDATE {self.table_name} "
            f"SET inuse = %s WHERE hostname = %s"
        )
        with self._cursor as cursor:
            try:
                cursor.execute(query, (in_use, hostname))
            except Exception as e:
                logger.error(
                    f"Failed to update in-use status "
                    f"for VM '{hostname}': {e}"
                )
                raise

    def clear_database(self) -> None:
        """Delete all VMs from the table."""
        query = f"DELETE FROM {self.table_name};"
        with self._cursor as cursor:
            cursor.execute(query)
            logger.info("Cleared all VMs from database")

    def update_health(self, hostname: str, healthy: str) -> None:
        """Modify the health status of a VM.

        Args:
            hostname (str): The hostname of the VM.
            healthy (str): The health status to set for the VM.
        """
        query = (
            f"UPDATE {self.table_name} "
            f"SET healthy = %s WHERE hostname = %s;"
        )
        with self._cursor as cursor:
            try:
                cursor.execute(query, (healthy, hostname))
            except Exception as e:
                logger.error(
                    f"Failed to update health status "
                    f"for VM '{hostname}': {e}"
                )
                raise

    def get_gpu_health(self, hostname: str) -> str:
        """Get the GPU health status of a VM.

        Args:
            hostname (str): The hostname of the VM.

        Returns:
            str: The health status of the GPU for the specified VM
                or None if not found.
        """
        query = (
            f"SELECT healthy FROM {self.table_name} "
            f"WHERE hostname = %s;"
        )
        try:
            with self._cursor as cursor:
                cursor.execute(query, (hostname,))
                result = cursor.fetchone()
            return result[0] if result else None
        except Exception as e:
            logger.error(
                f"Failed to retrieve GPU health "
                f"for VM '{hostname}': {e}"
            )
            return None

    def get_status_by_hostname(self, hostname: str) -> str:
        """Get the status of a VM by its hostname.

        Args:
            hostname (str): The hostname of the VM.

        Returns:
            str: The status of the VM, or None if not found.
        """
        query = (
            f"SELECT status FROM {self.table_name} "
            f"WHERE hostname = %s;"
        )
        try:
            with self._cursor as cursor:
                cursor.execute(query, (hostname,))
                result = cursor.fetchone()
            return result[0] if result else None
        except Exception as e:
            logger.error(
                f"Failed to retrieve status "
                f"for VM '{hostname}': {e}"
            )
            return None

    def get_vm_logs(self, hostname: str, log_type: str = None) -> dict:
        """Get the logs of a VM by its hostname.

        Args:
            hostname (str): The hostname of the VM.
            log_type (str): "cloud_init", "docker", or None for both.

        Returns:
            dict: A dict with "cloud_init_logs" and/or "docker_logs",
                or None if the VM is not found.
        """
        column_map = {
            "cloud_init": ("cloudinitlogs", "cloud_init_logs"),
            "docker": ("dockerlogs", "docker_logs"),
        }
        try:
            with self._cursor as cursor:
                if log_type in column_map:
                    col, key = column_map[log_type]
                    query = (
                        f"SELECT {col} FROM {self.table_name} "
                        f"WHERE hostname = %s;"
                    )
                    cursor.execute(query, (hostname,))
                    result = cursor.fetchone()
                    return {key: result[0]} if result else None
                else:
                    query = (
                        f"SELECT cloudinitlogs, dockerlogs "
                        f"FROM {self.table_name} "
                        f"WHERE hostname = %s;"
                    )
                    cursor.execute(query, (hostname,))
                    result = cursor.fetchone()
                    if result:
                        return {
                            "cloud_init_logs": result[0],
                            "docker_logs": result[1],
                        }
                    return None
        except Exception as e:
            logger.error(
                f"Failed to retrieve logs "
                f"for VM '{hostname}': {e}"
            )
            return None

    def save_logs_by_hostname(
        self, hostname: str, logs: str, log_type: str = "cloud_init"
    ) -> None:
        """Save logs for a VM by its hostname.

        Args:
            hostname (str): The hostname of the VM.
            logs (str): The logs to save for the VM.
            log_type (str): "cloud_init" or "docker".
        """
        column = (
            "cloudinitlogs" if log_type == "cloud_init"
            else "dockerlogs"
        )
        query = (
            f"UPDATE {self.table_name} "
            f"SET {column} = %s WHERE hostname = %s;"
        )
        with self._cursor as cursor:
            try:
                cursor.execute(query, (logs, hostname))
            except Exception as e:
                logger.error(
                    f"Failed to save {log_type} logs "
                    f"for VM '{hostname}': {e}"
                )
                raise

    def append_logs_by_hostname(
        self,
        hostname: str,
        new_logs: str,
        log_type: str = "cloud_init",
        max_size: int = 1 * 1024 * 1024,
    ) -> None:
        """Atomically append logs for a VM, truncating to max_size.

        Uses a single SQL UPDATE to avoid race conditions when multiple
        log shippers POST concurrently for the same VM.

        Args:
            hostname (str): The hostname of the VM.
            new_logs (str): The new log lines to append.
            log_type (str): "cloud_init" or "docker".
            max_size (int): Maximum log size in bytes (default 1MB).
        """
        column = (
            "cloudinitlogs" if log_type == "cloud_init"
            else "dockerlogs"
        )
        # Atomic append + truncate in a single UPDATE:
        # 1. COALESCE handles NULL (first write)
        # 2. Concatenate with newline separator
        # 3. RIGHT(..., max_size) keeps the most recent bytes
        # 4. Trim any partial first line left by truncation
        query = f"""
            UPDATE {self.table_name}
            SET {column} = (
                SELECT CASE
                    WHEN length(combined) > %s
                    THEN substring(combined
                        FROM position(E'\\n' IN right(combined, %s)) + 1)
                    ELSE combined
                END
                FROM (
                    SELECT COALESCE({column} || E'\\n', '') || %s AS combined
                ) sub
            )
            WHERE hostname = %s;
        """
        with self._cursor as cursor:
            try:
                cursor.execute(
                    query, (max_size, max_size, new_logs, hostname)
                )
            except Exception as e:
                logger.error(
                    f"Failed to append {log_type} logs "
                    f"for VM '{hostname}': {e}"
                )
                raise

    def get_all_vm_status(self) -> dict:
        """Get the status of all VMs in the table.

        Returns:
            dict: A dictionary containing the hostname and status
                of each VM.
        """
        query = (
            f"SELECT hostname, status FROM {self.table_name};"
        )
        try:
            with self._cursor as cursor:
                cursor.execute(query)
                rows = cursor.fetchall()
            return {row[0]: row[1] for row in rows}
        except Exception as e:
            logger.error(
                f"Failed to retrieve VM statuses: {e}"
            )
            return None

    def update_vm_status(self, hostname: str, status: str) -> None:
        """Update the status of a VM by its hostname.

        Args:
            hostname (str): The hostname of the VM.
            status (str): The new status to set for the VM.
        """
        possible_statuses = [
            "running", "initializing", "unknown",
            "error", "rebooting",
        ]
        if status not in possible_statuses:
            logger.error(
                f"Invalid VM status '{status}' for '{hostname}'"
            )
            return

        query = f"""
        INSERT INTO {self.table_name} (hostname, status)
        VALUES (%s, %s)
        ON CONFLICT (hostname) DO UPDATE
            SET status = EXCLUDED.status;
        """
        with self._cursor as cursor:
            try:
                cursor.execute(query, (hostname, status))
                logger.debug(
                    f"VM '{hostname}' status: {status}"
                )
            except Exception as e:
                logger.error(
                    f"Failed to update status "
                    f"for VM '{hostname}': {e}"
                )

    @classmethod
    def load_database(
        cls,
        dbname,
        user,
        password,
        host,
        port,
        table_name,
        message_channel,
        pool_min_size: int = POOL_MIN_SIZE,
        pool_max_size: int = POOL_MAX_SIZE,
    ) -> "PostgresqlDatabase":
        """Loads an existing database from PostgreSQL.

        Args match __init__. Provided for callers that prefer the
        classmethod style.
        """
        return cls(
            dbname,
            user,
            password,
            host,
            port,
            table_name,
            message_channel,
            pool_min_size=pool_min_size,
            pool_max_size=pool_max_size,
        )

    @staticmethod
    def _naive_utc(dt: datetime) -> datetime:
        """Convert a datetime to naive UTC."""
        if dt.tzinfo is not None:
            return dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt

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
            per_instance_start_time (datetime): The start time of the Terraform apply.
            per_instance_end_time (datetime): The end time of the Terraform apply.
        """

        query = f"""
            INSERT INTO {self.table_name} (
                hostname,
                terraformapplydurationseconds,
                terraformapplystarttime,
                terraformapplyendtime
            )
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (hostname) DO UPDATE
            SET terraformapplydurationseconds = EXCLUDED.terraformapplydurationseconds,
                terraformapplystarttime = EXCLUDED.terraformapplystarttime,
                terraformapplyendtime = EXCLUDED.terraformapplyendtime
        """
        with self._cursor as cursor:
            try:
                cursor.execute(
                    query,
                    (
                        hostname,
                        per_instance_seconds,
                        self._naive_utc(per_instance_start_time),
                        self._naive_utc(per_instance_end_time),
                    ),
                )
            except Exception as e:
                logger.error(
                    f"Failed to update Terraform timing for VM '{hostname}': {e}"
                )
                raise

    def update_vm_metrics_atomic(self, hostname: str, metrics: dict) -> None:
        """Update VM metrics and calculate total startup time in a single transaction.

        Args:
            hostname (str): The hostname of the VM.
            metrics (dict): A dictionary containing the timing metrics to update.
                Supported keys:
                - cloud_init_start (int): Unix timestamp
                - cloud_init_end (int): Unix timestamp
                - cloud_init_duration_seconds (float)
                - container_start (int): Unix timestamp
                - container_end (int): Unix timestamp
                - container_startup_duration_seconds (float)

        Raises:
            Exception: If the database operation fails (re-raised after rollback).
        """
        updates = []
        values = []

        # Build metric updates
        if "cloud_init_start" in metrics:
            updates.append("CloudInitStartTime = to_timestamp(%s)")
            values.append(metrics["cloud_init_start"])
        if "cloud_init_end" in metrics:
            updates.append("CloudInitEndTime = to_timestamp(%s)")
            values.append(metrics["cloud_init_end"])
        if "cloud_init_duration_seconds" in metrics:
            updates.append("CloudInitDurationSeconds = %s")
            values.append(metrics["cloud_init_duration_seconds"])

        if "container_start" in metrics:
            updates.append("ContainerStartTime = to_timestamp(%s)")
            values.append(metrics["container_start"])
        if "container_end" in metrics:
            updates.append("ContainerEndTime = to_timestamp(%s)")
            values.append(metrics["container_end"])
        if "container_startup_duration_seconds" in metrics:
            updates.append("ContainerStartupDurationSeconds = %s")
            values.append(metrics["container_startup_duration_seconds"])

        if not updates:
            return

        # Build the total startup time calculation using new values where
        # available. In PostgreSQL, SET expressions read pre-update column
        # values, so referencing the column being updated in the same
        # statement returns the OLD value. We must inline the new value
        # for any metric being set in this UPDATE.
        terraform_expr = "COALESCE(TerraformApplyDurationSeconds, 0)"
        cloud_init_expr = "COALESCE(CloudInitDurationSeconds, 0)"
        container_expr = "COALESCE(ContainerStartupDurationSeconds, 0)"

        if "cloud_init_duration_seconds" in metrics:
            cloud_init_expr = "%s"
            values.append(metrics["cloud_init_duration_seconds"])
        if "container_startup_duration_seconds" in metrics:
            container_expr = "%s"
            values.append(metrics["container_startup_duration_seconds"])

        total_expr = (
            f"{terraform_expr} + {cloud_init_expr} + {container_expr}"
        )
        updates.append(f"TotalStartupDurationSeconds = {total_expr}")

        query = f"""
            UPDATE {self.table_name}
            SET {", ".join(updates)}
            WHERE hostname = %s
            RETURNING TotalStartupDurationSeconds;
        """
        values.append(hostname)

        with self._cursor as cursor:
            try:
                cursor.execute(query, tuple(values))
                result = cursor.fetchone()

                # Log total startup time when available
                if result and result[0] is not None and result[0] > 0:
                    logger.info(
                        f"VM '{hostname}' total startup time: {result[0]:.1f}s"
                    )
            except Exception as e:
                logger.error(
                    f"Failed to update metrics for VM '{hostname}': {e}"
                )
                raise

    def create_scheduled_destruction(
        self,
        schedule_name: str,
        destruction_time: datetime,
        recurrence_rule: str = None,
        created_by: str = None,
        notification_enabled: bool = True,
        notification_hours_before: int = 1,
    ) -> int:
        """Create a scheduled destruction entry and return its ID.

        Raises:
            ValueError: If a schedule with the same name already exists
            RuntimeError: If database operation fails
        """
        query = """
            INSERT INTO scheduled_destructions
            (schedule_name, destruction_time, recurrence_rule, created_by,
            notification_enabled, notification_hours_before, status)
            VALUES (%s, %s, %s, %s, %s, %s, 'scheduled')
            RETURNING id;
        """
        with self._cursor as cursor:
            try:
                cursor.execute(
                    query,
                    (
                        schedule_name,
                        self._naive_utc(destruction_time),
                        recurrence_rule,
                        created_by,
                        notification_enabled,
                        notification_hours_before,
                    ),
                )
                destruction_id = cursor.fetchone()[0]
                logger.info(
                    f"Created scheduled destruction "
                    f"'{schedule_name}' "
                    f"(ID: {destruction_id})"
                )
                return destruction_id

            except psycopg2.IntegrityError as e:
                if (
                    'schedule_name' in str(e)
                    or 'unique constraint' in str(e).lower()
                ):
                    error_msg = (
                        f"Schedule '{schedule_name}' already exists"
                    )
                    logger.warning(error_msg)
                    raise ValueError(error_msg) from e
                else:
                    logger.error(
                        f"Database integrity error "
                        f"creating schedule: {e}"
                    )
                    raise RuntimeError(
                        f"Database integrity error: {e}"
                    ) from e

            except Exception as e:
                logger.error(
                    f"Failed to create scheduled destruction "
                    f"'{schedule_name}': {e}"
                )
                raise RuntimeError(
                    f"Failed to create scheduled destruction: {e}"
                ) from e

    def get_scheduled_destruction(self, schedule_id: int) -> Optional[dict]:
        """Get scheduled destruction by ID."""
        query = "SELECT * FROM scheduled_destructions WHERE id = %s;"
        with self._cursor as cursor:
            cursor.execute(query, (schedule_id,))
            row = cursor.fetchone()
        if row:
            columns = [
                "id",
                "schedule_name",
                "destruction_time",
                "recurrence_rule",
                "created_by",
                "status",
                "execution_count",
                "last_execution_time",
                "last_execution_result",
                "notification_enabled",
                "notification_hours_before",
                "created_at",
                "updated_at",
            ]
            return dict(zip(columns, row))
        return None

    def get_all_scheduled_destructions(
        self, status: Optional[str] = None
    ) -> List[dict]:
        """Get all scheduled destructions, optionally filtered by status."""
        columns = [
            "id",
            "schedule_name",
            "destruction_time",
            "recurrence_rule",
            "created_by",
            "status",
            "execution_count",
            "last_execution_time",
            "last_execution_result",
            "notification_enabled",
            "notification_hours_before",
            "created_at",
            "updated_at",
        ]

        with self._cursor as cursor:
            if status:
                query = (
                    "SELECT * FROM scheduled_destructions "
                    "WHERE status = %s "
                    "ORDER BY destruction_time;"
                )
                cursor.execute(query, (status,))
            else:
                query = (
                    "SELECT * FROM scheduled_destructions "
                    "ORDER BY destruction_time;"
                )
                cursor.execute(query)

            return [
                dict(zip(columns, row))
                for row in cursor.fetchall()
            ]

    def update_scheduled_destruction_status(
        self,
        schedule_id: int,
        status: str,
        execution_result: Optional[str] = None,
    ) -> None:
        """Update destruction execution status."""
        query = """
            UPDATE scheduled_destructions
            SET status = %s,
                execution_count = execution_count + 1,
                last_execution_time = NOW(),
                last_execution_result = %s
            WHERE id = %s;
        """
        with self._cursor as cursor:
            cursor.execute(
                query, (status, execution_result, schedule_id)
            )

    def cancel_scheduled_destruction(self, schedule_id: int) -> None:
        """Cancel a scheduled destruction."""
        query = (
            "UPDATE scheduled_destructions "
            "SET status = 'cancelled' WHERE id = %s;"
        )
        with self._cursor as cursor:
            cursor.execute(query, (schedule_id,))

    def ensure_reboot_columns(self) -> None:
        """Add reboot tracking columns to vm_table if they don't exist."""
        columns = {
            "reboot_count": "INTEGER DEFAULT 0",
            "last_reboot_time": "TIMESTAMP",
        }
        for col_name, col_type in columns.items():
            with self._cursor as cursor:
                try:
                    cursor.execute(
                        f"ALTER TABLE {self.table_name} "
                        f"ADD COLUMN IF NOT EXISTS "
                        f"{col_name} {col_type};"
                    )
                except Exception as e:
                    logger.error(
                        f"Failed to add column {col_name}: {e}"
                    )

    def record_heartbeat(
        self,
        hostname: str,
        boot_id: Optional[str],
        crd_active: Optional[bool],
        disk_free_pct: Optional[int],
    ) -> bool:
        """Record a client-VM heartbeat and emit warnings on anomalies.

        Updates last_seen_at and the three reported health fields. Logs a
        warning (not an error) when:

        - boot_id changed vs the previous value (unexpected host reboot),
        - crd_active transitioned from True to False,
        - disk_free_pct dropped below 10.

        Returns True if the row was updated, False if the hostname is
        unknown.
        """
        select_query = (
            f"SELECT boot_id, crd_active "
            f"FROM {self.table_name} WHERE hostname = %s;"
        )
        update_query = f"""
            UPDATE {self.table_name}
            SET last_seen_at = NOW(),
                boot_id = %s,
                crd_active = %s,
                disk_free_pct = %s
            WHERE hostname = %s;
        """
        try:
            with self._cursor as cursor:
                cursor.execute(select_query, (hostname,))
                row = cursor.fetchone()
                if row is None:
                    logger.warning(
                        f"Heartbeat for unknown hostname {hostname}"
                    )
                    return False
                prev_boot_id, prev_crd = row

                if (
                    boot_id is not None
                    and prev_boot_id is not None
                    and prev_boot_id != boot_id
                ):
                    logger.warning(
                        f"boot_id changed for {hostname}: "
                        f"{prev_boot_id} -> {boot_id}"
                    )
                if prev_crd is True and crd_active is False:
                    logger.warning(
                        f"crd_active flipped False for {hostname}"
                    )
                if disk_free_pct is not None and disk_free_pct < 10:
                    logger.warning(
                        f"disk_free_pct low for {hostname}: "
                        f"{disk_free_pct}%"
                    )

                cursor.execute(
                    update_query,
                    (
                        boot_id,
                        crd_active,
                        disk_free_pct,
                        hostname,
                    ),
                )
                return True
        except Exception as e:
            logger.error(f"Failed to record heartbeat for {hostname}: {e}")
            return False

    def touch_last_seen(self, hostname: str) -> None:
        """Bump last_seen_at for a VM without touching other columns.

        Called at the top of every authenticated client->allocator
        endpoint so that any client traffic refreshes the liveness
        timer. Heartbeat remains the primary signal; this is cheap
        insurance against false-positive staleness.
        """
        query = (
            f"UPDATE {self.table_name} "
            f"SET last_seen_at = NOW() WHERE hostname = %s;"
        )
        try:
            with self._cursor as cursor:
                cursor.execute(query, (hostname,))
        except Exception as e:
            logger.error(f"Failed to touch last_seen for {hostname}: {e}")

    def get_failed_vms(
        self,
        stale_initializing_minutes: int = 25,
        stale_rebooting_minutes: int = 10,
        stale_heartbeat_minutes: int = 3,
    ) -> List[dict]:
        """Get VMs that need a reboot attempt.

        Detects VMs in error state, with unhealthy GPUs, stuck initializing,
        stuck in rebooting state (failed to come back after a reboot), or
        running but silent (no heartbeat within the staleness window).

        Args:
            stale_initializing_minutes: Minutes after which an initializing VM
                is considered stale and eligible for reboot. Default 25 min —
                VMs can now legitimately sit in 'initializing' for the full
                duration of custom-startup.sh (ilastik downloads, large
                tutorial datasets, etc.) because user_data.sh no longer
                prematurely flips status to 'running'; start.sh does that
                once client services are about to launch.
            stale_rebooting_minutes: Minutes after which a rebooting VM is
                considered stuck and eligible for another reboot attempt.
            stale_heartbeat_minutes: Minutes after which a running VM is
                considered silent and eligible for reboot. Default 3 min
                (6x the 30s heartbeat cadence). Brand-new VMs with
                last_seen_at IS NULL are not flagged — they must heartbeat
                at least once to be eligible for staleness detection.

        Returns:
            list: VMs eligible for reboot with hostname, status, healthy,
                  reboot_count, last_reboot_time, useremail, and last_seen_at.
        """
        init_minutes = int(stale_initializing_minutes)
        reboot_minutes = int(stale_rebooting_minutes)
        heartbeat_minutes = int(stale_heartbeat_minutes)
        query = f"""
            SELECT hostname, status, healthy,
                   COALESCE(reboot_count, 0) as reboot_count,
                   last_reboot_time, useremail, last_seen_at
            FROM {self.table_name}
            WHERE status = 'error'
               OR (healthy = 'Unhealthy'
                   AND status NOT IN ('rebooting', 'error'))
               OR (status = 'initializing'
                   AND createdat IS NOT NULL
                   AND createdat < NOW()
                   - INTERVAL '{init_minutes} minutes')
               OR (status = 'rebooting'
                   AND last_reboot_time IS NOT NULL
                   AND last_reboot_time < NOW()
                   - INTERVAL '{reboot_minutes} minutes')
               OR (status = 'running'
                   AND last_seen_at IS NOT NULL
                   AND last_seen_at < NOW()
                   - INTERVAL '{heartbeat_minutes} minutes');
        """
        try:
            with self._cursor as cursor:
                cursor.execute(query)
                rows = cursor.fetchall()
            return [
                {
                    "hostname": row[0],
                    "status": row[1],
                    "healthy": row[2],
                    "reboot_count": row[3],
                    "last_reboot_time": row[4],
                    "useremail": row[5],
                    "last_seen_at": row[6],
                }
                for row in rows
            ]
        except Exception as e:
            logger.error(f"Failed to get failed VMs: {e}")
            return []

    def record_reboot(self, hostname: str) -> None:
        """Record a reboot attempt for a VM.

        Sets status to 'rebooting', increments reboot_count, updates
        last_reboot_time, and clears the CRD session fields
        (crdcommand, pin) — the Chrome Remote Desktop enrollment
        token is one-shot and is invalidated by the reboot, so it must
        be reissued when the student reconnects.

        `useremail` is preserved so the student keeps their VM slot
        across reboots. If reboot attempts are exhausted, the
        assignment is explicitly released via `release_assignment`.

        Note: setting `crdcommand = NULL` fires the Postgres trigger
        `trigger_crd_command_insert_or_update`, which emits a NOTIFY
        with a NULL-valued CrdCommand payload. The LISTEN loop in
        `listen_for_notifications` discards such payloads (see the
        `hostname is None or pin is None or command is None` guard),
        but each reboot still produces a spurious "Invalid notification
        payload" warning in any client currently listening. The proper
        fix is to add a `WHEN (NEW.CrdCommand IS NOT NULL)` guard to
        the trigger definition; tracked for PR 4 of the failed-VM
        recovery roadmap.

        Args:
            hostname: The hostname of the VM being rebooted.
        """
        query = f"""
            UPDATE {self.table_name}
            SET status = 'rebooting',
                reboot_count = COALESCE(reboot_count, 0) + 1,
                last_reboot_time = NOW(),
                crdcommand = NULL,
                pin = NULL
            WHERE hostname = %s;
        """
        with self._cursor as cursor:
            try:
                cursor.execute(query, (hostname,))
                logger.info(
                    f"Recorded reboot for VM '{hostname}'"
                )
            except Exception as e:
                logger.error(
                    f"Failed to record reboot "
                    f"for VM '{hostname}': {e}"
                )
                raise

    def release_assignment(self, hostname: str) -> None:
        """Release a VM's student assignment when it is deemed unrecoverable.

        Called by the auto-reboot service when reboot_count exceeds
        max_attempts. Clears useremail, crdcommand, pin and sets
        status to 'error' so the pool reflects the VM as unassignable
        until an admin intervenes. reboot_count is preserved for
        diagnostics.

        Note: like `record_reboot`, setting `crdcommand = NULL` fires
        the Postgres NOTIFY trigger with a NULL payload, producing a
        discarded notification and a spurious warning log in any
        listening client. The trigger-level fix is tracked for PR 4 of
        the failed-VM recovery roadmap.

        Args:
            hostname: The hostname of the VM whose assignment is being released.
        """
        query = f"""
            UPDATE {self.table_name}
            SET useremail = NULL,
                crdcommand = NULL,
                pin = NULL,
                status = 'error'
            WHERE hostname = %s;
        """
        with self._cursor as cursor:
            try:
                cursor.execute(query, (hostname,))
                logger.info(
                    f"Released assignment for unrecoverable VM '{hostname}'"
                )
            except Exception as e:
                logger.error(
                    f"Failed to release assignment for '{hostname}': {e}"
                )
                raise

    def get_reboot_info(self, hostname: str) -> Optional[dict]:
        """Get reboot tracking info for a VM.

        Args:
            hostname: The hostname of the VM.

        Returns:
            dict with reboot_count and last_reboot_time,
                or None if not found.
        """
        query = f"""
            SELECT COALESCE(reboot_count, 0), last_reboot_time
            FROM {self.table_name}
            WHERE hostname = %s;
        """
        try:
            with self._cursor as cursor:
                cursor.execute(query, (hostname,))
                row = cursor.fetchone()
            if row:
                return {
                    "reboot_count": row[0],
                    "last_reboot_time": row[1],
                }
            return None
        except Exception as e:
            logger.error(
                f"Failed to get reboot info "
                f"for VM '{hostname}': {e}"
            )
            return None

    def __del__(self):
        """Close all pooled connections when the object is deleted."""
        if hasattr(self, "_pool") and self._pool is not None:
            try:
                self._pool.closeall()
            except Exception:
                # Pool may already be closed; nothing to do.
                pass
