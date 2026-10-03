import os
import logging
from aiohttp import web
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart, Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

# ----------------------------------------------------------------------
# НАСТРОЙКИ
# ----------------------------------------------------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "-1003899669062"))
WEBHOOK_HOST = os.getenv("RENDER_EXTERNAL_URL")
WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"
PORT = int(os.getenv("PORT", 8080))

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Хранилища данных
msg_to_user = {}
ticket_counter = 1
tickets = {}
user_active_tickets = {}

# Список забаненных пользователей (ID)
banned_users = set()

# ----------------------------------------------------------------------
# КЛАВИАТУРЫ ДЛЯ ГРУППЫ ОПЕРАТОРОВ
# ----------------------------------------------------------------------
def get_operator_keyboard(user_id: int, ticket_id: int, status: str = "open"):
    buttons = []
    
    if status == "open":
        buttons.append([InlineKeyboardButton(text="🙋‍♂️ Взять в работу", callback_data=f"take_{ticket_id}_{user_id}")])
    elif status == "in_progress":
        buttons.append([
            InlineKeyboardButton(text="💬 Ответить", callback_data=f"info_{user_id}"),
            InlineKeyboardButton(text="✅ Заявка проверена", callback_data=f"approve_{ticket_id}_{user_id}")
        ])
        buttons.append([
            InlineKeyboardButton(text="🔴 Закрыть тикет", callback_data=f"close_{ticket_id}_{user_id}"),
            InlineKeyboardButton(text="⛔ Забанить игрока", callback_data=f"ban_{ticket_id}_{user_id}")
        ])
        
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# ----------------------------------------------------------------------
# ХЕНДЛЕРЫ ДЛЯ ПОЛЬЗОВАТЕЛЕЙ (В ЛС)
# ----------------------------------------------------------------------
@dp.message(CommandStart(), F.chat.type == "private")
async def start_cmd(message: types.Message):
    if message.from_user.id in banned_users:
        await message.answer("❌ Вы заблокированы и не можете использовать этого бота.")
        return
    await message.answer("👋 Здравствуйте! Напишите ваш вопрос или отправьте файл/заявку.")

@dp.message(F.chat.type == "private")
async def handle_user_message(message: types.Message):
    user_id = message.from_user.id

    # Проверка на бан
    if user_id in banned_users:
        await message.answer("❌ Вы заблокированы в системе поддержки.")
        return

    global ticket_counter

    # Создание тикета при новом обращении
    if user_id not in user_active_tickets:
        ticket_id = ticket_counter
        ticket_counter += 1
        tickets[ticket_id] = {"user_id": user_id, "status": "open"}
        user_active_tickets[user_id] = ticket_id

        user_info = f"@{message.from_user.username}" if message.from_user.username else message.from_user.full_name
        ticket_msg = await bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=f"📥 **Новое обращение — Тикет #{ticket_id}**\n"
                 f"👤 Игрок: {user_info} (ID: `{user_id}`)\n"
                 f"📌 Статус: 🟡 *В очереди*",
            parse_mode="Markdown",
            reply_markup=get_operator_keyboard(user_id, ticket_id, "open")
        )
        msg_to_user[ticket_msg.message_id] = user_id

    # Копируем сообщение игрока в чат операторов
    copied_msg = await bot.copy_message(
        chat_id=ADMIN_CHAT_ID,
        from_chat_id=user_id,
        message_id=message.message_id
    )

    # Прикрепляем кнопки быстрых действий под сообщение
    active_ticket_id = user_active_tickets[user_id]
    current_status = tickets[active_ticket_id]["status"]
    
    await bot.edit_message_reply_markup(
        chat_id=ADMIN_CHAT_ID,
        message_id=copied_msg.message_id,
        reply_markup=get_operator_keyboard(user_id, active_ticket_id, current_status)
    )

    msg_to_user[copied_msg.message_id] = user_id
    await message.answer("✅ Ваше сообщение/заявка доставлена оператору.")

# ----------------------------------------------------------------------
# ХЕНДЛЕРЫ КНОПОК И КОМАНД ОПЕРАТОРОВ
# ----------------------------------------------------------------------

