import os
import time
import threading
from flask import Flask
import telebot
from telebot import types

# 1. НАСТРОЙКИ И ПЕРЕМЕННЫЕ
TOKEN = os.environ.get("BOT_TOKEN", "СЮДА_ВСТАВИТЬ_ТОКЕН")
MANAGER_ID = int(os.environ.get("MANAGER_ID", "8957913298"))

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# --- ВЕБ-СЕРВЕР ДЛЯ RENDER ---
@app.route('/')
def home():
    return "Bot Manager is running!", 200

# --- КЛАВИАТУРЫ ---
def main_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("💬 Написать менеджеру")
    markup.add("ℹ️ О нас")
    return markup

def back_keyboard():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("🔙 Главное меню")
    return markup

# --- ХЕНДЛЕРЫ БОТА ---
@bot.message_handler(commands=['start'])
def start_cmd(message):
    text = "👋 Здравствуйте! Я бот-помощник.\n\nНажмите кнопку ниже, чтобы связаться с нашим менеджером."
    bot.send_message(message.chat.id, text, reply_markup=main_keyboard())

@bot.message_handler(func=lambda msg: msg.text == "ℹ️ О нас")
def about_cmd(message):
    text = "ℹ️ Информация о нас:\n\nМы работаем 24/7 и готовы ответить на любые ваши вопросы!"
    bot.send_message(message.chat.id, text, reply_markup=main_keyboard())

@bot.message_handler(func=lambda msg: msg.text == "🔙 Главное меню")
def back_cmd(message):
    start_cmd(message)

@bot.message_handler(func=lambda msg: msg.text == "💬 Написать менеджеру")
def ask_manager_cmd(message):
    text = "📝 Напишите ваше сообщение (или отправьте фото/файл), и менеджер ответит вам в ближайшее время:"
    bot.send_message(message.chat.id, text, reply_markup=back_keyboard())
    bot.register_next_step_handler(message, forward_to_manager)

def forward_to_manager(message):
    if message.text == "🔙 Главное меню":
        start_cmd(message)
        return

    info_text = f"📩 <b>Новое обращение!</b>\nОт: {message.from_user.first_name} (@{message.from_user.username or 'нет_юзернейма'})\nID: <code>{message.chat.id}</code>"
    bot.send_message(MANAGER_ID, info_text, parse_mode="HTML")
    bot.forward_message(MANAGER_ID, message.chat.id, message.message_id)
    bot.send_message(message.chat.id, "✅ Ваше сообщение отправлено! Ожидайте ответа.", reply_markup=main_keyboard())

# Ответ менеджера пользователю (через Reply / Ответить)
@bot.message_handler(func=lambda msg: msg.chat.id == MANAGER_ID and msg.reply_to_message is not None)
def reply_to_user(message):
    try:
        target_user_id = message.reply_to_message.forward_from.id
        bot.send_message(target_user_id, f"👨‍💻 <b>Ответ менеджера:</b>\n\n{message.text}", parse_mode="HTML")
        bot.send_message(MANAGER_ID, "✅ Ответ отправлен пользователю!")
    except Exception as e:
        bot.send_message(MANAGER_ID, f"❌ Ошибка отправки (возможно, у юзера скрыт профиль): {e}")

# --- ФУНКЦИЯ ЗАПУСКА ПОЛЛИНГА ---
def run_bot():
    print("🚀 Бот запущен...")
    try:
        bot.remove_webhook(drop_pending_updates=True)
        time.sleep(1)
    except Exception as e:
        print(f"Ошибка при сбросе вебхука: {e}")
        
    while True:
        try:
            bot.polling(none_stop=True, interval=2, timeout=30)
        except Exception as e:
            print(f"Ошибка сети: {e}. Перезапуск...")
            time.sleep(5)

# Фоновый запуск бота
bot_thread = threading.Thread(target=run_bot, daemon=True)
bot_thread.start()

# Запуск Flask сервера для Render
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
