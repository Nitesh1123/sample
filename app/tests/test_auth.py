def test_register_and_login(client):
    resp = client.post("/auth/register", json={"email": "a@b.com", "password": "pass1234"})
    assert resp.status_code == 201
    assert "access_token" in resp.json()

    resp2 = client.post("/auth/login", data={"username": "a@b.com", "password": "pass1234"})
    assert resp2.status_code == 200
    assert "access_token" in resp2.json()


def test_register_duplicate_email(client):
    client.post("/auth/register", json={"email": "dup@b.com", "password": "pass1234"})
    resp = client.post("/auth/register", json={"email": "dup@b.com", "password": "pass1234"})
    assert resp.status_code == 400


def test_login_wrong_password(client):
    client.post("/auth/register", json={"email": "c@d.com", "password": "pass1234"})
    resp = client.post("/auth/login", data={"username": "c@d.com", "password": "wrong"})
    assert resp.status_code == 401


def test_protected_route_requires_auth(client):
    resp = client.get("/documents")
    assert resp.status_code == 401