# 1. Бан / Разбан по командам
@dp.message(F.chat.id == ADMIN_CHAT_ID, Command("ban"))
async def ban_command(message: types.Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("⚠ Формат: `/ban <ID_игрока>`", parse_mode="Markdown")
        return
    try:
        user_id = int(args[1])
        banned_users.add(user_id)
        await message.reply(f"⛔ Игрок `{user_id}` был успешно **забанен**.", parse_mode="Markdown")
    except ValueError:
        await message.reply("❌ ID должен быть числом.")

@dp.message(F.chat.id == ADMIN_CHAT_ID, Command("unban"))
async def unban_command(message: types.Message):
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("⚠ Формат: `/unban <ID_игрока>`", parse_mode="Markdown")
        return
    try:
        user_id = int(args[1])
        if user_id in banned_users:
            banned_users.remove(user_id)
            await message.reply(f"✅ Игрок `{user_id}` **разбанен**.", parse_mode="Markdown")
        else:
            await message.reply("ℹ️ Этот игрок не находился в бане.")
    except ValueError:
        await message.reply("❌ ID должен быть числом.")

# 2. Обработка нажатий на инлайн-кнопки
@dp.callback_query(F.message.chat.id == ADMIN_CHAT_ID)
async def process_operator_buttons(callback: types.CallbackQuery):
    data_parts = callback.data.split("_")
    action = data_parts[0]

    if action == "info":
        user_id = data_parts[1]
        await callback.answer(
            f"Для ответа сделайте Reply на сообщение игрока или введите: /reply {user_id} Ваш_текст", 
            show_alert=True
        )
        return

    ticket_id = int(data_parts[1])
    user_id = int(data_parts[2])
    operator_name = callback.from_user.full_name

    # Взять в работу
    if action == "take":
        if ticket_id in tickets:
            tickets[ticket_id]["status"] = "in_progress"
            
        await callback.message.edit_reply_markup(
            reply_markup=get_operator_keyboard(user_id, ticket_id, "in_progress")
        )
        await callback.answer("Вы взяли заявку в работу!")

    # Кнопка «Заявка проверена»
    elif action == "approve":
        try:
            await bot.send_message(
                chat_id=user_id,
                text="✅ **Ваша заявка успешно проверена!**\nЕсли у вас остались вопросы, напишите нам снова.",
                parse_mode="Markdown"
            )
        except Exception:
            pass

        if ticket_id in tickets:
            tickets[ticket_id]["status"] = "closed"
        if user_id in user_active_tickets and user_active_tickets[user_id] == ticket_id:
            del user_active_tickets[user_id]

        await callback.message.reply(
            f"✅ Оператор {operator_name} отметил: *Заявка игрока `{user_id}` проверена и закрыта.*",
            parse_mode="Markdown"
        )
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.answer("Уведомление отправлено!")

    # Кнопка «Закрыть тикет»
    elif action == "close":
        if ticket_id in tickets:
            tickets[ticket_id]["status"] = "closed"
        if user_id in user_active_tickets and user_active_tickets[user_id] == ticket_id:
            del user_active_tickets[user_id]

        try:
            await bot.send_message(chat_id=user_id, text="ℹ️ Ваш тикет был закрыт оператором.")
        except Exception:
            pass

        await callback.message.reply(f"🔴 Тикет #{ticket_id} закрыт оператором {operator_name}.")
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.answer("Тикет закрыт!")

    # Кнопка «Забанить игрока»
    elif action == "ban":
        banned_users.add(user_id)

        # Закрываем активный тикет
        if ticket_id in tickets:
            tickets[ticket_id]["status"] = "closed"
        if user_id in user_active_tickets and user_active_tickets[user_id] == ticket_id:
            del user_active_tickets[user_id]

        try:
            await bot.send_message(chat_id=user_id, text="⛔ **Вы были заблокированы в системе поддержки.**", parse_mode="Markdown")
        except Exception:
            pass

        await callback.message.reply(f"⛔ Оператор {operator_name} **забанил** игрока `{user_id}`.", parse_mode="Markdown")
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.answer("Игрок забанен!")

# 3. Ручной ответ командой: /reply ID Текст
@dp.message(F.chat.id == ADMIN_CHAT_ID, Command(commands=["reply", "r"]))
async def reply_by_command(message: types.Message):
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.reply("⚠ Формат: `/reply <ID_игрока> <текст ответа>`", parse_mode="Markdown")
        return

    try:
        target_user_id = int(args[1])
        reply_text = args[2]

        await bot.send_message(
            chat_id=target_user_id,
            text=f"🎧 **Ответ оператора:**\n\n{reply_text}",
            parse_mode="Markdown"
        )
        await message.react([types.ReactionTypeEmoji(emoji="👍")])
        await message.reply(f"✅ Ответ доставлен игроку `{target_user_id}`", parse_mode="Markdown")
    except Exception as e:
        logging.error(f"Ошибка /reply: {e}")
        await message.reply("❌ Не удалось доставить ответ игроку.")

# 4. Ответ оператора пользователю через Reply на сообщение
@dp.message(F.chat.id == ADMIN_CHAT_ID, F.reply_to_message)
async def reply_to_user(message: types.Message):
    if message.text and message.text.startswith(("/", "!", ".")):
        return

    reply_msg_id = message.reply_to_message.message_id
    target_user_id = None

    if reply_msg_id in msg_to_user:
        target_user_id = msg_to_user[reply_msg_id]
    elif message.reply_to_message.forward_from:
        target_user_id = message.reply_to_message.forward_from.id

    if target_user_id:
        try:
            copied_reply = await bot.copy_message(
                chat_id=target_user_id,
                from_chat_id=ADMIN_CHAT_ID,
                message_id=message.message_id
            )
            msg_to_user[copied_reply.message_id] = target_user_id
            await message.react([types.ReactionTypeEmoji(emoji="👍")])
        except Exception as e:
            logging.error(f"Ошибка доставки: {e}")
            await message.reply("❌ Не удалось доставить ответ игроку.")
    else:
        await message.reply("⚠️ Используйте кнопки под сообщением или команду `/reply <ID> <текст>`.")

# ----------------------------------------------------------------------
# ЗАПУСК WEBHOOK ДЛЯ RENDER
# ----------------------------------------------------------------------
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
