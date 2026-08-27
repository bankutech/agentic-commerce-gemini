import os
from google import genai

client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
for m in client.models.list():
    if "gemini" in m.name:
        print(m.name)
