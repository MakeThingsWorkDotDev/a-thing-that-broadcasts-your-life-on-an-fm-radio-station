import json
import os
import time
import requests
import imaplib
import email
from datetime import datetime, timedelta
from openai import OpenAI
from mutagen.mp3 import MP3
import subprocess
from pyhtcc import PyHTCC
from wyze_sdk import Client
from wyze_sdk.errors import WyzeApiError


class Broadcast:
    FILE_PATH = 'broadcast.json'

    def __init__(self, created_at='', events=None, script_prompt='', script='', audio_file='', error=''):
        if events is None:
            events = []
        self.created_at = created_at
        self.events = events
        self.script_prompt = script_prompt
        self.script = script
        self.audio_file = audio_file
        self.error = error

    @classmethod
    def load(cls):
        if not os.path.exists(cls.FILE_PATH):
            return cls()

        try:
            with open(cls.FILE_PATH, 'r') as f:
                data = json.load(f)
            return cls(**data)
        except (json.JSONDecodeError, FileNotFoundError):
            return cls()

    def save(self):
        with open(self.FILE_PATH, 'w') as f:
            json.dump(self.to_dict(), f, indent=2)
        return self

    def to_dict(self):
        return {
            'created_at': self.created_at,
            'events': self.events,
            'script_prompt': self.script_prompt,
            'script': self.script,
            'audio_file': self.audio_file,
            'error': self.error
        }


def ordinalize(number):
    abs_number = abs(int(number))

    if 11 <= abs_number % 100 <= 13:
        return f"{number}th"
    else:
        last_digit = abs_number % 10
        if last_digit == 1:
            return f"{number}st"
        elif last_digit == 2:
            return f"{number}nd"
        elif last_digit == 3:
            return f"{number}rd"
        else:
            return f"{number}th"


def get_weather_event():
    url = 'https://api.openweathermap.org/data/3.0/onecall'
    params = {
        'lat': os.environ['LATITUDE'],
        'lon': os.environ['LONGITUDE'],
        'appid': os.environ['OPENWEATHERMAP_API_KEY'],
        'units': 'imperial',
        'exclude': 'minutely,hourly'  # we only want daily forecasts
    }

    response = requests.get(url, params=params)
    if response.status_code != 200:
        return "Weather data unavailable"

    weather_data = response.json()
    current = weather_data["current"]
    today = weather_data["daily"][0]
    tomorrow = weather_data["daily"][1]
    right_now = datetime.fromtimestamp(current['dt'])

    parts = [
        'Today,',
        right_now.strftime(f"%A, %B the {ordinalize(right_now.day)}"),
        f"{today['summary']}.",
        f"Right now it's {round(current['temp'])} and feels like {round(current['feels_like'])}",
        f"with a low of {round(today['temp']['min'])}",
        f"with a high of {round(today['temp']['max'])}.",
        f"Tomorrow, {tomorrow['summary']}",
        f"and a high of {round(tomorrow['temp']['max'])} and a heat index of {round(tomorrow['feels_like']['day'])}"
    ]

    return ' '.join(parts)


def get_email_events():
    try:
        mail = imaplib.IMAP4_SSL(os.environ['IMAP_HOST'])
        mail.login(os.environ['IMAP_USERNAME'], os.environ['IMAP_PASSWORD'])
        mail.select('inbox')

        search_terms = ["Shipped", "Out for Delivery", "Delivered", "on its way", "shipped", "on the way"]

        # Search for each term individually and combine results
        # This avoids complex OR syntax issues in Python imaplib
        all_email_ids = set()

        for term in search_terms:
            try:
                # Search for the term (case-sensitive)
                status, messages = mail.search(None, 'SUBJECT', f'"{term}"')
                if status == 'OK' and messages[0]:
                    all_email_ids.update(messages[0].split())

                # Search for lowercase version if different
                if term != term.lower():
                    status, messages = mail.search(None, 'SUBJECT', f'"{term.lower()}"')
                    if status == 'OK' and messages[0]:
                        all_email_ids.update(messages[0].split())
            except:
                continue

        email_ids = list(all_email_ids)

        if not email_ids:
            mail.close()
            mail.logout()
            return []

        emails = []
        for email_id in email_ids:
            status, msg_data = mail.fetch(email_id, '(RFC822)')
            msg = email.message_from_bytes(msg_data[0][1])

            from_header = msg.get('From', '')
            subject = msg.get('Subject', '').encode('ascii', 'ignore').decode('ascii').strip()
            date_header = msg.get('Date', '')

            # Parse the date
            try:
                email_date = email.utils.parsedate_to_datetime(date_header)
                date_str = email_date.strftime('%m/%d/%y %I:%M:%S %p')
            except:
                date_str = date_header

            # Extract sender name (basic parsing)
            sender_name = from_header.split('<')[0].strip().strip('"') if '<' in from_header else from_header

            email_text = f"An email from {sender_name} with a subject of '{subject}' was received at {date_str}"
            emails.append(email_text)

        mail.close()
        mail.logout()
        return emails

    except Exception as e:
        print(f"Error getting email events: {e}")
        return []


