import logging
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters, ConversationHandler
from collections import OrderedDict
import datetime
import re

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Константы для состояний ConversationHandler
SETTING_TIME, CANCELING_REGISTRATION = range(2)

class SeminarBot:
    def __init__(self):
        self.topics = {}  # {subject: {number: topic}}
        self.registrations = {}  # {subject: {number: (user_id, username, timestamp)}}
        self.current_subject = None
        self.waiting_for_topics = False
        self.start_time = None  # Время начала распределения
        self.admin_id = None  # ID администратора (можно установить через переменную окружения или конфиг)
        
        # Установите ID администратора здесь или через переменные окружения
        self.admin_id = 1074399585  # Замените на реальный ID администратора

    def is_admin(self, user_id):
        """Проверяет, является ли пользователь администратором"""
        return user_id == self.admin_id

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /start"""
        user = update.effective_user
        await update.message.reply_text(
            f"Привет, {user.first_name}! Я бот для распределения семинарских тем.\n\n"
            "Доступные команды:\n"
            "/new_subject - начать новое распределение тем\n"
            "/view_topics - посмотреть текущие темы\n"
            "/results - показать результаты распределения\n"
            "/set_start_time - установить время начала распределения (только для админа)\n"
            "/cancel_registration - отменить выбор темы (только для админа)\n"
            "/cancel - отменить текущую операцию"
        )

    async def new_subject(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Начать новое распределение тем"""
        self.waiting_for_topics = True
        self.current_subject = None
        self.registrations = {}
        self.start_time = None
        
        await update.message.reply_text(
            "Введите название предмета для которого добавляете темы:",
            reply_markup=ReplyKeyboardRemove()
        )

    async def set_start_time(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Установить время начала распределения (только для админа)"""
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text("Эта команда доступна только администратору.")
            return
        
        await update.message.reply_text(
            "Введите время начала распределения в формате ЧЧ:ММ (например, 14:30):"
        )
        return SETTING_TIME

    async def handle_set_time(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка ввода времени начала"""
        time_input = update.message.text.strip()
        
        # Проверяем формат времени
        time_pattern = r'^([0-1]?[0-9]|2[0-3]):([0-5][0-9])$'
        if not re.match(time_pattern, time_input):
            await update.message.reply_text("Неверный формат времени. Используйте ЧЧ:ММ (например, 14:30)")
            return SETTING_TIME
        
        # Устанавливаем время начала
        now = datetime.datetime.now()
        hours, minutes = map(int, time_input.split(':'))
        self.start_time = now.replace(hour=hours, minute=minutes, second=0, microsecond=0)
        
        if self.start_time < now:
            self.start_time = self.start_time + datetime.timedelta(days=1)
        
        await update.message.reply_text(
            f"Время начала распределения установлено: {self.start_time.strftime('%d.%m.%Y %H:%M')}"
        )
        return ConversationHandler.END

    async def cancel_registration(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Начать процесс отмены регистрации (только для админа)"""
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text("Эта команда доступна только администратору.")
            return ConversationHandler.END
        
        if not self.current_subject or not self.registrations.get(self.current_subject):
            await update.message.reply_text("Нет активных регистраций для отмены.")
            return ConversationHandler.END
        
        # Показываем список занятых тем
        occupied_text = "Занятые темы:\n\n"
        for topic_num, (user_id, username, timestamp) in self.registrations[self.current_subject].items():
            topic_name = self.topics[self.current_subject][topic_num]
            occupied_text += f"{topic_num}. {topic_name} - @{username} ({timestamp.strftime('%H:%M:%S')})\n"
        
        occupied_text += "\nВведите номер темы для отмены регистрации:"
        
        await update.message.reply_text(occupied_text)
        return CANCELING_REGISTRATION

    async def handle_cancel_registration(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка отмены регистрации"""
        try:
            topic_num = int(update.message.text.strip())
            
            if topic_num not in self.registrations[self.current_subject]:
                await update.message.reply_text("Этот номер темы не занят или не существует.")
                return CANCELING_REGISTRATION
            
            # Удаляем регистрацию
            user_id, username, timestamp = self.registrations[self.current_subject].pop(topic_num)
            topic_name = self.topics[self.current_subject][topic_num]
            
            await update.message.reply_text(
                f"Регистрация на тему {topic_num}. {topic_name} отменена.\n"
                f"Пользователь: @{username}"
            )
            
        except ValueError:
            await update.message.reply_text("Пожалуйста, введите номер темы (цифру).")
            return CANCELING_REGISTRATION
        
        return ConversationHandler.END

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Отмена текущей операции"""
        self.waiting_for_topics = False
        await update.message.reply_text(
            "Операция отменена.",
            reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END

    def is_distribution_started(self):
        """Проверяет, началось ли распределение тем"""
        if self.start_time is None:
            return True  # Если время не установлено, разрешаем сразу
        
        now = datetime.datetime.now()
        return now >= self.start_time

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
                
                if self.start_time:
                    topics_text += f"\nРаспределение начнется: {self.start_time.strftime('%d.%m.%Y %H:%M')}"
                topics_text += "\n\nЧтобы выбрать тему, отправьте номер нужной темы."
                
                await update.message.reply_text(topics_text)
            else:
                await update.message.reply_text("Не удалось распознать темы. Попробуйте еще раз.")
            return

        # Обработка выбора темы
        if self.current_subject and self.topics.get(self.current_subject):
            # Проверяем, началось ли распределение
            if not self.is_distribution_started():
                time_left = self.start_time - datetime.datetime.now()
                hours, remainder = divmod(time_left.total_seconds(), 3600)
                minutes, seconds = divmod(remainder, 60)
                
                await update.message.reply_text(
                    f"Распределение тем еще не началось!\n"
                    f"Осталось: {int(hours)}ч {int(minutes)}м {int(seconds)}с\n"
                    f"Начало: {self.start_time.strftime('%d.%m.%Y %H:%M')}"
                )
                return
            
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
        
        if self.start_time:
            if self.is_distribution_started():
                topics_text += f"\n✅ Распределение началось: {self.start_time.strftime('%d.%m.%Y %H:%M')}"
            else:
                time_left = self.start_time - datetime.datetime.now()
                hours, remainder = divmod(time_left.total_seconds(), 3600)
                minutes, seconds = divmod(remainder, 60)
                topics_text += f"\n⏰ До начала: {int(hours)}ч {int(minutes)}м {int(seconds)}с"
        
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
    
    # Создаем ConversationHandler для административных команд
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("set_start_time", bot.set_start_time),
            CommandHandler("cancel_registration", bot.cancel_registration)
        ],
        states={
            SETTING_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_set_time)],
            CANCELING_REGISTRATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_cancel_registration)]
        },
        fallbacks=[CommandHandler("cancel", bot.cancel)]
    )
    
    # Добавляем обработчики
    application.add_handler(CommandHandler("start", bot.start))
    application.add_handler(CommandHandler("new_subject", bot.new_subject))
    application.add_handler(CommandHandler("view_topics", bot.view_topics))
    application.add_handler(CommandHandler("results", bot.show_results))
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("cancel", bot.cancel))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_text))
    
    # Запускаем бота
    print("Бот запущен...")
    application.run_polling()

if __name__ == "__main__":
    main()
