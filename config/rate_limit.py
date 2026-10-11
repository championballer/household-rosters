"""A small, per-process limit for writes on the directly served household LAN."""

import math
import time
from collections import OrderedDict, deque
from threading import Lock

from django.http import HttpResponse


class PostRateLimitMiddleware:
    limit = 30
    window_seconds = 60
    max_clients = 2048

    def __init__(self, get_response):
        self.get_response = get_response
        self.buckets = OrderedDict()
        self.lock = Lock()

    def __call__(self, request):
        if request.method != "POST":
            return self.get_response(request)

        # Waitress serves the LAN directly. Do not use client-supplied
        # X-Forwarded-For headers as a way to identify the caller.
        peer = request.META.get("REMOTE_ADDR") or "unknown"
        with self.lock:
            now = time.monotonic()
            bucket = self.buckets.get(peer)
            if bucket is None:
                if len(self.buckets) >= self.max_clients:
                    self.buckets.popitem(last=False)
                bucket = deque()
                self.buckets[peer] = bucket
            self.buckets.move_to_end(peer)
            while bucket and bucket[0] <= now - self.window_seconds:
                bucket.popleft()
            if len(bucket) >= self.limit:
                retry_after = max(1, math.ceil(bucket[0] + self.window_seconds - now))
            else:
                bucket.append(now)
                retry_after = None

        if retry_after is not None:
            response = HttpResponse("Too many changes. Please wait a moment and try again.",
                                    status=429, content_type="text/plain")
            response["Retry-After"] = str(retry_after)
            response["Cache-Control"] = "no-store"
            return response
        return self.get_response(request)
