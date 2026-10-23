import os
import requests
from dotenv import load_dotenv

# Load variables from .env
load_dotenv()

API_KEY = os.getenv("CARTESIA_API_KEY")

if not API_KEY:
    raise RuntimeError(
        "CARTESIA_API_KEY was not found in your .env file."
    )

URL = "https://api.cartesia.ai/tts/bytes"

headers = {
    "Content-Type": "application/json",
    "X-API-Key": API_KEY,
    "Cartesia-Version": "2026-08-14",
}

payload = {
    "model_id": "sonic-3.6",

    "transcript": (
        "السلام علیکم۔ "
        "ایچ بی ایل بینکنگ اسسٹنٹ میں خوش آمدید۔ "
        "بتائیے، آج میں آپ کی کس طرح مدد کر سکتا ہوں؟"
    ),

    "voice": "db6b0ed5-d5d3-463d-ae85-518a07d3c2b4",

    "output_format": {
        "container": "wav",
        "encoding": "pcm_s16le",
        "sample_rate": 44100
    },

    "locale": "ur",

    "generation_config": {
        "speed": 1,
        "volume": 1
    }
}

print("Generating Cartesia Urdu voice...")

try:
    response = requests.post(
        URL,
        headers=headers,
        json=payload,
        timeout=60
    )

    if response.status_code != 200:
        print("ERROR:", response.status_code)
        print(response.text)
        raise SystemExit(1)

    with open("cartesia_hbl_test.wav", "wb") as f:
        f.write(response.content)

    print("SUCCESS!")
    print("Created: cartesia_hbl_test.wav")

except requests.RequestException as error:
    print("Connection error:")
    print(error)