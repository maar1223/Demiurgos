"""Small asynchronous boundary; callers enqueue IDs instead of blocking ingress.

Threading contract
------------------
``CaptureWorker`` runs processor calls on a thread pool. Durable SQLite access
from those threads is safe because ``CaptureStore`` owns one connection PER
thread (see ``store.CaptureStore``) — worker threads never share the ingress
thread's connection. ``close()`` first asks the pool threads to close their own
connections (SQLite connections can only be closed by their owning thread),
then shuts the pool down. Call it before ``CaptureStore.close()``.
"""

from concurrent.futures import ThreadPoolExecutor


class CaptureWorker:
    def __init__(self, processor, workers=1):
        self.processor = processor
        self.workers = workers
        self.executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="idea-capture")
        self._closed = False

    def submit(self, capture_id):
        if self._closed:
            raise RuntimeError("CaptureWorker is closed")
        return self.executor.submit(self.processor.process, capture_id)

    def submit_suggestions(self, capture_id, suggest):
        """Suggestions are enrichment-only and cannot veto the saved record."""
        def run():
            try:
                return suggest(self.processor.store.get(capture_id))
            except Exception:
                return {"status": "suggestions_unavailable"}
        return self.executor.submit(run)

    def close(self):
        if self._closed:
            return
        self._closed = True
        cleanup = getattr(self.processor.store, "close_own_thread_connections", None)
        if cleanup is not None:
            # Runs on a pool thread so each pool thread closes its own
            # connection; one task per worker keeps every pool thread covered.
            for _ in range(self.workers):
                self.executor.submit(cleanup)
        self.executor.shutdown(wait=True)
