import os
import json
import ast
import logging
import time

import telebot
import gspread
from google.oauth2.service_account import Credentials
import google.generativeai as genai

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GOOGLE_CREDENTIALS_JSON = os.environ.get("GOOGLE_CREDENTIALS_JSON")
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")
SHEET_NAME = os.environ.get("SHEET_NAME", "السجل اليومي")

_missing = [n for n, v in {"TELEGRAM_TOKEN": TELEGRAM_TOKEN, "GEMINI_API_KEY": GEMINI_API_KEY, "GOOGLE_CREDENTIALS_JSON": GOOGLE_CREDENTIALS_JSON, "SPREADSHEET_ID": SPREADSHEET_ID}.items() if not v]
if _missing:
    raise EnvironmentError(f"متغيرات مفقودة: {', '.join(_missing)}")

bot = telebot.TeleBot(TELEGRAM_TOKEN, parse_mode=None)
genai.configure(api_key=GEMINI_API_KEY)
gemini_model = genai.GenerativeModel("gemini-1.5-flash")

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
    response = gemini_model.generate_content(prompt, generation_config=genai.types.GenerationConfig(temperature=0.1, max_output_tokens=2048))
    raw = response.text.strip().replace("```python","").replace("```","").strip()
    parsed = ast.literal_eval(raw)
    if not isinstance(parsed, list):
        raise ValueError("المخرج ليس قائمة")
    return [row + [""]*(10-len(row)) if len(row)<10 else row[:10] for row in parsed]

@bot.message_handler(commands=["start","help"])
def start(message):
    bot.reply_to(message, "مرحباً! أرسل لي أي نص يصف حركات الموقع وسأضيفها للجدول تلقائياً.\n\nأمثلة:\n- استلام 50 كيس أسمنت\n- صرف 10 متر حديد\n- فاتورة نقل 500 ريال")

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
