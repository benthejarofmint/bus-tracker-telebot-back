from fastapi import FastAPI, Request
from bus_botback import bot
import os
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

@app.post("/webhook")
async def webhook_handler(request: Request):
    json_data = await request.json()
    update = bot.de_json(json_data)
    bot.process_new_updates([update])
    return {"ok": True}

@app.get("/")
def health_check():
    return {"status": "running"}

@app.on_event("startup")
def set_webhook():
    webhook_url = os.getenv("WEBHOOK_URL")
    bot.remove_webhook()
    bot.set_webhook(url=f"{webhook_url}/webhook")

