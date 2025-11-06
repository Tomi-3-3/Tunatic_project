import os
import logging
import json
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler
from dotenv import load_dotenv

# Импортируем вашу существующую систему
from agents.data_collector import DataCollectorAgent
from agents.data_analyzer import DataAnalyzerAgent
from database.json_db import JSONDatabase

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Загружаем переменные окружения
load_dotenv()

# Состояния диалога
COLLECTING_DATA, ANALYZING = range(2)


class InteractiveBusinessBot:
    def __init__(self, token):
        self.token = token
        self.db = JSONDatabase("data/database.json")
        self.user_sessions = {}  # Храним сессии пользователей

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Начало диалога - команда /start"""
        user_id = update.effective_user.id

        # Создаем нового сборщика данных для пользователя
        collector = DataCollectorAgent()
        first_question = collector.start_conversation()

        # Сохраняем сессию пользователя
        self.user_sessions[user_id] = {
            'collector': collector,
            'collected_data': None
        }

        welcome_text = """
🤖 *Бизнес-Консультант AI*

Я помогу вам проанализировать бизнес-идею. Будем собирать информацию по шагам.

*Давайте начнем!*
        """

        await update.message.reply_text(welcome_text, parse_mode='Markdown')
        await update.message.reply_text(first_question)

        return COLLECTING_DATA

    async def handle_user_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка ответов пользователя в диалоге"""
        user_id = update.effective_user.id
        user_input = update.message.text

        # Проверяем активную сессию
        if user_id not in self.user_sessions:
            await update.message.reply_text("Напишите /start чтобы начать консультацию")
            return COLLECTING_DATA

        session = self.user_sessions[user_id]
        collector = session['collector']

        try:
            # Обрабатываем ввод пользователя
            next_question, collected_data = collector.process_user_input(user_input)

            if collected_data:
                # Данные собраны, переходим к анализу
                session['collected_data'] = collected_data

                await update.message.reply_text(
                    "✅ *Данные собраны! Анализирую вашу бизнес-идею...*\n"
                    "⏳ Это займет 1-2 минуты",
                    parse_mode='Markdown'
                )

                # Запускаем анализ
                await self._generate_analysis(update, collected_data, user_id)

                # Завершаем диалог
                if user_id in self.user_sessions:
                    del self.user_sessions[user_id]

                return ConversationHandler.END

            else:
                # Задаем следующий вопрос
                await update.message.reply_text(next_question)
                return COLLECTING_DATA

        except Exception as e:
            logger.error(f"Ошибка обработки ввода: {e}")
            await update.message.reply_text(
                "❌ Произошла ошибка. Давайте попробуем еще раз - /start"
            )
            return ConversationHandler.END

    async def _generate_analysis(self, update: Update, user_data: dict, user_id: int):
        """Генерация анализа и рекомендаций"""
        try:
            # Создаем анализатор
            analyzer = DataAnalyzerAgent(self.db)

            # Показываем действие "печатает"
            await update.message.reply_chat_action(action="typing")

            # Генерируем рекомендации
            advice = analyzer.generate_advice(user_data)

            # Форматируем ответ
            response_text = f"""
🎯 *РЕКОМЕНДАЦИИ ДЛЯ ВАШЕГО БИЗНЕСА*

{advice}

---
💡 *Хотите проанализировать другую идею?* Напишите /start
            """

            # Отправляем результат (разбиваем на части если слишком длинный)
            if len(response_text) > 4096:
                # Разбиваем на части по 4096 символов
                parts = [response_text[i:i + 4096] for i in range(0, len(response_text), 4096)]
                for part in parts:
                    await update.message.reply_text(part, parse_mode='Markdown')
                    await update.message.reply_chat_action(action="typing")
            else:
                await update.message.reply_text(response_text, parse_mode='Markdown')

            # Сохраняем в базу данных
            self.db.add_parsed_source({
                "type": "telegram_user_query",
                "user_id": user_id,
                "data": user_data,
                "response_preview": advice[:200] + "..."
            })

            logger.info(f"Успешный анализ для пользователя {user_id}")

        except Exception as e:
            logger.error(f"Ошибка генерации анализа: {e}")
            await update.message.reply_text(
                "❌ Произошла ошибка при анализе данных. Попробуйте еще раз - /start"
            )

    async def cancel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Отмена диалога"""
        user_id = update.effective_user.id

        # Удаляем сессию пользователя
        if user_id in self.user_sessions:
            del self.user_sessions[user_id]

        await update.message.reply_text(
            "Диалог прерван. Если хотите начать заново - напишите /start"
        )
        return ConversationHandler.END

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда помощи"""
        help_text = """
📖 *Помощь по боту:*

/start - Начать новую бизнес-консультацию
/help - Показать эту справку
/cancel - Прервать текущий диалог

*Как работает консультация:*
1. Я задаю вопросы по одному о вашей бизнес-идее
2. Вы отвечаете на них последовательно
3. После сбора всех данных я анализирую и даю развернутые рекомендации
4. Время анализа: 1-2 минуты

*Собираемая информация:*
- Сфера деятельности
- Конкретная идея
- Город/регион  
- Бюджет
- Опыт в сфере
- Целевая аудитория
- Особые пожелания
        """
        await update.message.reply_text(help_text, parse_mode='Markdown')

    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик ошибок"""
        logger.error(f"Ошибка в боте: {context.error}")

        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id if update else None,
                text="❌ Произошла техническая ошибка. Попробуйте позже."
            )
        except Exception:
            pass

    def run(self):
        """Запуск бота"""
        try:
            application = Application.builder().token(self.token).build()

            # Создаем ConversationHandler для управления диалогом
            conv_handler = ConversationHandler(
                entry_points=[CommandHandler('start', self.start_command)],
                states={
                    COLLECTING_DATA: [
                        MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_user_input)
                    ],
                },
                fallbacks=[
                    CommandHandler('cancel', self.cancel_command),
                    CommandHandler('help', self.help_command)
                ]
            )

            # Регистрируем обработчики
            application.add_handler(conv_handler)
            application.add_handler(CommandHandler('help', self.help_command))
            application.add_handler(CommandHandler('cancel', self.cancel_command))

            # Добавляем обработчик ошибок
            application.add_error_handler(self.error_handler)

            # Запускаем бота
            print("🤖 Бот с интерактивным диалогом запущен!")
            print("💬 Бот будет задавать вопросы по одному, как в консольной версии")

            application.run_polling(
                drop_pending_updates=True,
                allowed_updates=['message', 'callback_query']
            )

        except Exception as e:
            print(f"❌ Критическая ошибка запуска: {e}")


def main():
    """Точка входа"""
    BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

    if not BOT_TOKEN:
        print("❌ Ошибка: TELEGRAM_BOT_TOKEN не найден в .env файле")
        return

    bot = InteractiveBusinessBot(BOT_TOKEN)
    bot.run()


if __name__ == "__main__":
    main()