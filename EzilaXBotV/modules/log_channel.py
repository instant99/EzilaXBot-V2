from datetime import datetime
from functools import wraps

from telegram.ext import CallbackContext

from EzilaXBotV.modules.helper_funcs.misc import is_module_loaded

FILENAME = __name__.rsplit(".", 1)[-1]

if is_module_loaded(FILENAME):
    from telegram import ParseMode, Update
    from telegram.error import BadRequest, Unauthorized
    from telegram.ext import CommandHandler, JobQueue, run_async
    from telegram.utils.helpers import escape_markdown

    from EzilaXBotV import EVENT_LOGS, LOGGER, dispatcher
    from EzilaXBotV.modules.helper_funcs.chat_status import user_admin
    from EzilaXBotV.modules.sql import log_channel_sql as sql

    def loggable(func):
        @wraps(func)
        def log_action(
            update: Update,
            context: CallbackContext,
            job_queue: JobQueue = None,
            *args,
            **kwargs,
        ):
            if not job_queue:
                result = func(update, context, *args, **kwargs)
            else:
                result = func(update, context, job_queue, *args, **kwargs)

            chat = update.effective_chat
            message = update.effective_message

            if result:
                datetime_fmt = "%H:%M - %d-%m-%Y"
                result += f"\n<b>Штамп события</b>: <code>{datetime.utcnow().strftime(datetime_fmt)}</code>"

                if message.chat.type == chat.SUPERGROUP and message.chat.username:
                    result += f'\n<b>Ссылка:</b> <a href="https://t.me/{chat.username}/{message.message_id}">click here</a>'
                log_chat = sql.get_chat_log_channel(chat.id)
                if log_chat:
                    send_log(context, log_chat, chat.id, result)

            return result

        return log_action

    def gloggable(func):
        @wraps(func)
        def glog_action(update: Update, context: CallbackContext, *args, **kwargs):
            result = func(update, context, *args, **kwargs)
            chat = update.effective_chat
            message = update.effective_message

            if result:
                datetime_fmt = "%H:%M - %d-%m-%Y"
                result += "\n<b>Штамп события</b>: <code>{}</code>".format(
                    datetime.utcnow().strftime(datetime_fmt)
                )

                if message.chat.type == chat.SUPERGROUP and message.chat.username:
                    result += f'\n<b>Ссылка:</b> <a href="https://t.me/{chat.username}/{message.message_id}">кликни здесь</a>'
                log_chat = str(EVENT_LOGS)
                if log_chat:
                    send_log(context, log_chat, chat.id, result)

            return result

        return glog_action

    def send_log(
        context: CallbackContext, log_chat_id: str, orig_chat_id: str, result: str
    ):
        bot = context.bot
        try:
            bot.send_message(
                log_chat_id,
                result,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except BadRequest as excp:
            if excp.message == "Чат не найден":
                bot.send_message(
                    orig_chat_id, "Этот канал с логами был удален - сброс настроек."
                )
                sql.stop_chat_logging(orig_chat_id)
            else:
                LOGGER.warning(excp.message)
                LOGGER.warning(result)
                LOGGER.exception("Не удалось разобрать")

                bot.send_message(
                    log_chat_id,
                    result
                    + "\n\nФорматирование было отключено из-за неожиданной ошибки.",
                )

    @run_async
    @user_admin
    def logging(update: Update, context: CallbackContext):
        bot = context.bot
        message = update.effective_message
        chat = update.effective_chat

        log_channel = sql.get_chat_log_channel(chat.id)
        if log_channel:
            log_channel_info = bot.get_chat(log_channel)
            message.reply_text(
                f"В этой группе есть все журналы, отправленные в:"
                f" {escape_markdown(log_channel_info.title)} (`{log_channel}`)",
                parse_mode=ParseMode.MARKDOWN,
            )

        else:
            message.reply_text("Для этой группы не был установлен канал с логами!")

    @run_async
    @user_admin
    def setlog(update: Update, context: CallbackContext):
        bot = context.bot
        message = update.effective_message
        chat = update.effective_chat
        if chat.type == chat.CHANNEL:
            message.reply_text(
                "Теперь перешлите /setlog в группу, к которой вы хотите привязать этот канал!"
            )

        elif message.forward_from_chat:
            sql.set_chat_log_channel(chat.id, message.forward_from_chat.id)
            try:
                message.delete()
            except BadRequest as excp:
                if excp.message == "Сообщение для удаления не найдено":
                    pass
                else:
                    LOGGER.exception(
                        "Ошибка удаления сообщения в канале с логами. Все равно должно сработать."
                    )

            try:
                bot.send_message(
                    message.forward_from_chat.id,
                    f"Это канал был установлен в качестве канала с логами для {chat.title or chat.first_name}.",
                )
            except Unauthorized as excp:
                if excp.message == "Запрещено: бот не является участником чата канала":
                    bot.send_message(chat.id, "Успешно настроен канал с логами!")
                else:
                    LOGGER.exception("Ошибка в настройке канала с логами.")

            bot.send_message(chat.id, "Канал с логами успешно настроен!")

        else:
            message.reply_text(
                "Для настройки канала с логами выполните следующие действия:\n"
                " - добавьте бота на нужный канал\n"
                " - отправьте /setlog в канал\n"
                " - перенаправьте /setlog в группу\n"
            )

    @run_async
    @user_admin
    def unsetlog(update: Update, context: CallbackContext):
        bot = context.bot
        message = update.effective_message
        chat = update.effective_chat

        log_channel = sql.stop_chat_logging(chat.id)
        if log_channel:
            bot.send_message(
                log_channel, f"Канал был отключен от {chat.title}"
            )
            message.reply_text("Канал с логами был отключен.")

        else:
            message.reply_text("Канал с логами еще не установлен!")

    def __stats__():
        return f"• {sql.num_logchannels()} log channels set."

    def __migrate__(old_chat_id, new_chat_id):
        sql.migrate_chat(old_chat_id, new_chat_id)

    def __chat_settings__(chat_id, user_id):
        log_channel = sql.get_chat_log_channel(chat_id)
        if log_channel:
            log_channel_info = dispatcher.bot.get_chat(log_channel)
            return f"This group has all it's logs sent to: {escape_markdown(log_channel_info.title)} (`{log_channel}`)"
        return "Канал с логами не установлен для этой группы!"

    __help__ = """
*Только для администраторов:*
✪ /logchannel*:* получить информацию о канале с логами
✪ /setlog*:* установить канал для логов.
✪ /unsetlog*:* убрать канал для логов.

*Настройка канала регистрации выполняется с помощью:*
 *1.* добавление бота на нужный канал (в качестве администратора!)
 *2.* отправка `/setlog ` в канале
 *3.* перенаправление `/setlog ` в группу
"""

    __mod_name__ = "Logger"

    LOG_HANDLER = CommandHandler("logchannel", logging)
    SET_LOG_HANDLER = CommandHandler("setlog", setlog)
    UNSET_LOG_HANDLER = CommandHandler("unsetlog", unsetlog)

    dispatcher.add_handler(LOG_HANDLER)
    dispatcher.add_handler(SET_LOG_HANDLER)
    dispatcher.add_handler(UNSET_LOG_HANDLER)

else:
    # run anyway if module not loaded
    def loggable(func):
        return func

    def gloggable(func):
        return func
