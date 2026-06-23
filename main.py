import os
import json
import ast
import logging
import time

import telebot
import gspread
from google.oauth2.service_account import Credentials
from groq import Groq

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GOOGLE_CREDENTIALS_JSON = os.environ.get("GOOGLE_CREDENTIALS_JSON", "")
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "")
SHEET_NAME = os.environ.get("SHEET_NAME", "السجل اليومي")

logger.info(f"TELEGRAM_TOKEN present: {bool(TELEGRAM_TOKEN)}")
logger.info(f"GEMINI_API_KEY present: {bool(GEMINI_API_KEY)}")
logger.info(f"GOOGLE_CREDENTIALS_JSON present: {bool(GOOGLE_CREDENTIALS_JSON)}")
logger.info(f"SPREADSHEET_ID present: {bool(SPREADSHEET_ID)}")

if not all([TELEGRAM_TOKEN, GEMINI_API_KEY, GOOGLE_CREDENTIALS_JSON, SPREADSHEET_ID]):
    missing = [k for k,v in {"TELEGRAM_TOKEN":TELEGRAM_TOKEN,"GEMINI_API_KEY":GEMINI_API_KEY,"GOOGLE_CREDENTIALS_JSON":GOOGLE_CREDENTIALS_JSON,"SPREADSHEET_ID":SPREADSHEET_ID}.items() if not v]
    logger.error(f"متغيرات مفقودة: {missing}")
    time.sleep(60)
    raise EnvironmentError(f"متغيرات مفقودة: {', '.join(missing)}")

bot = telebot.TeleBot(TELEGRAM_TOKEN, parse_mode=None)
groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY", ""))
SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]

def get_sheet():
    creds = Credentials.from_service_account_info(json.loads(GOOGLE_CREDENTIALS_JSON), scopes=SCOPES)
    client = gspread.authorize(creds)
    spreadsheet = client.open_by_key(SPREADSHEET_ID)
    try:
        return spreadsheet.worksheet(SHEET_NAME)
    except gspread.exceptions.WorksheetNotFound:
        sheet = spreadsheet.add_worksheet(title=SHEET_NAME, rows="1000", cols="10")
        sheet.append_rows([["التاريخ","الوقت","نوع الحركة","البند / الوصف","الكمية","الوحدة","المورد / الجهة","رقم الفاتورة","القيمة","ملاحظات"]], value_input_option="USER_ENTERED")
        return sheet

SYSTEM_PROMPT = """أنت محرك استخراج بيانات. حوّل النص إلى Python List of Lists فقط بدون أي نص إضافي أو markdown.
كل حركة = قائمة من 10 عناصر: [التاريخ, الوقت, نوع_الحركة, البند, الكمية, الوحدة, المورد, رقم_الفاتورة, القيمة, ملاحظات]
نوع_الحركة يجب أن يكون أحد هذه فقط: استلام مواد، صرف مواد، استلام فاتورة، حدث يومي
القيم الغير موجودة = نص فارغ ""
المخرج يجب أن يكون قابلاً لـ ast.literal_eval مباشرة."""

def parse_gemini(text):
    prompt = f"{SYSTEM_PROMPT}\n\nالنص:\n{text}"
    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
        max_tokens=2048,
    )
    raw = response.choices[0].message.content.strip().replace("```python","").replace("```","").strip()
    parsed = ast.literal_eval(raw)
    if not isinstance(parsed, list):
        raise ValueError("المخرج ليس قائمة")
    return [row + [""]*(10-len(row)) if len(row)<10 else row[:10] for row in parsed]

@bot.message_handler(commands=["start","help"])
def start(message):
    bot.reply_to(message, "مرحباً! أرسل لي أي نص يصف حركات الموقع وسأضيفها للجدول تلقائياً.")

@bot.message_handler(commands=["status"])
def status(message):
    try:
        sheet = get_sheet()
        bot.reply_to(message, f"✅ الاتصال يعمل\nالورقة: {SHEET_NAME}\nالصفوف: {len(sheet.get_all_values())}")
    except Exception as e:
        bot.reply_to(message, f"❌ خطأ: {str(e)[:200]}")

@bot.message_handler(func=lambda m: m.text and not m.text.startswith("/"))
def handle(message):
    msg = bot.reply_to(message, "⏳ جاري التحليل...")
    try:
        rows = parse_gemini(message.text)
        get_sheet().append_rows(rows, value_input_option="USER_ENTERED")
        result = f"✅ تمت إضافة {len(rows)} حركة:\n"
        for r in rows:
            result += f"• [{r[2]}] {r[3]}\n"
        bot.edit_message_text(result, message.chat.id, msg.message_id)
    except Exception as e:
        bot.edit_message_text(f"❌ خطأ: {str(e)[:200]}", message.chat.id, msg.message_id)
        logger.exception(e)

def main():
    logger.info("🚀 البوت يعمل...")
    while True:
        try:
            bot.infinity_polling(timeout=30, long_polling_timeout=30)
        except Exception as e:
            logger.error(f"انقطع الاتصال: {e}")
            time.sleep(10)

if __name__ == "__main__":
    main()
