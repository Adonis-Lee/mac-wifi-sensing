"""Local web console must only answer requests addressed to 127.0.0.1/localhost (DNS rebinding)."""
import http.client
import threading
from http.server import ThreadingHTTPServer

import pytest

from app.visual import Hub, handler_for

# what a DNS-rebinding page sends: the attacker's own hostname, now resolving to 127.0.0.1
REBOUND = ["localhost.attacker.example:8765", "127.0.0.1.attacker.example:8765", "attacker.example",
           "user@127.0.0.1:8765", "localhost:8765:1", "127.0.0.1:abc", "", None]


@pytest.fixture(scope="module")
def port():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(Hub()))
    srv.block_on_close = False  # an open /stream handler must not hold up teardown
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1]
    srv.shutdown()
    srv.server_close()


def status(port, method, path, host, headers=(), body=None):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        c.putrequest(method, path, skip_host=True)
        if host is not None:
            c.putheader("Host", host)
        for k, v in headers:
            c.putheader(k, v)
        if body is not None:
            c.putheader("Content-Length", str(len(body)))
        c.endheaders(body)
        return c.getresponse().status
    finally:
        c.close()


@pytest.mark.parametrize("path", ["/", "/stream"])
@pytest.mark.parametrize("host", REBOUND)
def test_get_rejects_foreign_host(port, path, host):
    assert status(port, "GET", path, host) == 403


@pytest.mark.parametrize("path", ["/", "/stream"])
@pytest.mark.parametrize("host", ["127.0.0.1:{port}", "localhost:{port}", "LOCALHOST:{port}", "localhost"])
def test_get_allows_loopback_host(port, path, host):
    assert status(port, "GET", path, host.format(port=port)) == 200


def post(port, host):
    return status(port, "POST", "/api/calibrate", host, body=b"{}",
                  headers=[("Origin", f"http://{host}"), ("Content-Type", "application/json")])


def test_post_rejects_localhost_prefixed_host(port):
    assert post(port, "localhost.attacker.example:8765") == 403


def test_post_with_loopback_host_passes_host_check(port):
    assert post(port, f"127.0.0.1:{port}") == 409  # reaches the handler: no calibration job in replay mode
