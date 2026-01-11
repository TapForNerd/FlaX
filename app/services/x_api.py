import requests


class XApiClient:
    def __init__(self, base_url, bearer_token):
        self.base_url = base_url.rstrip("/")
        self.bearer_token = bearer_token

    def _headers(self):
        if not self.bearer_token:
            return None
        return {"Authorization": f"Bearer {self.bearer_token}"}

    def get_me(self):
        headers = self._headers()
        if not headers:
            return {"error": "X_BEARER_TOKEN is not configured."}
        response = requests.get(
            f"{self.base_url}/users/me",
            headers=headers,
            timeout=10,
            params={"user.fields": "id,name,username,created_at"},
        )
        return {
            "status_code": response.status_code,
            "data": response.json() if response.headers.get("Content-Type", "").startswith("application/json") else response.text,
        }

    def get_me_with_token(self, access_token):
        response = requests.get(
            f"{self.base_url}/users/me",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
            params={"user.fields": "id,name,username,created_at"},
        )
        return {
            "status_code": response.status_code,
            "data": response.json() if response.headers.get("Content-Type", "").startswith("application/json") else response.text,
            "response": response,
        }
