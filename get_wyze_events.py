import os
import json
from datetime import datetime, timedelta
from wyze_sdk import Client
from wyze_sdk.errors import WyzeApiError

# Function to write data to JSON file
def write_tokens_to_file(access_token, refresh_token):
    data = {
        "access_token": access_token,
        "refresh_token": refresh_token
    }
    with open("wyze_credentials.json", 'w+') as json_file:
        json.dump(data, json_file, indent=4)

# Function to read data from JSON file
def read_tokens_from_file():
    with open("wyze_credentials.json", 'r') as json_file:
        data = json.load(json_file)
    return data.get('access_token'), data.get('refresh_token')

def populate_tokens():
    response = Client().login(
        email=os.environ['WYZE_EMAIL'],
        password=os.environ['WYZE_PASSWORD'],
        key_id=os.environ['WYZE_KEY_ID'],
        api_key=os.environ['WYZE_API_KEY']
    )
    write_tokens_to_file(response['access_token'], response['refresh_token'])

access_token, refresh_token = read_tokens_from_file()

if(access_token == ""):
    populate_tokens()
    access_token, refresh_token = read_tokens_from_file()

client = Client(token=access_token, refresh_token=refresh_token)

# Do a test of the current tokens
try:
    client.cameras.list()
except WyzeApiError as e:
    if(str(e).startswith("The access token has expired")):
        resp = client.refresh_token()
        write_tokens_to_file(resp.data['data']['access_token'], resp.data['data']['refresh_token'])
        access_token, refresh_token = read_tokens_from_file()
        client = Client(token=access_token, refresh_token=refresh_token)

# Pull all devices and build a map out of the mac address and the device name
devices = client.devices_list()
mac_map = {}
for device in devices:
    mac_map[device.mac] = device.nickname

twelve_hours_ago = datetime.now() - timedelta(hours=12)
output_format = []

try:
    for mac in mac_map.keys():
        events = client.events.list(device_ids=[mac], begin=twelve_hours_ago)
        for event in events:
            output_format.append(
                {
                    "camera_name": mac_map[event.mac],
                    "alarm_type": event.alarm_type.description,
                    "tags": [tag.description for tag in event.tags if tag is not None],
                    "time": event.time
                }
            )
except WyzeApiError as e:
    # You will get a WyzeApiError if the request failed
    print(f"Got an error: {e}")

print(json.dumps(output_format))
