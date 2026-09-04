"""Tests for authentication endpoints."""


class TestAuth:
    """Test authentication flows."""

    def test_login_success(self, client):
        """Test successful login with admin credentials."""
        response = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "admin"}
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    def test_login_invalid_credentials(self, client):
        """Test login with invalid credentials."""
        response = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "wrong"}
        )
        assert response.status_code == 401

    def test_me_endpoint(self, client, auth_headers):
        """Test /api/v1/me endpoint."""
        response = client.get("/api/v1/me", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "admin"

    def test_me_without_token(self, client):
        """Test /api/v1/me without token."""
        response = client.get("/api/v1/me")
        assert response.status_code == 401

    def test_forgot_password(self, client):
        """Test forgot password endpoint."""
        response = client.post(
            "/api/v1/auth/forgot",
            json={"username": "admin", "email": "test@example.com"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "message" in data

    def test_forgot_password_nonexistent_user(self, client):
        """Test forgot password for nonexistent user (should still succeed for security)."""
        response = client.post(
            "/api/v1/auth/forgot",
            json={"username": "nonexistent", "email": "test@example.com"}
        )
        assert response.status_code == 200

    def test_history_requires_auth(self, client):
        """Test history endpoint requires authentication."""
        response = client.get("/api/v1/history")
        assert response.status_code == 401

    def test_history_with_auth(self, client, auth_headers):
        """Test history endpoint with authentication."""
        response = client.get("/api/v1/history", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "data" in data