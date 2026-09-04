import httpx
import pprint as pp

PORT = "8088"
API_URL = "http://127.0.0.1:" + PORT

dev_token = "rl_live_8f2c1d94e6b74a03"

response = httpx.post(API_URL + "/v1/auth/token",
                   headers={"Authorization": f"Bearer {dev_token}"})
token = response.json()["access_token"]

response = httpx.get(API_URL + "/v1/orders",
                     params={"limit":5},
                     headers={"Authorization": f"Bearer {token}"})

pp.pprint(response.json()["data"][0])
