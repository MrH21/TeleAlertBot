import requests
from requests.auth import HTTPBasicAuth
import time


class PayPalClient:
    def __init__(self, client_id, secret, sandbox=True):
        # Use REST API hostnames
        self.base_url = (
            "https://api-m.sandbox.paypal.com" if sandbox else "https://api-m.paypal.com"
        )
        self.client_id = client_id
        self.secret = secret
        self.access_token = None
        self.token_expires_at = 0
        self.get_access_token()

    def get_access_token(self):
        # Simple caching for access token until it expires
        if self.access_token and time.time() < self.token_expires_at - 60:
            return self.access_token

        response = requests.post(
            f"{self.base_url}/v1/oauth2/token",
            auth=HTTPBasicAuth(self.client_id, self.secret),
            data={"grant_type": "client_credentials"},
        )
        response.raise_for_status()
        payload = response.json()
        self.access_token = payload["access_token"]
        expires_in = int(payload.get("expires_in", 3300))
        self.token_expires_at = time.time() + expires_in
        return self.access_token

    def verify_webhook_signature(
        self,
        transmission_id,
        transmission_time,
        cert_url,
        auth_algo,
        transmission_sig,
        webhook_id,
        webhook_event,
    ):
        """Verify PayPal webhook signature using PayPal API.

        Returns True if verification_status == 'SUCCESS'.
        """
        self.get_access_token()

        url = f"{self.base_url}/v1/notifications/verify-webhook-signature"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.access_token}",
        }
        body = {
            "auth_algo": auth_algo,
            "cert_url": cert_url,
            "transmission_id": transmission_id,
            "transmission_sig": transmission_sig,
            "transmission_time": transmission_time,
            "webhook_id": webhook_id,
            "webhook_event": webhook_event,
        }

        resp = requests.post(url, json=body, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        return data.get("verification_status") == "SUCCESS"
