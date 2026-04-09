import datetime


class ContainerHost:
    hostname = ""
    commands = {}
    last_seen_at = None
    connection = -1

    def __init__(self, hostname, commands):
        self.hostname = hostname
        self.commands = commands
        self.last_seen_at = None
        self.connection = -1

    def is_conneced(self):
        if self.last_seen_at is None:
            return False
        now = datetime.datetime.now()
        difference = now - self.last_seen_at
        seconds = int(difference.total_seconds())
        return seconds <= 10

    def update_last_seen_at(self):
        self.last_seen_at = datetime.datetime.now()

    def send_message(self, msg):
        if self.connection != -1:
            self.connection.send(f"{msg}".encode())
        else:
            print(f"Host {self.hostname} is not connected")

    def get_command(self, cmd_name):
        return self.commands[cmd_name]
