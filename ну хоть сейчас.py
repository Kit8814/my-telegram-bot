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
SETTING_TIME, CANCELING_REGISTRATION, WAITING_FOR_SUBJECT_TIME, SELECTING_SUBJECT_FOR_REMOVAL, SELECTING_TOPIC_FOR_REMOVAL = range(5)

class SeminarBot:
    def __init__(self, application):
        self.topics = {}  # {subject: {number: topic}}
        self.registrations = {}  # {subject: {number: (user_id, username, timestamp)}}
        self.start_times = {}  # {subject: datetime} - время начала для каждого предмета
        self.current_subject = None
        self.waiting_for_topics = False
        self.admin_id = None  # ID администратора
        self.distribution_tasks = {}  # {subject: task} - задачи для автоматического начала распределения
        self.reminder_tasks = {}    # {subject: task} - задачи для напоминаний
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
            "/set_subject_time - установить время начала для предмета (только для админа)\n"
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
        return WAITING_FOR_SUBJECT_TIME

    async def set_subject_time(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Установить время начала для конкретного предмета (только для админа)"""
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
        
        subjects_text += "\nВведите номер предмета или название для установки времени:"
        await update.message.reply_text(subjects_text)
        
        return WAITING_FOR_SUBJECT_TIME

    async def handle_subject_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка выбора предмета для установки времени"""
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
            f"Выбран предмет: {subject}\n"
            "Введите время начала распределения в формате ЧЧ:ММ (например, 14:30):"
        )
        return SETTING_TIME

    async def handle_set_time(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка ввода времени начала для предмета"""
        time_input = update.message.text.strip()
        subject = context.user_data.get('selected_subject')
        
        if not subject:
            await update.message.reply_text("Ошибка: предмет не выбран.")
            return ConversationHandler.END
        
        # Проверяем формат времени
        time_pattern = r'^([0-1]?[0-9]|2[0-3]):([0-5][0-9])$'
        if not re.match(time_pattern, time_input):
            await update.message.reply_text("Неверный формат времени. Используйте ЧЧ:ММ (например, 14:30)")
            return SETTING_TIME
        
        # Устанавливаем время начала для предмета
        now = datetime.datetime.now()
        hours, minutes = map(int, time_input.split(':'))
        start_time = now.replace(hour=hours, minute=minutes, second=0, microsecond=0)
        
        if start_time < now:
            start_time = start_time + datetime.timedelta(days=1)
        
        self.start_times[subject] = start_time
        
        # Запускаем задачу для автоматического начала распределения и напоминания
        await self.schedule_distribution_start(subject, start_time)
        await self.schedule_reminder(subject, start_time)
        
        await update.message.reply_text(
            f"Время начала распределения для предмета '{subject}' установлено: {start_time.strftime('%d.%m.%Y %H:%M')}\n"
            f"Напоминание будет отправлено за 5 минут."
        )
        
        # Очищаем временные данные
        context.user_data.pop('selected_subject', None)
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
                if self.is_distribution_started(subject):
                    topics_text += f"\n✅ Распределение активно с {start_time.strftime('%H:%M')}"
                else:
                    time_left = start_time - datetime.datetime.now()
                    hours, remainder = divmod(time_left.total_seconds(), 3600)
                    minutes, seconds = divmod(remainder, 60)
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
                if datetime.datetime.now() >= start_time:
                    status = "✅ Распределение началось"
                else:
                    time_left = start_time - datetime.datetime.now()
                    hours, remainder = divmod(time_left.total_seconds(), 3600)
                    minutes, seconds = divmod(remainder, 60)
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
                
                return ConversationHandler.END
                
            except ValueError:
                await update.message.reply_text("Пожалуйста, введите номер темы (цифру).")
                return CANCELING_REGISTRATION

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
                f"Предмет: {subject}"
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
        context.user_data.clear()
        
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

    def get_active_subjects(self):
        """Возвращает список предметов, для которых распределение УЖЕ началось"""
        active_subjects = []
        for subject in self.topics.keys():
            if self.is_distribution_started(subject):
                active_subjects.append(subject)
        return active_subjects

    async def handle_text_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка текстовых сообщений (для состояний)"""
        # Если мы в состоянии ожидания ввода предмета для новых тем
        if self.waiting_for_topics and not self.current_subject:
            self.current_subject = update.message.text.strip()
            self.topics[self.current_subject] = {}
            self.registrations[self.current_subject] = {}
            self.waiting_for_topics = False
            
            await update.message.reply_text(
                f"Предмет '{self.current_subject}' установлен. Теперь отправьте список тем в формате:\n"
                "1. Тема 1\n"
                "2. Тема 2\n"
                "3. Тема 3\n"
                "..."
            )
            return WAITING_FOR_SUBJECT_TIME

        # Если ожидаем список тем
        elif self.current_subject and not self.topics[self.current_subject]:
            text = update.message.text.strip()
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
                    topics_text += f"\nРаспределение начнется: {start_time.strftime('%d.%m.%Y %H:%M')}"
                topics_text += "\n\nЧтобы выбрать тему, отправьте номер нужной темы."
                
                await update.message.reply_text(topics_text)
                
                # Сбрасываем текущий предмет после добавления тем
                self.current_subject = None
                return ConversationHandler.END
            else:
                await update.message.reply_text("Не удалось распознать темы. Попробуйте еще раз.")
                return WAITING_FOR_SUBJECT_TIME

    async def handle_topic_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка выбора темы пользователем"""
        text = update.message.text.strip()
        
        if not text.isdigit():
            await update.message.reply_text("Пожалуйста, введите номер темы (цифру).")
            return
        
        topic_number = int(text)
        user_id = update.effective_user.id
        username = update.effective_user.username or update.effective_user.first_name
        
        # Ищем активные предметы
        active_subjects = self.get_active_subjects()
        
        if not active_subjects:
            await update.message.reply_text("В настоящее время нет активных распределений тем.")
            return
        
        # Если активен только один предмет, используем его
        if len(active_subjects) == 1:
            subject = active_subjects[0]
        else:
            # Если активных несколько, проверяем ответ на сообщение
            if update.message.reply_to_message:
                replied_text = update.message.reply_to_message.text
                for possible_subject in active_subjects:
                    if possible_subject in replied_text:
                        subject = possible_subject
                        break
                else:
                    await update.message.reply_text("Не могу определить предмет. Пожалуйста, ответьте на сообщение с темами нужного предмета.")
                    return
            else:
                await update.message.reply_text("Доступно несколько предметов. Пожалуйста, ответьте на сообщение с темами нужного предмета.")
                return
        
        # Проверяем существование темы
        if topic_number not in self.topics[subject]:
            await update.message.reply_text("Такого номера темы не существует.")
            return
        
        # Проверяем, не занята ли тема
        if subject in self.registrations and topic_number in self.registrations[subject]:
            await update.message.reply_text("Эта тема уже занята!")
            return
        
        # Записываем выбор
        timestamp = datetime.datetime.now()
        if subject not in self.registrations:
            self.registrations[subject] = {}
        self.registrations[subject][topic_number] = (user_id, username, timestamp)
        
        await update.message.reply_text(
            f"🎉 Вы успешно выбрали тему!\n"
            f"📖 Тема: {topic_number}. {self.topics[subject][topic_number]}\n"
            f"📚 Предмет: {subject}\n"
            f"⏰ Время выбора: {timestamp.strftime('%H:%M:%S')}"
        )
        
        await self.send_topics_update(subject, update)

    async def handle_general_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка общего текста (не в состоянии ConversationHandler)"""
        # Если это номер темы, обрабатываем выбор
        if update.message.text.strip().isdigit():
            await self.handle_topic_selection(update, context)
        else:
            await update.message.reply_text("Я не понимаю эту команду. Используйте /start для просмотра доступных команд.")

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
            CommandHandler("new_subject", bot.new_subject),
            CommandHandler("set_subject_time", bot.set_subject_time),
            CommandHandler("cancel_registration", bot.cancel_registration),
            CommandHandler("remove_user", bot.remove_user)
        ],
        states={
            WAITING_FOR_SUBJECT_TIME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_text_input)
            ],
            SETTING_TIME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_set_time)
            ],
            CANCELING_REGISTRATION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_cancel_registration)
            ],
            SELECTING_SUBJECT_FOR_REMOVAL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_subject_selection_for_removal)
            ],
            SELECTING_TOPIC_FOR_REMOVAL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_topic_selection_for_removal)
            ],
        },
        fallbacks=[CommandHandler("cancel", bot.cancel)],
        allow_reentry=True
    )
    
    # Добавляем обработчики
    application.add_handler(CommandHandler("start", bot.start))
    application.add_handler(CommandHandler("view_topics", bot.view_topics))
    application.add_handler(CommandHandler("results", bot.show_results))
    application.add_handler(CommandHandler("list_subjects", bot.list_subjects))
    application.add_handler(CommandHandler("cancel", bot.cancel))
    application.add_handler(conv_handler)
    
    # Обработчик для общего текста (должен быть последним)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_general_text))
    
    # Запускаем бота
    print("Бот запущен...")
    application.run_polling()

if __name__ == "__main__":
    main()
