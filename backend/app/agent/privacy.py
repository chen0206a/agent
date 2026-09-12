import re


def scrub(value, secrets: tuple[str, ...] = ()):
    """Best-effort secret minimization; HTTP credentials are never included in traces."""
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[REDACTED]")
        return re.sub(r"sk-[A-Za-z0-9_-]{12,}", "[REDACTED]", value)
    if isinstance(value, list):
        return [scrub(item, secrets) for item in value]
    if isinstance(value, dict):
        return {
            key: "[REDACTED]"
            if key.lower() in {"api_key", "password", "authorization", "token"}
            else scrub(item, secrets)
            for key, item in value.items()
        }
    return value
