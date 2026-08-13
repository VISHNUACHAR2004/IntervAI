from dotenv import load_dotenv;
from google import genai
import os

load_dotenv()

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
resp = client.models.generate_content(model="gemini-3.6-flash", contents="say ok")
print(resp.text)