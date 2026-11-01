import ipaddress

from fastapi.testclient import TestClient

from node.config import Settings, user_api_client_ok
from node.main import create_app


def settings(tmp_path, **kw):
    return Settings(node_id="node-1", host_id="host-1", cluster_key=b"k" * 32, data_dir=tmp_path / "data",
                    advertise_addr="127.0.0.1:8001", mdns=False, **kw)


def test_user_api_client_ok():
    docker = [ipaddress.ip_network("172.28.0.0/16")]
    assert user_api_client_ok("127.0.0.1", [])
    assert user_api_client_ok("::1", [])
    assert not user_api_client_ok("192.168.1.20", [])
    assert not user_api_client_ok("172.28.0.1", [])
    assert user_api_client_ok("172.28.0.1", docker)
    assert not user_api_client_ok("10.0.0.5", docker)
    assert not user_api_client_ok("testclient", docker)
    assert not user_api_client_ok(None, docker)


def test_user_api_allow_parsed_from_env(tmp_path):
    s = Settings.from_env({"CLUSTER_KEY": "x" * 20, "DATA_DIR": str(tmp_path), "NODE_ID": "n",
                           "USER_API_ALLOW": "172.28.0.0/16, 10.1.2.3"})
    assert [str(n) for n in s.user_api_allow] == ["172.28.0.0/16", "10.1.2.3/32"]
    assert Settings.from_env({"CLUSTER_KEY": "x" * 20, "DATA_DIR": str(tmp_path), "NODE_ID": "n"}).user_api_allow == []


def test_dashboard_served_at_ui_with_root_redirect(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>Minimol Storage</title>")
    monkeypatch.setenv("UI_DIR", str(dist))
    c = TestClient(create_app(settings(tmp_path)))
    assert "Minimol Storage" in c.get("/ui/").text
    r = c.get("/", follow_redirects=False)
    assert r.status_code in (307, 302) and r.headers["location"] == "/ui/"


def test_user_api_rejects_non_local_clients(tmp_path, monkeypatch):
    monkeypatch.setenv("UI_DIR", str(tmp_path / "missing"))
    c = TestClient(create_app(settings(tmp_path)))     # TestClient's host is "testclient"
    assert c.get("/stats").status_code == 403
