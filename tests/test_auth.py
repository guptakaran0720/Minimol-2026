import pytest

from node.auth import AuthError, sign_headers, sign_response, verify, verify_response

KEY = b"cluster-key-for-tests"


def test_round_trip():
    h = sign_headers(KEY, "node-a", "PUT", "/chunks/abc", b"body", now=1000)
    assert verify(KEY, "PUT", "/chunks/abc", h, b"body", now=1000) == "node-a"


def test_lowercase_headers_accepted():
    h = {k.lower(): v for k, v in sign_headers(KEY, "node-a", "GET", "/health", now=1000).items()}
    assert verify(KEY, "GET", "/health", h, b"", now=1000) == "node-a"


@pytest.mark.parametrize("change", ["key", "method", "path", "body", "node"])
def test_any_change_rejected(change):
    h = sign_headers(KEY, "node-a", "PUT", "/chunks/abc", b"body", now=1000)
    key, method, path, body = KEY, "PUT", "/chunks/abc", b"body"
    if change == "key":
        key = b"another-cluster-key!!"
    elif change == "method":
        method = "GET"
    elif change == "path":
        path = "/chunks/abd"
    elif change == "body":
        body = b"bodY"
    else:
        h["X-Node"] = "node-b"      # relabelling a captured request as another node
    with pytest.raises(AuthError):
        verify(key, method, path, h, body, now=1000)


def test_timestamp_window():
    h = sign_headers(KEY, "node-a", "GET", "/health", now=1000)
    assert verify(KEY, "GET", "/health", h, b"", now=1030)
    with pytest.raises(AuthError):
        verify(KEY, "GET", "/health", h, b"", now=1031)
    with pytest.raises(AuthError):
        verify(KEY, "GET", "/health", h, b"", now=969)


def test_missing_headers_rejected():
    with pytest.raises(AuthError):
        verify(KEY, "GET", "/health", {}, b"", now=1000)
    with pytest.raises(AuthError):
        verify(KEY, "GET", "/health", {"X-Node": "a", "X-Ts": "nope", "X-Sig": "00"}, b"", now=1000)


def test_response_signature():
    req_sig = sign_headers(KEY, "node-a", "GET", "/health", now=1000)["X-Sig"]
    sig = sign_response(KEY, 200, req_sig, "node-b", b"{}")
    headers = {"X-Node": "node-b", "X-Resp-Sig": sig}
    assert verify_response(KEY, 200, req_sig, headers, b"{}") == "node-b"
    for status, rsig, body in [(404, req_sig, b"{}"), (200, "other-request", b"{}"), (200, req_sig, b"[]")]:
        with pytest.raises(AuthError):
            verify_response(KEY, status, rsig, headers, body)
    with pytest.raises(AuthError):
        verify_response(KEY, 200, req_sig, {}, b"{}")
