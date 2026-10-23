import os
import uuid
import requests
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("VOICELY_API_KEY")

if not api_key:
    raise RuntimeError("VOICELY_API_KEY is missing from .env")

url = "https://tryvoicely.com/v1/text-to-speech/vly_m05"

text = (
    "السلام علیکم۔ ایچ بی ایل بینکنگ اسسٹنٹ میں خوش آمدید۔ "
    "بتائیے، آج میں آپ کی کس طرح مدد کر سکتا ہوں؟"
)

response = requests.post(
    url,
    params={
        "output_format": "mp3_44100_128"
    },
    headers={
        "xi-api-key": api_key,
        "Content-Type": "application/json",
        "Idempotency-Key": str(uuid.uuid4()),
    },
    json={
        "text": text,
        "model_id": "voicely-flash-v1",
        "language_code": "ur",
    },
    timeout=180,
)

if not response.ok:
    print("ERROR:", response.status_code)
    print(response.text)
    raise SystemExit()

with open("voicely_urdu_male_test.mp3", "wb") as f:
    f.write(response.content)

print("SUCCESS")
print("Created: voicely_urdu_male_test.mp3")
print(
    "Voice actually used:",
    response.headers.get("X-Voicely-Voice-Used")
)