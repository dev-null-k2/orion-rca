"""Host-network provisioning client."""
RATE_LIMIT_PER_SECOND = 50


def provision(line):
    return {"status": "queued", "line": line}
