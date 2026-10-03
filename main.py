import os
import logging
from aiohttp import web
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "-1003899669062"))
WEBHOOK_HOST = os.getenv("RENDER_EXTERNAL_URL")
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"
PORT = int(os.getenv("PORT", 8080))

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Хранилище: ID сообщения в группе -> ID пользователя
msg_to_user = {}

# Хранилище тикетов
ticket_counter = 1
tickets = {}
user_active_tickets = {}

def get_ticket_keyboard(ticket_id: int, status: str = "open"):
    if status == "open":
        btn = InlineKeyboardButton(text="🙋‍♂️ Взять в работу", callback_data=f"take_{ticket_id}")
    elif status == "in_progress":
        btn = InlineKeyboardButton(text="✅ Закрыть тикет", callback_data=f"close_{ticket_id}")
    else:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[btn]])

@dp.message(CommandStart(), F.chat.type == "private")
async def start_cmd(message: types.Message):
    await message.answer("👋 Здравствуйте! Напишите ваш вопрос или отправьте файл.")

# 1. Прием любого сообщения от пользователя
@dp.message(F.chat.type == "private")
async def handle_user_message(message: types.Message):
    global ticket_counter
    user_id = message.from_user.id

    # Создание тикета при первом обращении
    if user_id not in user_active_tickets:
        ticket_id = ticket_counter
        ticket_counter += 1
        tickets[ticket_id] = {"user_id": user_id, "status": "open"}
        user_active_tickets[user_id] = ticket_id

        user_info = f"@{message.from_user.username}" if message.from_user.username else message.from_user.full_name
        await bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=f"📥 **Новое обращение — Тикет #{ticket_id}**\n"
                 f"👤 Пользователь: {user_info} (ID: `{user_id}`)\n"
                 f"📌 Статус: 🟡 *В очереди*",
            parse_mode="Markdown",
            reply_markup=get_ticket_keyboard(ticket_id, "open")
        )

    # Копируем сообщение пользователя в группу
    copied_msg = await bot.copy_message(
        chat_id=ADMIN_CHAT_ID,
        from_chat_id=user_id,
        message_id=message.message_id
    )

    # ЗАПОМИНАЕМ: ID скопированного сообщения в группе = user_id
    msg_to_user[copied_msg.message_id] = user_id

    await message.answer("✅ Сообщение доставлено оператору.")

# 2. Обработка кнопок тикета
@dp.callback_query(F.message.chat.id == ADMIN_CHAT_ID)
async def process_ticket_action(callback: types.CallbackQuery):
    data = callback.data
    action, ticket_id_str = data.split("_")
    ticket_id = int(ticket_id_str)

    if ticket_id not in tickets:
        await callback.answer("Тикет не найден.", show_alert=True)
        return

    ticket = tickets[ticket_id]
    user_id = ticket["user_id"]
    operator_name = callback.from_user.full_name

    if action == "take":
        ticket["status"] = "in_progress"
        await callback.message.edit_text(
            f"📥 **Тикет #{ticket_id}**\n"
            f"👤 Пользователь: ID `{user_id}`\n"
            f"📌 Статус: 🟢 *В работе* (Оператор: {operator_name})",
            parse_mode="Markdown",
            reply_markup=get_ticket_keyboard(ticket_id, "in_progress")
        )
        await callback.answer("Вы взяли тикет в работу!")

    elif action == "close":
        ticket["status"] = "closed"
        if user_id in user_active_tickets and user_active_tickets[user_id] == ticket_id:
            del user_active_tickets[user_id]

        await callback.message.edit_text(
            f"📥 **Тикет #{ticket_id}**\n"
            f"👤 Пользователь: ID `{user_id}`\n"
            f"📌 Статус: 🔴 *Закрыт* (Оператор: {operator_name})",
            parse_mode="Markdown"
        )
        await callback.answer("Тикет закрыт!")
        try:
            await bot.send_message(chat_id=user_id, text="ℹ️ Ваш тикет был закрыт.")
        except Exception:
            pass

# 3. ОТВЕТ ОПЕРАТОРА (Работает ВСЕГДА)
@dp.message(F.chat.id == ADMIN_CHAT_ID, F.reply_to_message)
async def reply_to_user(message: types.Message):
    reply_msg_id = message.reply_to_message.message_id
    target_user_id = None

    # Шаг А: Ищем ID пользователя в нашем словаре по ID сообщения
    if reply_msg_id in msg_to_user:
        target_user_id = msg_to_user[reply_msg_id]
    
    # Шаг Б: Если сообщение было переслано и у юзера открыт профиль
    elif message.reply_to_message.forward_from:
        target_user_id = message.reply_to_message.forward_from.id

    # Отправляем ответ
    if target_user_id:
        try:
            copied_reply = await bot.copy_message(
                chat_id=target_user_id,
                from_chat_id=ADMIN_CHAT_ID,
                message_id=message.message_id
            )
            # Связываем и ответное сообщение тоже
            msg_to_user[copied_reply.message_id] = target_user_id
            await message.react([types.ReactionTypeEmoji(emoji="👍")])
        except Exception as e:
            logging.error(f"Ошибка доставки: {e}")
            await message.reply("❌ Не удалось доставить ответ (пользователь заблокировал бота).")
    else:
        await message.reply("⚠️ Не удалось определить адресата. Делайте Reply непосредственно на сообщение пользователя.")

async def on_startup(bot: Bot):
    await bot.set_webhook(WEBHOOK_URL)
    logging.info(f"Webhook запущен: {WEBHOOK_URL}")

def main():
    dp.startup.register(on_startup)
    app = web.Application()
    webhook_requests_handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    webhook_requests_handler.register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)
    web.run_app(app, host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    main()
