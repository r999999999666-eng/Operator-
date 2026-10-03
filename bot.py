import asyncio
import logging
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import CommandStart, Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

# ----------------------------------------------------------------------
# НАСТРОЙКИ И ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ
# ----------------------------------------------------------------------
BOT_TOKEN = "ВАШ_ТОКЕН_БОТА"  # Вставьте токен от @BotFather
ADMIN_CHAT_ID = -1003899669062  # ID вашей группы операторов

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Счетчик тикетов и хранилище активных диалогов в памяти
# {ticket_id: {"user_id": int, "status": str}}
ticket_counter = 1
tickets = {}
# Быстрый поиск активного тикета по user_id
user_active_tickets = {}

# ----------------------------------------------------------------------
# КЛАВИАТУРЫ ОПЕРАТОРА
# ----------------------------------------------------------------------
def get_ticket_keyboard(ticket_id: int, status: str = "open"):
    if status == "open":
        btn = InlineKeyboardButton(text="🙋‍♂️ Взять в работу", callback_data=f"take_{ticket_id}")
    elif status == "in_progress":
        btn = InlineKeyboardButton(text="✅ Закрыть тикет", callback_data=f"close_{ticket_id}")
    else:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[btn]])

# ----------------------------------------------------------------------
# ХЕНДЛЕРЫ
# ----------------------------------------------------------------------

# 1. Команда /start для пользователя
@dp.message(CommandStart(), F.chat.type == "private")
async def start_cmd(message: types.Message):
    await message.answer(
        "👋 Здравствуйте!\n\n"
        "Отправьте ваш вопрос или файл (фото, документ, голосовое сообщение).\n"
        "Оператор поддержки ответит вам в ближайшее время."
    )

# 2. Обработка любых сообщений от пользователя (текст, фото, видео, файлы)
@dp.message(F.chat.type == "private")
async def handle_user_message(message: types.Message):
    global ticket_counter
    user_id = message.from_user.id

    # Если у пользователя нет активного тикета, создаем новый
    if user_id not in user_active_tickets:
        ticket_id = ticket_counter
        ticket_counter += 1
        tickets[ticket_id] = {"user_id": user_id, "status": "open"}
        user_active_tickets[user_id] = ticket_id

        # Служебное уведомление операторам о новом тикете в очереди
        user_info = f"@{message.from_user.username}" if message.from_user.username else message.from_user.full_name
        await bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=f"📥 **Новое обращение — Тикет #{ticket_id}**\n"
                 f"👤 Пользователь: {user_info} (ID: `{user_id}`)\n"
                 f"📌 Статус: 🟡 *В очереди*",
            parse_mode="Markdown",
            reply_markup=get_ticket_keyboard(ticket_id, "open")
        )

    # Копируем сообщение пользователя (со всеми фото/медиа/подписями) в чат операторов
    copied_msg = await bot.copy_message(
        chat_id=ADMIN_CHAT_ID,
        from_chat_id=user_id,
        message_id=message.message_id
    )

    await message.answer("✅ Сообщение доставлено в службу поддержки.")

# 3. Нажатие кнопок «Взять в работу» / «Закрыть тикет»
@dp.callback_query(F.message.chat.id == ADMIN_CHAT_ID)
async def process_ticket_action(callback: types.CallbackQuery):
    data = callback.data
    action, ticket_id_str = data.split("_")
    ticket_id = int(ticket_id_str)

    if ticket_id not in tickets:
        await callback.answer("Тикет не найден или уже закройте.", show_alert=True)
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
        
        # Уведомляем пользователя о закрытии тикета
        try:
            await bot.send_message(
                chat_id=user_id,
                text="ℹ️ Ваш тикет был закрыт оператором. Если у вас возникнут новые вопросы, просто напишите сообщение."
            )
        except Exception:
            pass

# 4. Ответ оператора пользователю (любой тип медиа/текст через Reply)
@dp.message(F.chat.id == ADMIN_CHAT_ID, F.reply_to_message)
async def reply_to_user(message: types.Message):
    original_message = message.reply_to_message

    # Определяем ID пользователя через пересланное сообщение
    target_user_id = None
    if original_message.forward_from:
        target_user_id = original_message.forward_from.id

    if target_user_id:
        try:
            # Копируем любая входящие фото, видео или текст напрямую пользователю
            await bot.copy_message(
                chat_id=target_user_id,
                from_chat_id=ADMIN_CHAT_ID,
                message_id=message.message_id
            )
            # Ставим реакцию «галочка» на ответ оператора
            await message.react([types.ReactionTypeEmoji(emoji="👍")])
        except Exception as e:
            logging.error(f"Ошибка отправки: {e}")
            await message.reply("❌ Не удалось доставить ответ пользователю (возможно, бот заблокирован).")
    else:
        await message.reply(
            "⚠️ Не удалось определить пользователя.\n"
            "Делайте **Ответить (Reply)** непосредственно на пересланное сообщение пользователя."
        )

# ----------------------------------------------------------------------
# ЗАПУСК БОТА
# ----------------------------------------------------------------------
async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("Операторский бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Бот остановлен.")