def get_honeywell_status():
    try:
        p = PyHTCC(os.environ['HONEYWELL_USERNAME'], os.environ['HONEYWELL_PASSWORD'])
        zone = p.get_zone_by_name('THERMOSTAT')

        thermostat_data = {
            "temperature": zone.get_current_temperature_raw(),
            "mode": zone.get_system_mode().name
        }

        return f"The thermostat is set to {thermostat_data['mode']} and the indoor temperature is {thermostat_data['temperature']}"
    except Exception as e:
        print(f"Error getting thermostat status: {e}")
        return "Thermostat status unavailable"


def write_wyze_tokens_to_file(access_token, refresh_token):
    data = {
        "access_token": access_token,
        "refresh_token": refresh_token
    }
    with open("wyze_credentials.json", 'w+') as json_file:
        json.dump(data, json_file, indent=4)


def read_wyze_tokens_from_file():
    try:
        with open("wyze_credentials.json", 'r') as json_file:
            data = json.load(json_file)
        return data.get('access_token', ''), data.get('refresh_token', '')
    except FileNotFoundError:
        return '', ''


def populate_wyze_tokens():
    response = Client().login(
        email=os.environ['WYZE_EMAIL'],
        password=os.environ['WYZE_PASSWORD'],
        key_id=os.environ['WYZE_KEY_ID'],
        api_key=os.environ['WYZE_API_KEY']
    )
    write_wyze_tokens_to_file(response['access_token'], response['refresh_token'])


def get_camera_events():
    try:
        access_token, refresh_token = read_wyze_tokens_from_file()

        if not access_token:
            populate_wyze_tokens()
            access_token, refresh_token = read_wyze_tokens_from_file()

        client = Client(token=access_token, refresh_token=refresh_token)

        # Test current tokens
        try:
            client.cameras.list()
        except WyzeApiError as e:
            if str(e).startswith("The access token has expired"):
                resp = client.refresh_token()
                write_wyze_tokens_to_file(resp.data['data']['access_token'], resp.data['data']['refresh_token'])
                access_token, refresh_token = read_wyze_tokens_from_file()
                client = Client(token=access_token, refresh_token=refresh_token)

        # Pull all devices and build a map out of the mac address and the device name
        devices = client.devices_list()
        mac_map = {}
        for device in devices:
            mac_map[device.mac] = device.nickname

        twelve_hours_ago = datetime.now() - timedelta(hours=12)
        events = []

        for mac in mac_map.keys():
            wyze_events = client.events.list(device_ids=[mac], begin=twelve_hours_ago)
            for event in wyze_events:
                event_text = f"{mac_map[event.mac]} detected {event.alarm_type.description}"
                if event.tags:
                    verb = 'heard' if event.alarm_type.description.lower() == 'sound' else 'saw'
                    tags_text = ' and '.join([f"a {tag.description}" for tag in event.tags if tag is not None])
                    event_text = f"{event_text} and {verb} {tags_text}"
                events.append(event_text)

        return events

    except Exception as e:
        print(f"Error getting camera events: {e}")
        return []


def base_script_prompt():
    current_time = datetime.now().strftime('%I:00 %p')
    return f"""    In the style of a 1930's radio broadcaster, give a news update summarizing the below events.
    Do not include prompts, headers, or asterisks in the output.
    Do not read them all individually but group common events and summarize them.
    Do not include sound or music prompts. Mention that the broadcast is for the current time of {current_time}
    The news update should be verbose and loquacious but please do not refer to yourself as either.
    The station name is 1.101 Cozy Castle Radio and your radio broadcaster name is Hotsy Totsy Harry Fitzgerald.
    At some point in the broadcast advertise for a ridiculous fictional product from the 1930's or tell a joke, do not do both.
    Give an introduction to the news report and a sign off.
    Here are the events:"""


