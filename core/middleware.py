"""Thread-local current-request state so the audit layer can attribute
writes without every call site passing the user around."""

import threading

_local = threading.local()


def get_current_user():
    return getattr(_local, "user", None)


def get_current_ip():
    return getattr(_local, "ip", None)


class CurrentUserMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        _local.user = request.user if request.user.is_authenticated else None
        _local.ip = request.META.get("REMOTE_ADDR")
        try:
            return self.get_response(request)
        finally:
            _local.user = None
            _local.ip = None
