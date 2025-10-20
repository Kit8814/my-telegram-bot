import logging
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters, ConversationHandler
from collections import OrderedDict
import datetime
import re
import asyncio

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# Константы для состояний ConversationHandler
SETTING_DATE_TIME, CANCELING_REGISTRATION, WAITING_FOR_SUBJECT_TIME, SELECTING_SUBJECT_FOR_REMOVAL, SELECTING_TOPIC_FOR_REMOVAL = range(5)

class SeminarBot:
    def __init__(self, application):
        self.topics = {}  # {subject: {number: topic}}
        self.registrations = {}  # {subject: {number: (user_id, username, timestamp)}}
        self.start_times = {}  # {subject: datetime} - время начала для каждого предмета
        self.current_subject = None
        self.waiting_for_topics = False
        self.admin_id = None  # ID администратора
        self.distribution_tasks = {}  # {subject: task} - задачи для автоматического начала распределения
        self.reminder_tasks = {}  # {subject: task} - задачи для напоминаний
        self.application = application
        
        # Установите ID администратора здесь
        self.admin_id = 1074399585   # Замените на реальный ID администратора

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
            "/set_subject_time - установить дату и время начала для предмета (только для админа)\n"
            "/cancel_registration - отменить выбор темы (только для админа)\n"
            "/remove_user - удалить участника с темы (только для админа)\n"
            "/list_subjects - показать все предметы и их время начала\n"
            "/cancel - отменить текущую операцию"
        )

    async def new_subject(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Начать новое распределение тем"""
        self.waiting_for_topics = True
        self.current_subject = None
        
        await update.message.reply_text(
            "Введите название предмета для которого добавляете темы:",
            reply_markup=ReplyKeyboardRemove()
        )

    async def set_subject_time(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Установить дату и время начала для конкретного предмета (только для админа)"""
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text("Эта команда доступна только администратору.")
            return ConversationHandler.END
        
        if not self.topics:
            await update.message.reply_text("Нет добавленных предметов.")
            return ConversationHandler.END
        
        # Показываем список предметов
        subjects_text = "Доступные предметы:\n\n"
        for i, subject in enumerate(self.topics.keys(), 1):
            start_time = self.start_times.get(subject)
            time_info = f" - начало: {start_time.strftime('%d.%m.%Y %H:%M')}" if start_time else " - время не установлено"
            subjects_text += f"{i}. {subject}{time_info}\n"
        
        subjects_text += "\nВведите номер предмета или название для установки даты и времени:"
        await update.message.reply_text(subjects_text)
        
        return WAITING_FOR_SUBJECT_TIME

    async def handle_subject_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка выбора предмета для установки даты и времени"""
        text = update.message.text.strip()
        subject = None
        
        # Пытаемся найти предмет по номеру
        try:
            subject_num = int(text)
            subjects = list(self.topics.keys())
            if 1 <= subject_num <= len(subjects):
                subject = subjects[subject_num - 1]
        except ValueError:
            # Ищем предмет по названию
            if text in self.topics:
                subject = text
        
        if not subject:
            await update.message.reply_text("Предмет не найден. Попробуйте еще раз.")
            return WAITING_FOR_SUBJECT_TIME
        
        context.user_data['selected_subject'] = subject
        await update.message.reply_text(
            f"Выбран предмет: {subject}\n\n"
            "Теперь установите дату и время начала распределения.\n\n"
            "📅 Введите дату в формате ДД.ММ.ГГГГ (например, 25.12.2024):"
        )
        return SETTING_DATE_TIME

    async def handle_set_date_time(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка ввода даты и времени начала для предмета"""
        text = update.message.text.strip()
        subject = context.user_data.get('selected_subject')
        
        if not subject:
            await update.message.reply_text("Ошибка: предмет не выбран.")
            return ConversationHandler.END
        
        # Если это первый шаг - ввод даты
        if 'selected_date' not in context.user_data:
            # Проверяем формат даты
            date_pattern = r'^(\d{2})\.(\d{2})\.(\d{4})$'
            match = re.match(date_pattern, text)
            
            if not match:
                await update.message.reply_text(
                    "Неверный формат даты. Используйте ДД.ММ.ГГГГ (например, 25.12.2024)\n"
                    "Попробуйте еще раз:"
                )
                return SETTING_DATE_TIME
            
            day, month, year = map(int, match.groups())
            
            try:
                # Проверяем корректность даты
                selected_date = datetime.datetime(year, month, day)
                now = datetime.datetime.now()
                
                if selected_date.date() < now.date():
                    await update.message.reply_text(
                        "Нельзя установить дату в прошлом! Введите будущую дату:\n"
                        "Формат: ДД.ММ.ГГГГ (например, 25.12.2024)"
                    )
                    return SETTING_DATE_TIME
                
                context.user_data['selected_date'] = selected_date
                await update.message.reply_text(
                    f"✅ Дата установлена: {selected_date.strftime('%d.%m.%Y')}\n\n"
                    "⏰ Теперь введите время начала в формате ЧЧ:ММ (например, 14:30):"
                )
                return SETTING_DATE_TIME
                
            except ValueError:
                await update.message.reply_text(
                    "Некорректная дата! Проверьте правильность ввода.\n"
                    "Формат: ДД.ММ.ГГГГ (например, 25.12.2024)\n"
                    "Попробуйте еще раз:"
                )
                return SETTING_DATE_TIME
        
        # Если это второй шаг - ввод времени
        else:
            # Проверяем формат времени
            time_pattern = r'^([0-1]?[0-9]|2[0-3]):([0-5][0-9])$'
            if not re.match(time_pattern, text):
                await update.message.reply_text(
                    "Неверный формат времени. Используйте ЧЧ:ММ (например, 14:30)\n"
                    "Попробуйте еще раз:"
                )
                return SETTING_DATE_TIME
            
            # Получаем сохраненную дату и добавляем время
            selected_date = context.user_data['selected_date']
            hours, minutes = map(int, text.split(':'))
            
            # Создаем полную дату и время
            start_time = selected_date.replace(hour=hours, minute=minutes, second=0, microsecond=0)
            
            now = datetime.datetime.now()
            
            # Проверяем, что установленное время в будущем
            if start_time <= now:
                await update.message.reply_text(
                    "Нельзя установить время в прошлом! Введите будущее время:\n"
                    "Формат: ЧЧ:ММ (например, 14:30)"
                )
                return SETTING_DATE_TIME
            
            # Устанавливаем время начала для предмета
            self.start_times[subject] = start_time
            
            # Запускаем задачу для автоматического начала распределения
            await self.schedule_distribution_start(subject, start_time)
            # Запускаем задачу для напоминания за 5 минут
            await self.schedule_reminder(subject, start_time)
            
            # Рассчитываем сколько дней осталось
            days_left = (start_time.date() - now.date()).days
            
            await update.message.reply_text(
                f"✅ Дата и время начала распределения установлены!\n\n"
                f"📖 Предмет: {subject}\n"
                f"📅 Дата: {start_time.strftime('%d.%m.%Y')}\n"
                f"⏰ Время: {start_time.strftime('%H:%M')}\n"
                f"📊 До начала: {days_left} дней\n"
                f"🔔 Напоминание будет отправлено за 5 минут до начала."
            )
            
            # Очищаем временные данные
            context.user_data.pop('selected_subject', None)
            context.user_data.pop('selected_date', None)
            return ConversationHandler.END

    async def schedule_distribution_start(self, subject, start_time):
        """Запускает задачу для автоматического начала распределения в указанное время"""
        # Отменяем предыдущую задачу, если она существует
        if subject in self.distribution_tasks:
            self.distribution_tasks[subject].cancel()
        
        # Создаем новую задачу
        async def start_distribution():
            delay = (start_time - datetime.datetime.now()).total_seconds()
            if delay > 0:
                await asyncio.sleep(delay)
                # Рассылаем уведомление о начале распределения
                await self.notify_distribution_start(subject)
        
        task = asyncio.create_task(start_distribution())
        self.distribution_tasks[subject] = task

    async def schedule_reminder(self, subject, start_time):
        """Запускает задачу для отправки напоминания за 5 минут до начала"""
        # Отменяем предыдущую задачу, если она существует
        if subject in self.reminder_tasks:
            self.reminder_tasks[subject].cancel()
        
        reminder_time = start_time - datetime.timedelta(minutes=5)
        now = datetime.datetime.now()
        
        # Если время напоминания уже прошло, не планируем его
        if reminder_time < now:
            return
        
        async def send_reminder():
            delay = (reminder_time - datetime.datetime.now()).total_seconds()
            if delay > 0:
                await asyncio.sleep(delay)
                await self.notify_reminder(subject)
        
        task = asyncio.create_task(send_reminder())
        self.reminder_tasks[subject] = task

    async def notify_reminder(self, subject):
        """Рассылает напоминание о начале распределения за 5 минут"""
        try:
            message_text = (
                f"⏰ Напоминание!\n"
                f"Распределение тем по предмету '{subject}' начнется через 5 минут!\n"
                f"Приготовьтесь выбрать тему."
            )
            logging.info(f"НАПОМИНАНИЕ для предмета '{subject}': {message_text}")
            
        except Exception as e:
            logging.error(f"Ошибка при отправке напоминания: {e}")

    async def notify_distribution_start(self, subject):
        """Рассылает уведомление о начале распределения тем"""
        try:
            logging.info(f"Распределение тем для предмета '{subject}' началось!")
            
            message_text = (
                f"🎉 Распределение тем по предмету '{subject}' началось!\n\n"
                f"Доступные темы:\n"
            )
            
            for num, topic in self.topics[subject].items():
                status = "✅ Занята" if subject in self.registrations and num in self.registrations[subject] else "❌ Свободна"
                message_text += f"{num}. {topic} - {status}\n"
            
            message_text += "\nЧтобы выбрать тему, отправьте номер нужной темы."
            
            logging.info(f"Сообщение о начале распределения: {message_text}")
            
        except Exception as e:
            logging.error(f"Ошибка при отправке уведомления: {e}")

    async def send_topics_update(self, subject, update: Update = None, chat_id: int = None):
        """Отправляет обновленный список тем после выбора"""
        try:
            topics_text = f"📊 Актуальный список тем по предмету '{subject}':\n\n"
            
            for num, topic in self.topics[subject].items():
                if subject in self.registrations and num in self.registrations[subject]:
                    user_id, username, timestamp = self.registrations[subject][num]
                    time_str = timestamp.strftime('%H:%M:%S')
                    topics_text += f"{num}. {topic} - ✅ Занята @{username} (в {time_str})\n"
                else:
                    topics_text += f"{num}. {topic} - ❌ Свободна\n"
            
            start_time = self.start_times.get(subject)
            if start_time:
                now = datetime.datetime.now()
                if self.is_distribution_started(subject):
                    topics_text += f"\n✅ Распределение активно с {start_time.strftime('%d.%m.%Y %H:%M')}"
                else:
                    time_left = start_time - now
                    days = time_left.days
                    hours, remainder = divmod(time_left.seconds, 3600)
                    minutes, seconds = divmod(remainder, 60)
                    
                    if days > 0:
                        topics_text += f"\n⏰ До начала: {days} дн {int(hours)}ч {int(minutes)}м"
                    else:
                        topics_text += f"\n⏰ До начала: {int(hours)}ч {int(minutes)}м"
            
            # Отправляем сообщение
            if update:
                await update.message.reply_text(topics_text)
            elif chat_id:
                await self.application.bot.send_message(chat_id, topics_text)
                
        except Exception as e:
            logging.error(f"Ошибка при отправке обновления тем: {e}")

    async def list_subjects(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показать все предметы и их время начала"""
        if not self.topics:
            await update.message.reply_text("Нет добавленных предметов.")
            return
        
        subjects_text = "📚 Список предметов и время начала распределения:\n\n"
        
        for subject in self.topics.keys():
            start_time = self.start_times.get(subject)
            if start_time:
                time_info = start_time.strftime('%d.%m.%Y %H:%M')
                now = datetime.datetime.now()
                
                if now >= start_time:
                    status = "✅ Распределение началось"
                else:
                    time_left = start_time - now
                    days = time_left.days
                    hours, remainder = divmod(time_left.seconds, 3600)
                    minutes, seconds = divmod(remainder, 60)
                    
                    if days > 0:
                        status = f"⏰ До начала: {days} дн {int(hours)}ч {int(minutes)}м"
                    else:
                        status = f"⏰ До начала: {int(hours)}ч {int(minutes)}м"
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

    # ... (остальные методы класса остаются без изменений: cancel_registration, handle_cancel_registration, remove_user, handle_subject_selection_for_removal, handle_topic_selection_for_removal, cancel, is_distribution_started, handle_text, view_topics, show_results)

    async def cancel_registration(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Начать процесс отмены регистрации (только для админа)"""
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text("Эта команда доступна только администратору.")
            return ConversationHandler.END
        
        if not self.topics:
            await update.message.reply_text("Нет добавленных предметов.")
            return ConversationHandler.END
        
        # Показываем список предметов
        subjects_text = "Выберите предмет:\n\n"
        for i, subject in enumerate(self.topics.keys(), 1):
            subjects_text += f"{i}. {subject}\n"
        
        subjects_text += "\nВведите номер предмета:"
        await update.message.reply_text(subjects_text)
        
        context.user_data['cancel_action'] = 'select_subject'
        return CANCELING_REGISTRATION

    async def handle_cancel_registration(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка отмены регистрации"""
        text = update.message.text.strip()
        
        if context.user_data.get('cancel_action') == 'select_subject':
            # Выбор предмета
            try:
                subject_num = int(text)
                subjects = list(self.topics.keys())
                if 1 <= subject_num <= len(subjects):
                    subject = subjects[subject_num - 1]
                    context.user_data['selected_subject'] = subject
                    context.user_data['cancel_action'] = 'select_topic'
                    
                    # Показываем занятые темы для выбранного предмета
                    if subject in self.registrations and self.registrations[subject]:
                        occupied_text = f"Занятые темы для '{subject}':\n\n"
                        for topic_num, (user_id, username, timestamp) in self.registrations[subject].items():
                            topic_name = self.topics[subject][topic_num]
                            occupied_text += f"{topic_num}. {topic_name} - @{username} ({timestamp.strftime('%H:%M:%S')})\n"
                        
                        occupied_text += "\nВведите номер темы для отмены регистрации:"
                        await update.message.reply_text(occupied_text)
                    else:
                        await update.message.reply_text(f"Для предмета '{subject}' нет занятых тем.")
                        return ConversationHandler.END
                else:
                    await update.message.reply_text("Неверный номер предмета.")
                    return CANCELING_REGISTRATION
            except ValueError:
                await update.message.reply_text("Пожалуйста, введите номер предмета.")
                return CANCELING_REGISTRATION
        
        elif context.user_data.get('cancel_action') == 'select_topic':
            # Выбор темы для отмены
            try:
                topic_num = int(text)
                subject = context.user_data.get('selected_subject')
                
                if subject not in self.registrations or topic_num not in self.registrations[subject]:
                    await update.message.reply_text("Этот номер темы не занят или не существует.")
                    return CANCELING_REGISTRATION
                
                # Удаляем регистрацию
                user_id, username, timestamp = self.registrations[subject].pop(topic_num)
                topic_name = self.topics[subject][topic_num]
                
                await update.message.reply_text(
                    f"Регистрация на тему {topic_num}. {topic_name} отменена.\n"
                    f"Предмет: {subject}\n"
                    f"Пользователь: @{username}"
                )
                
                # Отправляем обновленный список тем
                await self.send_topics_update(subject, update)
                
                # Очищаем временные данные
                context.user_data.pop('selected_subject', None)
                context.user_data.pop('cancel_action', None)
                
            except ValueError:
                await update.message.reply_text("Пожалуйста, введите номер темы (цифру).")
                return CANCELING_REGISTRATION
        
        return ConversationHandler.END

    async def remove_user(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Начать процесс удаления пользователя с темы (только для админа)"""
        if not self.is_admin(update.effective_user.id):
            await update.message.reply_text("Эта команда доступна только администратору.")
            return ConversationHandler.END
        
        if not self.topics:
            await update.message.reply_text("Нет добавленных предметов.")
            return ConversationHandler.END
        
        # Показываем список предметов
        subjects_text = "Выберите предмет для удаления участника:\n\n"
        for i, subject in enumerate(self.topics.keys(), 1):
            subjects_text += f"{i}. {subject}\n"
        
        subjects_text += "\nВведите номер предмета:"
        await update.message.reply_text(subjects_text)
        
        return SELECTING_SUBJECT_FOR_REMOVAL

    async def handle_subject_selection_for_removal(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка выбора предмета для удаления пользователя"""
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
            await update.message.reply_text("Предмет не найден. Попробуйте еще раз.")
            return SELECTING_SUBJECT_FOR_REMOVAL
        
        context.user_data['removal_subject'] = subject
        
        # Показываем занятые темы для выбранного предмета
        if subject in self.registrations and self.registrations[subject]:
            occupied_text = f"Занятые темы для '{subject}':\n\n"
            for topic_num, (user_id, username, timestamp) in self.registrations[subject].items():
                topic_name = self.topics[subject][topic_num]
                occupied_text += f"{topic_num}. {topic_name} - @{username} ({timestamp.strftime('%H:%M:%S')})\n"
            
            occupied_text += "\nВведите номер темы, с которой нужно удалить участника:"
            await update.message.reply_text(occupied_text)
            return SELECTING_TOPIC_FOR_REMOVAL
        else:
            await update.message.reply_text(f"Для предмета '{subject}' нет занятых тем.")
            context.user_data.pop('removal_subject', None)
            return ConversationHandler.END

    async def handle_topic_selection_for_removal(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка выбора темы для удаления пользователя"""
        text = update.message.text.strip()
        subject = context.user_data.get('removal_subject')
        
        if not subject:
            await update.message.reply_text("Ошибка: предмет не выбран.")
            return ConversationHandler.END
        
        try:
            topic_num = int(text)
            
            if subject not in self.registrations or topic_num not in self.registrations[subject]:
                await update.message.reply_text("Этот номер темы не занят или не существует.")
                return SELECTING_TOPIC_FOR_REMOVAL
            
            # Удаляем регистрацию
            user_id, username, timestamp = self.registrations[subject].pop(topic_num)
            topic_name = self.topics[subject][topic_num]
            
            await update.message.reply_text(
                f"Участник @{username} удален с темы {topic_num}. {topic_name}.\n"
                f"Предмет: {subject}\n"
                f"Тема теперь свободна для выбора."
            )
            
            # Отправляем обновленный список тем
            await self.send_topics_update(subject, update)
            
        except ValueError:
            await update.message.reply_text("Пожалуйста, введите номер темы (цифру).")
            return SELECTING_TOPIC_FOR_REMOVAL
        finally:
            # Очищаем временные данные
            context.user_data.pop('removal_subject', None)
        
        return ConversationHandler.END

    async def cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Отмена текущей операции"""
        self.waiting_for_topics = False
        # Очищаем временные данные
        context.user_data.pop('selected_subject', None)
        context.user_data.pop('cancel_action', None)
        context.user_data.pop('removal_subject', None)
        context.user_data.pop('selected_date', None)
        
        await update.message.reply_text(
            "Операция отменена.",
            reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END

    def is_distribution_started(self, subject):
        """Проверяет, началось ли распределение тем для указанного предмета"""
        if subject not in self.start_times:
            return True  # Если время не установлено, разрешаем сразу
        
        now = datetime.datetime.now()
        return now >= self.start_times[subject]

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
                
                start_time = self.start_times.get(self.current_subject)
                if start_time:
                    now = datetime.datetime.now()
                    time_left = start_time - now
                    days = time_left.days
                    
                    if days > 0:
                        topics_text += f"\n📅 Распределение начнется: {start_time.strftime('%d.%m.%Y %H:%M')}"
                        topics_text += f"\n⏰ До начала: {days} дней"
                    else:
                        topics_text += f"\n⏰ Распределение начнется: {start_time.strftime('%d.%m.%Y %H:%M')}"
                else:
                    topics_text += "\n⏰ Время начала распределения не установлено"
                
                topics_text += "\n\nЧтобы выбрать тему, отправьте номер нужной темы."
                
                await update.message.reply_text(topics_text)
                
                # Сбрасываем текущий предмет после добавления тем
                self.current_subject = None
            else:
                await update.message.reply_text("Не удалось распознать темы. Попробуйте еще раз.")
            return

        # Обработка выбора темы (пользователь отправляет номер темы)
        if text.isdigit():
            # Ищем предмет, для которого доступно распределение
            selected_subject = None
            for subject in self.topics.keys():
                if self.is_distribution_started(subject):
                    selected_subject = subject
                    break
            
            if not selected_subject:
                await update.message.reply_text("В настоящее время нет активных распределений тем.")
                return
            
            try:
                topic_number = int(text)
                topics = self.topics[selected_subject]
                
                if topic_number not in topics:
                    await update.message.reply_text("Такого номера темы не существует.")
                    return
                
                # Проверяем, не занята ли уже тема
                if selected_subject in self.registrations and topic_number in self.registrations[selected_subject]:
                    await update.message.reply_text("Эта тема уже занята!")
                    return
                
                # Записываем выбор пользователя
                timestamp = datetime.datetime.now()
                if selected_subject not in self.registrations:
                    self.registrations[selected_subject] = {}
                self.registrations[selected_subject][topic_number] = (user_id, username, timestamp)
                
                # Отправляем подтверждение выбора
                await update.message.reply_text(
                    f"🎉 Вы успешно выбрали тему!\n"
                    f"📖 Тема: {topic_number}. {topics[topic_number]}\n"
                    f"📚 Предмет: {selected_subject}\n"
                    f"⏰ Время выбора: {timestamp.strftime('%H:%M:%S')}"
                )
                
                # Отправляем обновленный список всех тем
                await self.send_topics_update(selected_subject, update)
                
            except ValueError:
                await update.message.reply_text("Пожалуйста, отправьте номер темы (цифру).")

    async def view_topics(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показать текущие темы для всех предметов"""
        if not self.topics:
            await update.message.reply_text("Темы еще не добавлены.")
            return
        
        for subject, topics_dict in self.topics.items():
            await self.send_topics_update(subject, update)

    async def show_results(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показать результаты распределения для всех предметов"""
        if not any(self.registrations.values()):
            await update.message.reply_text("Еще никто не выбрал темы.")
            return
        
        for subject, registrations in self.registrations.items():
            if registrations:
                # Сортируем по времени выбора
                sorted_registrations = sorted(
                    registrations.items(),
                    key=lambda x: x[1][2]  # сортировка по timestamp
                )
                
                results_text = f"📊 Итоговые результаты по предмету '{subject}':\n\n"
                
                for topic_num, (user_id, username, timestamp) in sorted_registrations:
                    topic_name = self.topics[subject][topic_num]
                    time_str = timestamp.strftime('%H:%M:%S')
                    results_text += f"{topic_num}. {topic_name}\n   👤 @{username} (в {time_str})\n\n"
                
                await update.message.reply_text(results_text)

def main():
    """Запуск бота"""
    TOKEN = "8405347117:AAG7h0qxePyQ9mXW3z03DBYOEWafOVP3oBI"
    
    # Создаем приложение
    application = Application.builder().token(TOKEN).build()
    
    # Создаем экземпляр бота с передачей application
    bot = SeminarBot(application)
    
    # Создаем ConversationHandler для административных команд
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("set_subject_time", bot.set_subject_time),
            CommandHandler("cancel_registration", bot.cancel_registration),
            CommandHandler("remove_user", bot.remove_user)
        ],
        states={
            WAITING_FOR_SUBJECT_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_subject_selection)],
            SETTING_DATE_TIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_set_date_time)],
            CANCELING_REGISTRATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_cancel_registration)],
            SELECTING_SUBJECT_FOR_REMOVAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_subject_selection_for_removal)],
            SELECTING_TOPIC_FOR_REMOVAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_topic_selection_for_removal)]
        },
        fallbacks=[CommandHandler("cancel", bot.cancel)]
    )
    
    # Добавляем обработчики
    application.add_handler(CommandHandler("start", bot.start))
    application.add_handler(CommandHandler("new_subject", bot.new_subject))
    application.add_handler(CommandHandler("view_topics", bot.view_topics))
    application.add_handler(CommandHandler("results", bot.show_results))
    application.add_handler(CommandHandler("list_subjects", bot.list_subjects))
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("cancel", bot.cancel))
    application.add_handler(MessageHandler(filters.TEXT & filters.Regex(r'^\d+$'), bot.handle_text))
    
    # Запускаем бота
    print("Бот запущен...")
    application.run_polling()

if __name__ == "__main__":
    main()
