import httpx
import time
import json


PORT = "8088"
API_URL = "http://127.0.0.1:" + PORT

DEV_TOKEN = "rl_live_8f2c1d94e6b74a03"

def auth_to_API(client: httpx.Client):
    resp = client.post(API_URL + "/v1/auth/token",
                   headers={"Authorization": f"Bearer {DEV_TOKEN}"})
    live_token = resp.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {live_token}"

client = httpx.Client(base_url=API_URL, timeout=10,
                      mounts={"all://localhost": None,
                              "all://127.0.0.1": None})
auth_to_API(client)

cursor = None
page = 1
max_retries = 5
orders = []

while True:
    if cursor is None:
        resp = client.get("v1/orders", params={"limit":5})
    else:
        resp = client.get("v1/orders", params={"limit":5, "cursor":cursor})
    tries = 0
    while tries < max_retries:
        if resp.status_code == 200: 
            break
        if resp.status_code == 401:
            auth_to_API(client)
        elif (resp.status_code == 429) | (resp.status_code == 500):
            time.sleep(0.2)
        resp = client.get("v1/orders",
            params={"limit":5, "cursor":cursor})
        tries+=1
    print(f"Page {page} done, next cursor {cursor}")
    orders.extend(resp.json()["data"])
    print(f"Added {len(resp.json()["data"])} records")
    print(f"Total is {len(orders)} orders")
    page+=1
    cursor = resp.json()["next_cursor"]
    print(cursor)
    # breakpoint()
    if cursor is None:
        break

# breakpoint()

with open("orders_sample.jsonl", "w") as f:
    for order in orders:
        f.write(json.dumps(order) + "\n")