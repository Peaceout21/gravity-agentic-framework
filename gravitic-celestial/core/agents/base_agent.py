"""Base class for runtime agents."""

from abc import ABCMeta, abstractmethod

from core.framework.messages import make_message


class BaseAgent(object, metaclass=ABCMeta):

    def __init__(self, name, event_bus):
        self.name = name
        self.bus = event_bus
        self.running = False
        self._setup()

    def _setup(self):
        return None

    @abstractmethod
    def start(self):
        raise NotImplementedError

    @abstractmethod
    def handle_message(self, message):
        raise NotImplementedError

    def publish(self, topic, payload):
        self.bus.publish(make_message(source=self.name, topic=topic, payload=payload))
