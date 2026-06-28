"""Extract real client IP from request, considering proxy headers."""

from starlette.requests import Request


def get_client_ip(request: Request) -> str:
    """Get real client IP, checking proxy headers first.

    Priority:
    1. X-Forwarded-For (first IP in chain)
    2. X-Real-IP
    3. request.client.host (fallback)
    """
    if request is None:
        return "unknown"

    # Check X-Forwarded-For header
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        # Format: "client, proxy1, proxy2" — take the first (client) IP
        ip = forwarded_for.split(",")[0].strip()
        if ip:
            return ip

    # Check X-Real-IP header
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip

    # Fallback to client host
    if request.client:
        return request.client.host

    return "unknown"
