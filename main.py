from fastapi import FastAPI, Request
from bus_botback import bot
import os
from dotenv import load_dotenv
from bus_botback import process_update_from_webhook
import uvicorn
import httpx
import requests

load_dotenv()

app = FastAPI()

BOT_TOKEN = os.getenv('TELE_TOKEN')
CLOUD_RUN_BASE_URL = os.getenv("WEBHOOK_URL")
WEBHOOK_URL = f"{CLOUD_RUN_BASE_URL}/{BOT_TOKEN}"

TELEGRAM_API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook"
print("📢 Loaded BOT_TOKEN:", BOT_TOKEN[:10] + "..." if BOT_TOKEN else "None")


@app.get("/")
def root():
    print("✅ Health check hit!")
    return {"message": "Telegram Bot is running on Cloud Run!", "status": "healthy"}


@app.get("/health")
def health_check():
    return {"status": "healthy", "bot_token_set": bool(BOT_TOKEN)}

@app.post(f"/{BOT_TOKEN}")
async def telegram_webhook(request: Request):
    print("🚨 Incoming Telegram webhook hit!")
    try:
        body = await request.body()
        print("📦 Processing webhook...")
        process_update_from_webhook(body.decode("utf-8"))
        return {"ok": True}
    except Exception as e:
        print("❌ Error processing webhook:", str(e))
        return {"error": str(e)}

@app.on_event("startup")
async def startup_event():
   async with httpx.AsyncClient() as client:
        response = await client.post(
            TELEGRAM_API_URL,
            json={"url": WEBHOOK_URL},
            headers={"Content-Type": "application/json"}
        )
        print("Webhook set response:", response.status_code, response.json())

# @app.on_event("startup")
# def set_webhook():
   # webhook_url = os.getenv("WEBHOOK_URL")
   # bot.remove_webhook()
   # bot.set_webhook(url=f"{webhook_url}/webhook")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"🚀 Starting server on port {port}")
    uvicorn.run("main:app", host="0.0.0.0", port=port)