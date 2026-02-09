# api/index.py
import os
import json
import requests
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)

LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
DIFY_API_KEY = os.environ.get('DIFY_API_KEY')
DIFY_API_URL = "https://api.dify.ai/v1"

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

def call_dify(query, user_id):
    headers = {
        'Authorization': f'Bearer {DIFY_API_KEY}',
        'Content-Type': 'application/json'
    }
    payload = {
        "inputs": {},
        "query": query,
        "response_mode": "blocking",
        "conversation_id": "",
        "user": user_id
    }
    
    try:
        response = requests.post(f"{DIFY_API_URL}/chat-messages", headers=headers, json=payload)
        response.raise_for_status()
        return response.json().get('answer', 'Dify 沒有回應')
    except Exception as e:
        print(f"Error calling Dify: {e}")
        return "連線失敗，請檢查後台。"

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_msg = event.message.text.strip()
    user_id = event.source.user_id

    TRIGGER_KEYWORDS = ["/"] 
    
    is_triggered = any(k in user_msg for k in TRIGGER_KEYWORDS)
    
    if is_triggered:
        print(f"Triggered by {user_id}: {user_msg}")
        dify_reply = call_dify(user_msg, user_id)
        
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=dify_reply)
        )
    else:
        print(f"[LOG] {user_id} said: {user_msg}")
        pass

if __name__ == "__main__":
    app.run()