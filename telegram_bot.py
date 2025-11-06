import os
import logging
import json
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler

# Настройка логирования для Render
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Состояния диалога
COLLECTING_DATA, ANALYZING = range(2)


class InteractiveBusinessBot:
    def __init__(self, token):
        self.token = token
        
        # Создаем папку data если её нет
        os.makedirs("data", exist_ok=True)
        
        self.db = self._init_database()
        self.user_sessions = {}

    def _init_database(self):
        """Инициализация базы данных"""
        try:
            from database.json_db import JSONDatabase
            return JSONDatabase("data/database.json")
        except ImportError as e:
            logger.warning(f"Не удалось импортировать JSONDatabase: {e}")
            class DummyDB:
                def add_parsed_source(self, data):
                    logger.info(f"Заглушка DB: {data}")
            return DummyDB()

    def _init_agents(self):
        """Инициализация агентов с правильными именами файлов"""
        try:
            # Исправляем имена файлов согласно вашей структуре
            from agents.data_collector import DataCollectorAgent
            from agents.data_analyzer import DataAnalyzerAgent  # data_analyses.py -> data_analyzer
            return DataCollectorAgent, DataAnalyzerAgent
        except ImportError as e:
            logger.error(f"Ошибка импорта агентов: {e}")
            # Создаем заглушки для тестирования
            class DataCollectorAgent:
                def start_conversation(self):
                    return "Расскажите о вашей бизнес-идее. В какой сфере вы планируете работать?"
                
                def process_user_input(self, user_input):
                    # Заглушка для тестирования
                    return "Какой у вас бюджет?", {"idea": user_input}
            
            class DataAnalyzerAgent:
                def __init__(self, db):
                    self.db = db
                
                def generate_advice(self, data):
                    return f"Рекомендации для вашей идеи: {data.get('idea', 'не указана')}"
            
            return DataCollectorAgent, DataAnalyzerAgent

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Начало диалога - команда /start"""
        user_id = update.effective_user.id

        try:
            DataCollectorAgent, _ = self._init_agents()
            collector = DataCollectorAgent()
            first_question = collector.start_conversation()

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

        except Exception as e:
            logger.error(f"Ошибка в start_command: {e}")
            await update.message.reply_text("❌ Произошла ошибка при запуске. Попробуйте позже.")
            return ConversationHandler.END

    async def handle_user_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка ответов пользователя в диалоге"""
        user_id = update.effective_user.id
        user_input = update.message.text

        if user_id not in self.user_sessions:
            await update.message.reply_text("Напишите /start чтобы начать консультацию")
            return COLLECTING_DATA

        session = self.user_sessions[user_id]
        collector = session['collector']

        try:
            next_question, collected_data = collector.process_user_input(user_input)

            if collected_data:
                session['collected_data'] = collected_data

                await update.message.reply_text(
                    "✅ *Данные собраны! Анализирую вашу бизнес-идею...*\n"
                    "⏳ Это займет 1-2 минуты",
                    parse_mode='Markdown'
                )

                await self._generate_analysis(update, collected_data, user_id)

                if user_id in self.user_sessions:
                    del self.user_sessions[user_id]

                return ConversationHandler.END
            else:
                await update.message.reply_text(next_question)
                return COLLECTING_DATA

        except Exception as e:
            logger.error(f"Ошибка обработки ввода: {e}")
            await update.message.reply_text("❌ Произошла ошибка. Давайте попробуем еще раз - /start")
            if user_id in self.user_sessions:
                del self.user_sessions[user_id]
            return ConversationHandler.END

    async def _generate_analysis(self, update: Update, user_data: dict, user_id: int):
        """Генерация анализа и рекомендаций"""
        try:
            _, DataAnalyzerAgent = self._init_agents()
            analyzer = DataAnalyzerAgent(self.db)

            await update.message.reply_chat_action(action="typing")

            advice = analyzer.generate_advice(user_data)

            response_text = f"""
🎯 *РЕКОМЕНДАЦИИ ДЛЯ ВАШЕГО БИЗНЕСА*

{advice}

---
💡 *Хотите проанализировать другую идею?* Напишите /start
            """

            if len(response_text) > 4096:
                parts = [response_text[i:i + 4096] for i in range(0, len(response_text), 4096)]
                for part in parts:
                    await update.message.reply_text(part, parse_mode='Markdown')
                    await update.message.reply_chat_action(action="typing")
            else:
                await update.message.reply_text(response_text, parse_mode='Markdown')

            self.db.add_parsed_source({
                "type": "telegram_user_query",
                "user_id": user_id,
                "data": user_data,
                "response_preview": advice[:200] + "..."
            })

            logger.info(f"Успешный анализ для пользователя {user_id}")

        except Exception as e:
            logger.error(f"Ошибка генерации анализа: {e}")
            await update.message.reply_text("❌ Произошла ошибка при анализе данных. Попробуйте еще раз - /start")

    async def cancel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Отмена диалога"""
        user_id = update.effective_user.id

        if user_id in self.user_sessions:
            del self.user_sessions[user_id]

        await update.message.reply_text("Диалог прерван. Если хотите начать заново - напишите /start")
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

            application.add_handler(conv_handler)
            application.add_handler(CommandHandler('help', self.help_command))
            application.add_handler(CommandHandler('cancel', self.cancel_command))
            application.add_error_handler(self.error_handler)

            logger.info("🤖 Бот запущен на Render!")
            application.run_polling(drop_pending_updates=True)

        except Exception as e:
            logger.error(f"❌ Критическая ошибка запуска: {e}")
            raise


def main():
    """Точка входа"""
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    
    if not BOT_TOKEN:
        logger.error("❌ Ошибка: BOT_TOKEN не найден")
        return

    bot = InteractiveBusinessBot(BOT_TOKEN)
    bot.run()


if __name__ == "__main__":
    main()
