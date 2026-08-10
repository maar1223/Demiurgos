"""Idempotent Engram outbox publisher boundary."""


class MemoryPublisher:
    def __init__(self):
        self.messages = []

    def publish(self, topic, payload):
        if topic not in {item[0] for item in self.messages}:
            self.messages.append((topic, payload))