def generate_script(script_prompt):
    client = OpenAI(
        api_key=os.environ['OPENAI_ACCESS_TOKEN'],
        organization=os.environ['OPENAI_ORGANIZATION_ID']
    )

    response = client.chat.completions.create(
        model='gpt-4',
        messages=[{'role': 'user', 'content': script_prompt}]
    )

    return response.choices[0].message.content


def get_script_audio(text, filename):
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{os.environ['ELEVENLABS_VOICE_ID']}/stream"

    headers = {
        'xi-api-key': os.environ['ELEVENLABS_API_KEY'],
        'Content-Type': 'application/json',
        'Accept': 'audio/mpeg'
    }

    data = {
        'text': text,
        'model_id': 'eleven_monolingual_v1'
    }

    response = requests.post(url, headers=headers, json=data, stream=True)

    if response.status_code != 200:
        raise Exception(f"Non-success status code while streaming {response.status_code}")

    with open(filename, 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)

    return filename


def audio_length_in_seconds(file_path):
    if not os.path.exists(file_path):
        return 0

    try:
        audio = MP3(file_path)
        return int(audio.info.length)
    except:
        return 0


def mix_broadcast_audio(vocals_file, output_file):
    original_intro_outro_file = "radio_intro_outro.mp3"
    vocals_length = audio_length_in_seconds(vocals_file)
    intro_outro_length = audio_length_in_seconds(original_intro_outro_file)

    working_dir = 'work'
    intro_outro_file = f"{working_dir}/radio_intro_outro_resampled.mp3"
    padded_vocals_file = f"{working_dir}/padded_vocals.mp3"
    faded_intro_outro_file = f"{working_dir}/faded_intro_outro.mp3"
    padded_outro_file = f"{working_dir}/padded_outro.mp3"
    mixed_broadcast_file = f"{working_dir}/mixed_broadcast.wav"
    compressed_broadcast_file = f"{working_dir}/compressed_broadcast.wav"

    # create work directory and clear old file
    subprocess.run(["mkdir", "-p", "work"], check=False)
    subprocess.run(["rm", "-f", output_file], check=False)

    # resample file from Udio
    subprocess.run(["sox", original_intro_outro_file, intro_outro_file, "rate", "-h", "44100"], check=True)

    # pad vocals
    subprocess.run(["sox", vocals_file, padded_vocals_file, "pad", "10@0"], check=True)

    # fade intro outro
    subprocess.run(["sox", intro_outro_file, faded_intro_outro_file, "fade", "5", "25", "20"], check=True)

    # pad outro
    subprocess.run(["sox", faded_intro_outro_file, padded_outro_file, "pad", f"{vocals_length}@0"], check=True)

    # mix files
    subprocess.run([
        "sox", "-M",
        "-v", "0.3", faded_intro_outro_file,
        "-v", "1.2", padded_vocals_file,
        "-v", "0.4", padded_outro_file,
        mixed_broadcast_file
    ], check=True)

    # compress and fade in
    subprocess.run([
        "sox", mixed_broadcast_file, compressed_broadcast_file,
        "fade", "5", "compand", "0.3,1", "6:-70,-60,-20", "-5", "-90", "0.2", "norm", "-3"
    ], check=True)

    # wav to mono mp3
    subprocess.run(["sox", compressed_broadcast_file, output_file, "remix", "-"], check=True)

    # cleanup everything
    subprocess.run(["rm", "-rf", "work"], check=False)
    subprocess.run(["rm", "-f", "vocals_file.mp3"], check=False)

    return output_file


if __name__ == "__main__":
    start_time = time.time()
    print("Starting Broadcast Generation... 🎙️")

    record = Broadcast.load()
    record.created_at = datetime.now().isoformat()

    print("Collecting Weather Data ☀️")
    record.events.append(get_weather_event())

    print("Collecting Email Events 📧")
    record.events.extend(get_email_events())

    print("Collecting Camera Events 📹")
    record.events.extend(get_camera_events())

    print("Collecting Thermostat Status 🌡️")
    record.events.append(get_honeywell_status())

    record.script_prompt = f"{base_script_prompt()}\n{chr(10).join(record.events)}"

    print("Generating Script ✍️")
    record.script = generate_script(record.script_prompt)

    print("Getting Vocals 🎤")
    vocals_file = get_script_audio(record.script, "vocals_file.mp3")

    print("Mixing Audio 🎵")
    record.audio_file = mix_broadcast_audio(vocals_file, "broadcast.mp3")

    record.save()

    end_time = time.time()
    elapsed_time = round(end_time - start_time, 2)
    print(f"You're done! 🎉 (Completed in {elapsed_time} seconds)")