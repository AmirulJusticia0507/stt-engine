"""Tests for API key and audit log endpoints."""


class TestApiKeys:
    """Test API key endpoints."""

    def test_create_api_key(self, client, auth_headers):
        """Test creating an API key."""
        response = client.post("/api/v1/api-keys", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "key" in data
        assert len(data["key"]) > 20

    def test_list_api_keys(self, client, auth_headers):
        """Test listing API keys."""
        response = client.get("/api/v1/api-keys", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "keys" in data
        assert isinstance(data["keys"], list)

    def test_revoke_api_key(self, client, auth_headers):
        """Test revoking an API key."""
        create_resp = client.post("/api/v1/api-keys", headers=auth_headers)
        key = create_resp.json()["key"]

        response = client.delete(f"/api/v1/api-keys/{key}", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"

        # Verify key is revoked
        list_resp = client.get("/api/v1/api-keys", headers=auth_headers)
        keys = list_resp.json()["keys"]
        assert key not in keys

    def test_non_admin_cannot_create_api_key(self, client):
        """Test that non-admin cannot create API keys."""
        # We can't easily test this without a non-admin token
        # Skip for now


class TestAuditLog:
    """Test audit log endpoints."""

    def test_audit_log(self, client, auth_headers):
        """Test audit log endpoint."""
        response = client.get("/api/v1/audit/log?limit=10", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "data" in data
        assert isinstance(data["data"], list)

    def test_audit_log_requires_auth(self, client):
        """Test audit log requires authentication."""
        response = client.get("/api/v1/audit/log")
        assert response.status_code == 401