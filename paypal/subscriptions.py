import requests

def create_subscription(client, plan_id, return_url, cancel_url):
    # refresh token each time (safe + simple)
    client.get_access_token()

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {client.access_token}"
    }

    data = {
        "plan_id": plan_id,
        "application_context": {
            "brand_name": "QuantAlert",
            "return_url": return_url,
            "cancel_url": cancel_url,
            "user_action": "SUBSCRIBE_NOW"
        }
    }

    response = requests.post(
        f"{client.base_url}/v1/billing/subscriptions",
        json=data,
        headers=headers
    )

    response.raise_for_status()

    result = response.json()

    approval_url = next(
        link["href"] for link in result["links"]
        if link["rel"] == "approve"
    )

    return {
        "subscription_id": result["id"],
        "approval_url": approval_url
    }
