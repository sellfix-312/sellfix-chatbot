import os
import re
import requests
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
from supabase import create_client, Client

app = Flask(__name__)

LINE_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN', 'dummy_token')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET', 'dummy_secret')
DIFY_API_KEY = os.environ.get('DIFY_API_KEY', '')
DIFY_API_URL = "https://api.dify.ai/v1"
SUPABASE_URL = os.environ.get('SUPABASE_URL', '')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY', '')

line_bot_api = LineBotApi(LINE_ACCESS_TOKEN)
line_webhook = WebhookHandler(LINE_CHANNEL_SECRET)

try:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
except Exception:
    supabase = None

def remove_think_tag(text):
    if not text:
        return ""
    pattern = r"<think>.*?</think>"
    cleaned_text = re.sub(pattern, "", text, flags=re.DOTALL)
    return cleaned_text.strip()

def send_loading_animation(user_id):
    url = "https://api.line.me/v2/bot/chat/loading/start"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LINE_ACCESS_TOKEN}"
    }
    payload = {
        "chatId": user_id,
        "loadingSeconds": 60
    }
    try:
        requests.post(url, headers=headers, json=payload, timeout=2)
    except Exception:
        pass

def save_message_to_db(user_id, msg):
    if not supabase:
        return
    try:
        data = {"user_id": user_id, "message": msg}
        supabase.table("message_store").insert(data).execute()
    except Exception:
        pass

def get_recent_messages(user_id, limit=50):
    if not supabase:
        return []
    try:
        response = supabase.table("message_store")\
            .select("message")\
            .eq("user_id", user_id)\
            .order("created_at", desc=True)\
            .limit(limit)\
            .execute()
        messages = [row['message'] for row in response.data]
        return messages[::-1]
    except Exception:
        return []

def get_saved_conversation_id(user_id):
    if not supabase:
        return ""
    try:
        response = supabase.table("session_store").select("conversation_id").eq("user_id", user_id).execute()
        if response.data:
            return response.data[0]['conversation_id']
    except Exception:
        pass
    return ""

def save_conversation_id(user_id, conv_id):
    if not supabase:
        return
    try:
        data = {"user_id": user_id, "conversation_id": conv_id}
        supabase.table("session_store").upsert(data).execute()
    except Exception:
        pass

def call_dify(query, user_id, history_context):
    if not DIFY_API_KEY:
        return "Error: Dify API Key is not set."

    headers = {
        'Authorization': f'Bearer {DIFY_API_KEY}',
        'Content-Type': 'application/json'
    }

    conversation_id = get_saved_conversation_id(user_id)

    if history_context:
        context_str = "\n".join(history_context)
        final_query = f"【前情提要 - 這些是我們剛剛的討論，請參考】：\n{context_str}\n\n【現在使用者的問題】：\n{query}"
    else:
        final_query = query

    payload = {
        "inputs": {},
        "query": final_query,
        "response_mode": "blocking",
        "user": user_id,
        "conversation_id": conversation_id
    }

    try:
        response = requests.post(f"{DIFY_API_URL}/chat-messages", headers=headers, json=payload, timeout=60)
        response.raise_for_status()

        data = response.json()
        new_conv_id = data.get('conversation_id')
        
        if new_conv_id and new_conv_id != conversation_id:
            save_conversation_id(user_id, new_conv_id)

        raw_answer = data.get('answer', '')
        return remove_think_tag(raw_answer)
    except Exception:
        return "Partner is currently unavailable, please check the system."

@app.route("/")
def home():
    status = "Connected to Database" if supabase else "Database Error"
    return f"Sellfix Partner Bot is Running. Status: {status}"

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)

    try:
        line_webhook.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    except Exception:
        abort(500)
    return 'OK'

@line_webhook.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_msg = event.message.text.strip()
    user_id = event.source.user_id
    
    if event.source.type == 'group':
        user_id = event.source.group_id
    elif event.source.type == 'room':
        user_id = event.source.room_id

    TRIGGER_KEYWORDS = ["#ai", "@sellfix chatbot"]
    is_triggered = any(k in user_msg.lower() for k in TRIGGER_KEYWORDS)

    if not is_triggered:
        save_message_to_db(user_id, f"User: {user_msg}")
        return

    if is_triggered:
        send_loading_animation(user_id)

        history = get_recent_messages(user_id, limit=5)
        dify_reply = call_dify(user_msg, user_id, history)
        
        save_message_to_db(user_id, f"AI: {dify_reply}")

        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=dify_reply)
        )

if __name__ == "__main__":
    app.run()