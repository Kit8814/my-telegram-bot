import logging
import os
import asyncio
from telegram import Update, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters, ConversationHandler
import datetime
import re

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Константы для состояний ConversationHandler
(
    WAITING_SUBJECT_NAME, 
    WAITING_TOPICS_LIST,
    WAITING_FOR_SUBJECT_TIME,
    SETTING_DATE,
    SETTING_TIME,
    CANCELING_REGISTRATION,
    SELECTING_SUBJECT_FOR_REMOVAL,
    SELECTING_TOPIC_FOR_REMOVAL
) = range(8)

class SeminarBot:
    def __init__(self):
        self.topics = {}
        self.registrations = {}
        self.start_times = {}
        self.admin_id = 1074399585

    def is_admin(self, user_id):
        return user_id == self.admin_id

    def get_local_time(self):
        """Получаем текущее время с учетом часового пояса Москвы (UTC+3)"""
        utc_now = datetime.datetime.utcnow()
        msk_offset = datetime.timedelta(hours=3)
        return utc_now + msk_offset

    def format_time_left(self, time_left):
        """Форматирует оставшееся время в читаемый вид"""
        days = time_left.days
        total_seconds = int(time_left.total_seconds())
        hours = (total_seconds // 3600) % 24
        minutes = (total_seconds // 60) % 60
        
        if days > 0:
            return f"{days} дн. {hours} ч. {minutes} м."
        elif hours > 0:
            return f"{hours} ч. {minutes} м."
        else:
            return f"{minutes} м."

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        await update.message.reply_text(
            f"Привет, {user.first_name}! Я бот для распределения семинарских тем.\n\n"
            "Доступные команды:\n"
            "/new_subject - начать новое распределение тем\n"
            "/view_topics - посмотреть текущие темы\n"
            "/results - показать результаты распределения\n"
            "/set_subject_time - установить дату и время начала (админ)\n"
            "/cancel_registration - отменить выбор темы (админ)\n"
            "/remove_user - удалить участника с темы (админ)\n"
            "/list_subjects - показать все предметы\n"
            "/cancel - отменить текущую операцию"
        )

    async def new_subject(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text(
            "Введите название предмета:",
            reply_markup=ReplyKeyboardRemove()
        )
        return WAITING_SUBJECT_NAME

    async def handle_subject_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        subject_name = update.message.text.strip()
        
        if not subject_name:
            await update.message.reply_text("Название предмета не может быть пустым. Попробуйте еще раз:")
            return WAITING_SUBJECT_NAME
        
        context.user_data['current_subject'] = subject_name
        
        await update.message.reply_text(
            f"Предмет '{subject_name}' установлен. Теперь отправьте список тем:\n"
            "1. Тема 1\n"
            "2. Тема 2\n"
            "3. Тема 3\n"
            "..."
        )
        return WAITING_TOPICS_LIST

    async def handle_topics_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = update.message.text.strip()
        subject_name = context.user_data.get('current_subject')
        
        if not subject_name:
            await update.message.reply_text("Ошибка. Начните заново с /new_subject")
            return ConversationHandler.END
        
        lines = text.split('\n')
        topics_dict = {}
        
        for line in lines:
            if '.' in line:
                parts = line.split('.', 1)
                try:
                    number = int(parts[0].strip())
                    topic = parts[1].strip()
                    if topic:
                        topics_dict[number] = topic
                except (ValueError, IndexError):
                    continue
        
        if topics_dict:
            self.topics[subject_name] = topics_dict
            self.registrations[subject_name] = {}
            
            topics_text = f"✅ Темы для '{subject_name}' добавлены!\n\n"
            for num, topic in sorted(topics_dict.items()):
                topics_text += f"{num}. {topic}\n"
            
            start_time = self.start_times.get(subject_name)
            if start_time:
                now = self.get_local_time()
                if now >= start_time:
                    topics_text += f"\n✅ Распределение АКТИВНО"
                else:
                    time_left = start_time - now
                    time_info = self.format_time_left(time_left)
                    topics_text += f"\n⏰ Начнется через: {time_info}"
            else:
                topics_text += "\n⏰ Время не установлено (/set_subject_time)"
            
            topics_text += "\n\nЧтобы выбрать тему, отправьте номер."
            
            await update.message.reply_text(topics_text)
            context.user_data.pop('current_subject', None)
        else:
            await update.message.reply_text(
                "Не удалось распознать темы. Формат:\n"
                "1. Тема 1\n"
                "2. Тема 2\n"
                "..."
            )
            return WAITING_TOPICS_LIST
        
        return ConversationHandler.END

    async def set_subject_time(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text("Эта команда доступна только администратору.")
            return ConversationHandler.END
        
        if not self.topics:
            await update.message.reply_text("Нет добавленных предметов.")
            return ConversationHandler.END
        
        subjects_text = "📚 Выберите предмет:\n\n"
        for i, subject in enumerate(self.topics.keys(), 1):
            start_time = self.start_times.get(subject)
            time_info = f" - {start_time.strftime('%d.%m.%Y %H:%M')}" if start_time else " - время не установлено"
            subjects_text += f"{i}. {subject}{time_info}\n"
        
        subjects_text += "\nВведите номер предмета:"
        await update.message.reply_text(subjects_text)
        
        return WAITING_FOR_SUBJECT_TIME

    async def handle_subject_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = update.message.text.strip()
        subject = None
        
        try:
            subject_num = int(text)
            subjects = list(self.topics.keys())
            if 1 <= subject_num <= len(subjects):
                subject = subjects[subject_num - 1]
        except ValueError:
            if text in self.topics:
                subject = text
        
        if not subject:
            await update.message.reply_text("❌ Предмет не найден. Введите номер из списка:")
            return WAITING_FOR_SUBJECT_TIME
        
        context.user_data['selected_subject'] = subject
        
        await update.message.reply_text(
            f"📖 Выбран предмет: {subject}\n\n"
            "📅 Введите дату начала в формате ДД.ММ.ГГГГ\n"
            "Например: 25.12.2024"
        )
        return SETTING_DATE

    async def handle_set_date(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = update.message.text.strip()
        subject = context.user_data.get('selected_subject')
        
        if not subject:
            await update.message.reply_text("❌ Ошибка: предмет не выбран.")
            return ConversationHandler.END
        
        # Проверяем формат даты
        date_pattern = r'^(\d{1,2})\.(\d{1,2})\.(\d{4})$'
        match = re.match(date_pattern, text)
        
        if not match:
            await update.message.reply_text(
                "❌ Неверный формат даты!\n"
                "✅ Используйте: ДД.ММ.ГГГГ\n"
                "Например: 25.12.2024\n"
                "Попробуйте еще раз:"
            )
            return SETTING_DATE
        
        day, month, year = map(int, match.groups())
        
        try:
            # Создаем дату в московском часовом поясе
            selected_date = datetime.datetime(year, month, day)
            
            # Получаем текущее время в MSK
            now_msk = self.get_local_time()
            
            if selected_date.date() < now_msk.date():
                await update.message.reply_text(
                    "❌ Нельзя установить дату в прошлом!\n"
                    "✅ Введите будущую дату:\n"
                    "Формат: ДД.ММ.ГГГГ"
                )
                return SETTING_DATE
            
            # Сохраняем дату
            context.user_data['selected_date'] = selected_date
            
            await update.message.reply_text(
                f"✅ Дата установлена: {selected_date.strftime('%d.%m.%Y')}\n\n"
                "⏰ Теперь введите время начала в формате ЧЧ:ММ\n"
                "Например: 14:30"
            )
            return SETTING_TIME
            
        except ValueError as e:
            await update.message.reply_text(
                f"❌ Некорректная дата!\n"
                "✅ Проверьте:\n"
                "- День от 1 до 31\n"
                "- Месяц от 1 до 12\n"
                "- Год от 2024\n"
                "Попробуйте еще раз:"
            )
            return SETTING_DATE

    async def handle_set_time(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = update.message.text.strip()
        subject = context.user_data.get('selected_subject')
        selected_date = context.user_data.get('selected_date')
        
        if not subject or not selected_date:
            await update.message.reply_text("❌ Ошибка: данные не найдены.")
            return ConversationHandler.END
        
        # Проверяем формат времени
        time_pattern = r'^([0-1]?[0-9]|2[0-3]):([0-5][0-9])$'
        match = re.match(time_pattern, text)
        
        if not match:
            await update.message.reply_text(
                "❌ Неверный формат времени!\n"
                "✅ Используйте: ЧЧ:ММ\n"
                "Например: 14:30\n"
                "Попробуйте еще раз:"
            )
            return SETTING_TIME
        
        hours, minutes = map(int, match.groups())
        
        try:
            # Создаем полную дату и время в MSK
            start_time = datetime.datetime.combine(selected_date, datetime.time(hours, minutes))
            
            # Получаем текущее время в MSK
            now_msk = self.get_local_time()
            
            # Проверяем, что установленное время в будущем
            if start_time <= now_msk:
                await update.message.reply_text(
                    "❌ Нельзя установить время в прошлом!\n"
                    "✅ Введите будущее время:\n"
                    "Формат: ЧЧ:ММ"
                )
                return SETTING_TIME
            
            # Устанавливаем время начала для предмета
            self.start_times[subject] = start_time
            
            # Рассчитываем сколько времени осталось
            time_left = start_time - now_msk
            time_info = self.format_time_left(time_left)
            
            await update.message.reply_text(
                f"✅ Дата и время установлены!\n\n"
                f"📖 Предмет: {subject}\n"
                f"📅 Дата: {start_time.strftime('%d.%m.%Y')}\n"
                f"⏰ Время: {start_time.strftime('%H:%M')}\n"
                f"⏳ До начала: {time_info}\n"
                f"🔔 Напоминание за 5 минут до начала"
            )
            
            # Очищаем временные данные
            context.user_data.pop('selected_subject', None)
            context.user_data.pop('selected_date', None)
            
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {str(e)}")
        
        return ConversationHandler.END

    async def send_topics_update(self, subject, update: Update = None):
        try:
            topics_text = f"📊 Темы по предмету '{subject}':\n\n"
            
            for num, topic in self.topics[subject].items():
                if subject in self.registrations and num in self.registrations[subject]:
                    user_id, username, timestamp = self.registrations[subject][num]
                    time_str = timestamp.strftime('%H:%M:%S')
                    topics_text += f"{num}. {topic} - ✅ @{username} ({time_str})\n"
                else:
                    topics_text += f"{num}. {topic} - ❌ Свободна\n"
            
            start_time = self.start_times.get(subject)
            if start_time:
                now = self.get_local_time()
                if now >= start_time:
                    topics_text += f"\n✅ Распределение АКТИВНО"
                else:
                    time_left = start_time - now
                    time_info = self.format_time_left(time_left)
                    topics_text += f"\n⏰ Начнется через: {time_info}"
            
            if update:
                await update.message.reply_text(topics_text)
                
        except Exception as e:
            logging.error(f"Ошибка при отправке тем: {e}")

    async def list_subjects(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.topics:
            await update.message.reply_text("Нет добавленных предметов.")
            return
        
        subjects_text = "📚 Список предметов:\n\n"
        
        for subject in self.topics.keys():
            start_time = self.start_times.get(subject)
            if start_time:
                time_info = start_time.strftime('%d.%m.%Y %H:%M')
                now = self.get_local_time()
                
                if now >= start_time:
                    status = "✅ АКТИВНО"
                else:
                    time_left = start_time - now
                    time_info_status = self.format_time_left(time_left)
                    status = f"⏰ Через {time_info_status}"
            else:
                time_info = "не установлено"
                status = "❌ Время не задано"
            
            topics_count = len(self.topics[subject])
            reg_count = len(self.registrations.get(subject, {}))
            
            subjects_text += f"📖 {subject}\n"
            subjects_text += f"   ⏰ Время: {time_info}\n"
            subjects_text += f"   📊 Темы: {topics_count}, Выбрано: {reg_count}\n"
            subjects_text += f"   🚦 Статус: {status}\n\n"
        
        await update.message.reply_text(subjects_text)

    # ... остальные методы остаются без изменений

    async def cancel_registration(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text("Эта команда доступна только администратору.")
            return ConversationHandler.END
        
        if not self.topics:
            await update.message.reply_text("Нет добавленных предметов.")
            return ConversationHandler.END
        
        subjects_text = "Выберите предмет:\n\n"
        for i, subject in enumerate(self.topics.keys(), 1):
            subjects_text += f"{i}. {subject}\n"
        
        subjects_text += "\nВведите номер предмета:"
        await update.message.reply_text(subjects_text)
        
        context.user_data['cancel_action'] = 'select_subject'
        return CANCELING_REGISTRATION

    async def handle_cancel_registration(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = update.message.text.strip()
        
        if context.user_data.get('cancel_action') == 'select_subject':
            try:
                subject_num = int(text)
                subjects = list(self.topics.keys())
                if 1 <= subject_num <= len(subjects):
                    subject = subjects[subject_num - 1]
                    context.user_data['selected_subject'] = subject
                    context.user_data['cancel_action'] = 'select_topic'
                    
                    if subject in self.registrations and self.registrations[subject]:
                        occupied_text = f"Занятые темы для '{subject}':\n\n"
                        for topic_num, (user_id, username, timestamp) in self.registrations[subject].items():
                            topic_name = self.topics[subject][topic_num]
                            occupied_text += f"{topic_num}. {topic_name} - @{username}\n"
                        
                        occupied_text += "\nВведите номер темы для отмены:"
                        await update.message.reply_text(occupied_text)
                    else:
                        await update.message.reply_text(f"Для предмета '{subject}' нет занятых тем.")
                        return ConversationHandler.END
                else:
                    await update.message.reply_text("Неверный номер предмета.")
                    return CANCELING_REGISTRATION
            except ValueError:
                await update.message.reply_text("Введите номер предмета.")
                return CANCELING_REGISTRATION
        
        elif context.user_data.get('cancel_action') == 'select_topic':
            try:
                topic_num = int(text)
                subject = context.user_data.get('selected_subject')
                
                if subject not in self.registrations or topic_num not in self.registrations[subject]:
                    await update.message.reply_text("Тема не занята или не существует.")
                    return CANCELING_REGISTRATION
                
                user_id, username, timestamp = self.registrations[subject].pop(topic_num)
                topic_name = self.topics[subject][topic_num]
                
                await update.message.reply_text(
                    f"Регистрация отменена:\n"
                    f"Тема: {topic_num}. {topic_name}\n"
                    f"Предмет: {subject}\n"
                    f"Пользователь: @{username}"
                )
                
                await self.send_topics_update(subject, update)
                context.user_data.pop('selected_subject', None)
                context.user_data.pop('cancel_action', None)
                
            except ValueError:
                await update.message.reply_text("Введите номер темы.")
                return CANCELING_REGISTRATION
        
        return ConversationHandler.END

    async def remove_user(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text("Эта команда доступна только администратору.")
            return ConversationHandler.END
        
        if not self.topics:
            await update.message.reply_text("Нет добавленных предметов.")
            return ConversationHandler.END
        
        subjects_text = "Выберите предмет:\n\n"
        for i, subject in enumerate(self.topics.keys(), 1):
            subjects_text += f"{i}. {subject}\n"
        
        subjects_text += "\nВведите номер предмета:"
        await update.message.reply_text(subjects_text)
        
        return SELECTING_SUBJECT_FOR_REMOVAL

    async def handle_subject_selection_for_removal(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = update.message.text.strip()
        subject = None
        
        try:
            subject_num = int(text)
            subjects = list(self.topics.keys())
            if 1 <= subject_num <= len(subjects):
                subject = subjects[subject_num - 1]
        except ValueError:
            if text in self.topics:
                subject = text
        
        if not subject:
            await update.message.reply_text("Предмет не найден.")
            return SELECTING_SUBJECT_FOR_REMOVAL
        
        context.user_data['removal_subject'] = subject
        
        if subject in self.registrations and self.registrations[subject]:
            occupied_text = f"Занятые темы для '{subject}':\n\n"
            for topic_num, (user_id, username, timestamp) in self.registrations[subject].items():
                topic_name = self.topics[subject][topic_num]
                occupied_text += f"{topic_num}. {topic_name} - @{username}\n"
            
            occupied_text += "\nВведите номер темы для удаления:"
            await update.message.reply_text(occupied_text)
            return SELECTING_TOPIC_FOR_REMOVAL
        else:
            await update.message.reply_text(f"Для предмета '{subject}' нет занятых тем.")
            context.user_data.pop('removal_subject', None)
            return ConversationHandler.END

    async def handle_topic_selection_for_removal(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = update.message.text.strip()
        subject = context.user_data.get('removal_subject')
        
        if not subject:
            await update.message.reply_text("Ошибка: предмет не выбран.")
            return ConversationHandler.END
        
        try:
            topic_num = int(text)
            
            if subject not in self.registrations or topic_num not in self.registrations[subject]:
                await update.message.reply_text("Тема не занята или не существует.")
                return SELECTING_TOPIC_FOR_REMOVAL
            
            user_id, username, timestamp = self.registrations[subject].pop(topic_num)
            topic_name = self.topics[subject][topic_num]
            
            await update.message.reply_text(
                f"Участник удален:\n"
                f"Тема: {topic_num}. {topic_name}\n"
                f"Предмет: {subject}\n"
                f"Пользователь: @{username}"
            )
            
            await self.send_topics_update(subject, update)
            
        except ValueError:
            await update.message.reply_text("Введите номер темы.")
            return SELECTING_TOPIC_FOR_REMOVAL
        finally:
            context.user_data.pop('removal_subject', None)
        
        return ConversationHandler.END

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        for key in ['current_subject', 'selected_subject', 'cancel_action', 'removal_subject', 'selected_date']:
            context.user_data.pop(key, None)
        
        await update.message.reply_text(
            "Операция отменена.",
            reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END

    def is_distribution_started(self, subject):
        if subject not in self.start_times:
            return True
        now = self.get_local_time()
        return now >= self.start_times[subject]

    async def handle_topic_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = update.message.text.strip()
        user_id = update.effective_user.id
        username = update.effective_user.username or update.effective_user.first_name

        if text.isdigit():
            selected_subject = None
            for subject in self.topics.keys():
                if self.is_distribution_started(subject):
                    selected_subject = subject
                    break
            
            if not selected_subject:
                await update.message.reply_text("Нет активных распределений.")
                return
            
            try:
                topic_number = int(text)
                topics = self.topics[selected_subject]
                
                if topic_number not in topics:
                    await update.message.reply_text("Такой темы не существует.")
                    return
                
                if selected_subject in self.registrations and topic_number in self.registrations[selected_subject]:
                    await update.message.reply_text("Эта тема уже занята!")
                    return
                
                timestamp = self.get_local_time()
                if selected_subject not in self.registrations:
                    self.registrations[selected_subject] = {}
                self.registrations[selected_subject][topic_number] = (user_id, username, timestamp)
                
                await update.message.reply_text(
                    f"🎉 Тема выбрана!\n"
                    f"📖 {topic_number}. {topics[topic_number]}\n"
                    f"📚 {selected_subject}\n"
                    f"⏰ {timestamp.strftime('%H:%M:%S')}"
                )
                
                await self.send_topics_update(selected_subject, update)
                
            except ValueError:
                await update.message.reply_text("Введите номер темы.")

    async def view_topics(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self.topics:
            await update.message.reply_text("Темы еще не добавлены.")
            return
        
        for subject in self.topics.keys():
            await self.send_topics_update(subject, update)

    async def show_results(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not any(self.registrations.values()):
            await update.message.reply_text("Еще никто не выбрал темы.")
            return
        
        for subject, registrations in self.registrations.items():
            if registrations:
                sorted_registrations = sorted(registrations.items(), key=lambda x: x[1][2])
                
                results_text = f"📊 Результаты по '{subject}':\n\n"
                
                for topic_num, (user_id, username, timestamp) in sorted_registrations:
                    topic_name = self.topics[subject][topic_num]
                    time_str = timestamp.strftime('%H:%M:%S')
                    results_text += f"{topic_num}. {topic_name}\n   👤 @{username} ({time_str})\n\n"
                
                await update.message.reply_text(results_text)

def main():
    TOKEN = os.environ.get('BOT_TOKEN', "8405347117:AAG7h0qxePyQ9mXW3z03DBYOEWafOVP3oBI")
    
    application = Application.builder().token(TOKEN).build()
    bot = SeminarBot()
    
    # ConversationHandler для добавления предметов
    new_subject_handler = ConversationHandler(
        entry_points=[CommandHandler("new_subject", bot.new_subject)],
        states={
            WAITING_SUBJECT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_subject_name)],
            WAITING_TOPICS_LIST: [MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_topics_list)],
        },
        fallbacks=[CommandHandler("cancel", bot.cancel)]
    )
    
    # ConversationHandler для установки времени
    time_handler = ConversationHandler(
        entry_points=[CommandHandler("set_subject_time", bot.set_subject_time)],
        states={
            WAITING_FOR_SUBJECT_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_subject_selection)],
            SETTING_DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_set_date)],
            SETTING_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_set_time)],
        },
        fallbacks=[CommandHandler("cancel", bot.cancel)]
    )
    
    # ConversationHandler для административных команд
    admin_handler = ConversationHandler(
        entry_points=[
            CommandHandler("cancel_registration", bot.cancel_registration),
            CommandHandler("remove_user", bot.remove_user)
        ],
        states={
            CANCELING_REGISTRATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_cancel_registration)],
            SELECTING_SUBJECT_FOR_REMOVAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_subject_selection_for_removal)],
            SELECTING_TOPIC_FOR_REMOVAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_topic_selection_for_removal)]
        },
        fallbacks=[CommandHandler("cancel", bot.cancel)]
    )
    
    # Добавляем обработчики
    application.add_handler(CommandHandler("start", bot.start))
    application.add_handler(new_subject_handler)
    application.add_handler(time_handler)
    application.add_handler(CommandHandler("view_topics", bot.view_topics))
    application.add_handler(CommandHandler("results", bot.show_results))
    application.add_handler(CommandHandler("list_subjects", bot.list_subjects))
    application.add_handler(admin_handler)
    application.add_handler(CommandHandler("cancel", bot.cancel))
    
    # Обработчик для выбора тем
    application.add_handler(MessageHandler(
        filters.TEXT & filters.Regex(r'^\d+$'), 
        bot.handle_topic_selection
    ))
    
    print("Бот запущен...")
    application.run_polling()

if __name__ == "__main__":
    main()
