import logging
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from collections import OrderedDict
import datetime

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

class SeminarBot:
    def __init__(self):
        self.topics = {}  # {subject: {number: topic}}
        self.registrations = {}  # {subject: {number: (user_id, username, timestamp)}}
        self.current_subject = None
        self.waiting_for_topics = False

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /start"""
        user = update.effective_user
        await update.message.reply_text(
            f"Привет, {user.first_name}! Я бот для распределения семинарских тем.\n\n"
            "Доступные команды:\n"
            "/new_subject - начать новое распределение тем\n"
            "/view_topics - посмотреть текущие темы\n"
            "/results - показать результаты распределения\n"
            "/cancel - отменить текущую операцию"
        )

    async def new_subject(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Начать новое распределение тем"""
        self.waiting_for_topics = True
        self.current_subject = None
        self.registrations = {}
        
        await update.message.reply_text(
            "Введите название предмета для которого добавляете темы:",
            reply_markup=ReplyKeyboardRemove()
        )

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Отмена текущей операции"""
        self.waiting_for_topics = False
        await update.message.reply_text(
            "Операция отменена.",
            reply_markup=ReplyKeyboardRemove()
        )

    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка текстовых сообщений"""
        text = update.message.text.strip()
        user_id = update.effective_user.id
        username = update.effective_user.username or update.effective_user.first_name

        # Если ожидаем ввод названия предмета
        if self.waiting_for_topics and not self.current_subject:
            self.current_subject = text
            self.topics[self.current_subject] = {}
            self.registrations[self.current_subject] = {}
            self.waiting_for_topics = False
            
            await update.message.reply_text(
                f"Предмет '{text}' установлен. Теперь отправьте список тем в формате:\n"
                "1. Тема 1\n"
                "2. Тема 2\n"
                "3. Тема 3\n"
                "..."
            )
            return

        # Если ожидаем список тем
        elif self.current_subject and not self.topics[self.current_subject]:
            lines = text.split('\n')
            topics_dict = {}
            
            for line in lines:
                if '.' in line:
                    parts = line.split('.', 1)
                    try:
                        number = int(parts[0].strip())
                        topic = parts[1].strip()
                        topics_dict[number] = topic
                    except (ValueError, IndexError):
                        continue
            
            if topics_dict:
                self.topics[self.current_subject] = topics_dict
                
                # Формируем сообщение с темами
                topics_text = f"Темы для предмета '{self.current_subject}':\n\n"
                for num, topic in topics_dict.items():
                    topics_text += f"{num}. {topic}\n"
                
                topics_text += "\nЧтобы выбрать тему, отправьте номер нужной темы."
                
                await update.message.reply_text(topics_text)
            else:
                await update.message.reply_text("Не удалось распознать темы. Попробуйте еще раз.")
            return

        # Обработка выбора темы
        if self.current_subject and self.topics.get(self.current_subject):
            try:
                topic_number = int(text)
                topics = self.topics[self.current_subject]
                
                if topic_number not in topics:
                    await update.message.reply_text("Такого номера темы не существует.")
                    return
                
                # Проверяем, не занята ли уже тема
                if topic_number in self.registrations[self.current_subject]:
                    await update.message.reply_text("Эта тема уже занята!")
                    return
                
                # Записываем выбор пользователя
                timestamp = datetime.datetime.now()
                self.registrations[self.current_subject][topic_number] = (user_id, username, timestamp)
                
                await update.message.reply_text(
                    f"Вы выбрали тему {topic_number}: {topics[topic_number]}\n"
                    f"Время выбора: {timestamp.strftime('%H:%M:%S')}"
                )
                
            except ValueError:
                await update.message.reply_text("Пожалуйста, отправьте номер темы (цифру).")

    async def view_topics(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показать текущие темы"""
        if not self.current_subject or not self.topics.get(self.current_subject):
            await update.message.reply_text("Темы еще не добавлены.")
            return
        
        topics_text = f"Темы для предмета '{self.current_subject}':\n\n"
        for num, topic in self.topics[self.current_subject].items():
            status = "✅ Занята" if num in self.registrations[self.current_subject] else "❌ Свободна"
            topics_text += f"{num}. {topic} - {status}\n"
        
        await update.message.reply_text(topics_text)

    async def show_results(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показать результаты распределения"""
        if not self.current_subject or not self.registrations.get(self.current_subject):
            await update.message.reply_text("Еще никто не выбрал темы.")
            return
        
        # Сортируем по времени выбора
        sorted_registrations = sorted(
            self.registrations[self.current_subject].items(),
            key=lambda x: x[1][2]  # сортировка по timestamp
        )
        
        results_text = f"Результаты распределения тем по предмету '{self.current_subject}':\n\n"
        
        for topic_num, (user_id, username, timestamp) in sorted_registrations:
            topic_name = self.topics[self.current_subject][topic_num]
            time_str = timestamp.strftime('%H:%M:%S')
            results_text += f"{topic_num}. {topic_name}\n   👤 {username} (в {time_str})\n\n"
        
        await update.message.reply_text(results_text)

def main():
    """Запуск бота"""
    # Замените 'YOUR_BOT_TOKEN' на реальный токен
    TOKEN = "8405347117:AAG7h0qxePyQ9mXW3z03DBYOEWafOVP3oBI"
    
    # Создаем приложение
    application = Application.builder().token(TOKEN).build()
    
    # Создаем экземпляр бота
    bot = SeminarBot()
    
    # Добавляем обработчики
    application.add_handler(CommandHandler("start", bot.start))
    application.add_handler(CommandHandler("new_subject", bot.new_subject))
    application.add_handler(CommandHandler("view_topics", bot.view_topics))
    application.add_handler(CommandHandler("results", bot.show_results))
    application.add_handler(CommandHandler("cancel", bot.cancel))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_text))
    
    # Запускаем бота
    print("Бот запущен...")
    application.run_polling()

if __name__ == "__main__":
    main()
