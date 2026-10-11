"""Small LAN-app security checks that complement Django's built-in middleware."""


class RequestSecurityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Django validates ALLOWED_HOSTS when get_host() is called. Ensure that
        # even read-only endpoints reject a forged Host header.
        request.get_host()
        response = self.get_response(request)
        response["Content-Security-Policy"] = (
            "default-src 'self'; base-uri 'none'; object-src 'none'; "
            "script-src 'self'; style-src 'self'; img-src 'self'; "
            "connect-src 'self'; form-action 'self'; frame-ancestors 'none'"
        )
        return response
