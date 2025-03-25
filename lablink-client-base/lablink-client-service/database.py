import psycopg2
import select


class PostgresqlDtabase:
    def __init__(self, dbname, user, password, host, port, table_name):
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
        # LISTEN requires a non-transactional connection
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
            if col == "hostname":
                values.append(hostname)
            else:
                values.append(None)  # NULL in SQL

        columns = ", ".join(column_names)
        placeholders = ", ".join(["%s" for _ in column_names])

        print(f"Column names: {column_names}")
        print(f"Values: {values}")
        print(f"Columns: {columns}")
        print(f"Placeholders: {placeholders}")

        sql = f"INSERT INTO {self.table_name} ({columns}) VALUES ({placeholders});"
        self.cursor.execute(sql, values)
        self.conn.commit()
        print(f"Inserted data: {values}")

    def assign_vm(self, hostname, crd_command):
        """Assign a VM to a command.

        Args:
            hostname (str): The hostname of the VM.
            crd_command (str): The command to assign to the VM.
        """
        # Placeholder for the actual implementation
        print(f"Assigning VM '{hostname}' to command '{crd_command}'...")

        # Implement the logic to assign the VM to the command
        column_name = "crd_command"
        sql = f"UPDATE {self.table_name} SET {column_name} = %s WHERE hostname = %s;"
        self.cursor.execute(sql, (crd_command, hostname))
        self.conn.commit()
        print(f"Assigned VM '{hostname}' to command '{crd_command}'.")

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
                if select.select([self.conn], [], [], 5) == ([], [], []):
                    print("No notifications received in the last 5 seconds.")
                else:
                    self.conn.poll()  # Process any pending notifications
                    while self.conn.notifies:
                        notify = self.conn.notifies.pop(0)
                        print(
                            f"Received notification: {notify.payload} from channel {notify.channel}"
                        )
        except KeyboardInterrupt:
            print("Exiting...")
        finally:
            self.cursor.close()
            self.conn.close()
