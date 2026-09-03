export no_proxy="localhost,127.0.0.1"

PORT=8088
BASE=http://127.0.0.1:$PORT


echo "==========TOKEN AND CONNEXION=========="

LAB_TOKEN=$(grep '^token' lab.toml | cut -d '"' -f2)
TOKEN=$(curl -s -X POST "$BASE/v1/auth/token" -H "Authorization: Bearer $LAB_TOKEN" | jq -r .access_token)
echo $TOKEN

echo "==========PAYLOAD=========="

curl -s "$BASE/v1/orders?limit=5" -H "Authorization: Bearer $TOKEN" | jq > order_sample.json
echo "keys of the payload :"
cat order_sample.json | jq 'keys'
echo "some keys from the first data item of the payload:"
cat order_sample.json | jq '.data[0] | {order_id, channel}'
echo "length of the data item of the payload"
jq '.data | length' order_sample.json

echo "=====TOTAL LENGTH OF THE PAYLOAD======="
curl -s "$BASE/v1/orders" -H "Authorization: Bearer $TOKEN" | jq '.data | length'


# curl -s "$BASE/v1/orders/ORD-00000005?as_of=2026-01-02T04:49:47" -H "Authorization: Bearer $TOKEN" | jq
# curl -s "$BASE/v1/orders?limit=5" -H "Authorization: Bearer $TOKEN" | jq '{data, as_of}'


# curl -s "$BASE/v1/orders?limit=5" -H "Authorization: Bearer $TOKEN" | jq > page1.json
# CURSOR=$(jq -r '.next_cursor' page1.json)
# curl -s "$BASE/v1/orders?limit=5&cursor=$CURSOR" -H "Authorization: Bearer $TOKEN" | jq > page2.json
# jq '.next_cursor' page2.json
# jq '.cursor' page2.json
# echo $CURSOR