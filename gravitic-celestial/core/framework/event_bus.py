"""Simple threaded pub/sub event bus."""

import logging
import threading
import time
from collections import defaultdict
from queue import Empty, Queue
from typing import Callable, DefaultDict, List

from core.framework.messages import AgentMessage

Handler = Callable[[AgentMessage], None]


class EventBus(object):
    def __init__(self, max_retries=2, retry_delay=0.25):
        self._queue = Queue()
        self._subscribers = defaultdict(list)  # type: DefaultDict[str, List[Handler]]
        self._lock = threading.Lock()
        self._worker = None
        self._running = False
        self._max_retries = max_retries
        self._retry_delay = retry_delay

    def subscribe(self, topic, handler):
        with self._lock:
            self._subscribers[topic].append(handler)

    def publish(self, message):
        self._queue.put(message)

    def start(self):
        if self._running:
            return
        self._running = True
        self._worker = threading.Thread(target=self._worker_loop, daemon=True, name="event-bus-worker")
        self._worker.start()

    def stop(self, timeout=2.0):
        self._running = False
        if self._worker:
            self._worker.join(timeout=timeout)

    def _worker_loop(self):
        while self._running:
            try:
                message = self._queue.get(timeout=0.1)
            except Empty:
                continue

            handlers = self._subscribers.get(message.topic, []) + self._subscribers.get("*", [])
            for handler in handlers:
                self._dispatch_with_retry(handler, message)
            self._queue.task_done()

    def _dispatch_with_retry(self, handler, message):
        attempt = 0
        while attempt <= self._max_retries:
            try:
                handler(message)
                return
            except Exception:
                logging.exception("event handler failed topic=%s attempt=%s", message.topic, attempt + 1)
                attempt += 1
                if attempt <= self._max_retries:
                    time.sleep(self._retry_delay)
