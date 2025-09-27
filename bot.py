import os
import logging
import asyncio
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler, \
    MessageHandler, filters
from telegram.error import BadRequest, Forbidden
import sqlite3
from dotenv import load_dotenv

load_dotenv()

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Проверка обязательных переменных окружения
required_vars = [
    'TELEGRAM_BOT_TOKEN', 
    'CHANNEL_ID', 
    'ADMIN_CHAT_ID',
    'CARD_NUMBER',
    'CARD_HOLDER'
]

missing_vars = [var for var in required_vars if not os.getenv(var)]

if missing_vars:
    logger.error(f"❌ Отсутствуют переменные: {missing_vars}")
    logger.error("Добавьте их в Railway Settings → Variables")
    exit(1)

# Загрузка переменных окружения
CHANNEL_ID = os.getenv('CHANNEL_ID')
ADMIN_CHAT_ID = os.getenv('ADMIN_CHAT_ID')
CARD_NUMBER = os.getenv('CARD_NUMBER')
CARD_HOLDER = os.getenv('CARD_HOLDER')
SUBSCRIPTION_PRICE = os.getenv('SUBSCRIPTION_PRICE', '1000')

# Опциональные переменные
WELCOME_IMAGE_URL = os.getenv('WELCOME_IMAGE_URL', "https://raw.githubusercontent.com/DariaBurd/mindwomen-bot/main/images/welcome.png")

class SubscriptionBot:
    def __init__(self, token):
        if not token:
            logger.error("❌ TELEGRAM_BOT_TOKEN не найден!")
            exit(1)

        self.application = Application.builder().token(token).build()
        self.setup_handlers()
        self.setup_database()

    def setup_database(self):
        """Инициализация базы данных"""
        self.conn = sqlite3.connect('subscriptions.db', check_same_thread=False)
        self.cursor = self.conn.cursor()

        # Таблица пользователей
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                subscription_end DATE,
                joined_date DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Таблица ожидающих платежей
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS pending_payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                amount INTEGER DEFAULT 1000,
                screenshot_sent BOOLEAN DEFAULT FALSE,
                created_date DATETIME DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'pending'
            )
        ''')
        self.conn.commit()

    def setup_handlers(self):
        """Настройка обработчиков"""
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("my_subscription", self.my_subscription))
        self.application.add_handler(CallbackQueryHandler(self.handle_callback))
        self.application.add_handler(MessageHandler(filters.PHOTO, self.handle_screenshot))
        self.application.add_error_handler(self.error_handler)

    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка ошибок"""
        logger.error(f"Ошибка: {context.error}", exc_info=context.error)

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Приветственное сообщение"""
        user = update.effective_user

        welcome_text = """
*Добро пожаловать, моя прекрасная!*

*Что нам на самом деле важно* - это не бояться быть самой собой. Быть среди женщин. Все мы - сестры и отражаясь в глазах сестры мы начинаем видеть себя очень ясно.

*Закрытый Клуб Осознанной Женственности* - это твое безопасное поле, где мы вместе будем практиковать, общаться, создавая общее женское комьюнити осознанности и жизни в моменте здесь и сейчас. 

*Путешествие начинается.* 🌸
        """

        try:
            await update.message.reply_photo(
                photo=WELCOME_IMAGE_URL,
                caption=welcome_text,
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Ошибка загрузки картинки: {e}")
            await update.message.reply_text(welcome_text, parse_mode='Markdown')

        # Проверяем подписку
        subscription_end = self.get_user_subscription(user.id)
        if not subscription_end or subscription_end <= datetime.now():
            await self.offer_payment(update, user)
        else:
            await self.send_welcome_message(update, user, subscription_end)

    async def send_welcome_message(self, update: Update, user, subscription_end):
        """Сообщение для пользователей с активной подпиской"""
        welcome_text = f"""
🌸 *Добро пожаловать в MindWomen, Королева!* 🌸

*Твоя подписка активна до:* {subscription_end.strftime('%d.%m.%Y')}

*Что тебя ждет в нашем сообществе:*
• Ежедневные медитации и практики
• Закрытый чат с сестрами
• Мое бережное сопровождение
• Живые встречи

*Ссылка на канал:* https://t.me/+Yx9m02RdviBmNjAy

*Чтобы проверить статус подписки:* /my_subscription

*Мы рады тебе!* 💖
        """
        await update.message.reply_text(welcome_text, parse_mode='Markdown')

    async def offer_payment(self, update: Update, user):
        """Предложение оплатить подписку"""
        keyboard = [[InlineKeyboardButton(f"💳 Оплатить подписку - {SUBSCRIPTION_PRICE}₽/месяц", callback_data="pay_subscription")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        text = f"""
💰 *Приобрести подписку на MindWomen*

*Тариф:* {SUBSCRIPTION_PRICE}₽ в месяц

*Что включено:*
- Доступ к закрытому каналу
- Все практики и медитации
- Участие в живых встречах
- Поддержка сообщества

Нажмите кнопку ниже для получения реквизитов оплаты.
        """

        await update.message.reply_text(text, parse_mode='Markdown', reply_markup=reply_markup)

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка нажатий кнопок"""
        query = update.callback_query
        await query.answer()

        if query.data == "pay_subscription":
            await self.send_payment_details(query)
        elif query.data.startswith('confirm_'):
            payment_id = query.data.replace('confirm_', '')
            await self.confirm_payment(update, context, payment_id)
        elif query.data.startswith('reject_'):
            payment_id = query.data.replace('reject_', '')
            await self.reject_payment(update, context, payment_id)

    async def send_payment_details(self, query):
        """Отправляет реквизиты для перевода"""
        user = query.from_user
        
        # Сохраняем запрос на оплату
        self.cursor.execute('''
            INSERT INTO pending_payments (user_id, amount) 
            VALUES (?, ?)
        ''', (user.id, SUBSCRIPTION_PRICE))
        self.conn.commit()

        payment_text = f"""
💳 *Оплата подписки MindWomen*

*Сумма:* {SUBSCRIPTION_PRICE}₽ в месяц

*Реквизиты для перевода:*
▫️ *Номер карты:* `{CARD_NUMBER}`
▫️ *Получатель:* {CARD_HOLDER}

*Инструкция:*
1. Переведите {SUBSCRIPTION_PRICE}₽ на указанную карту
2. Сделайте скриншот чека или перевода
3. Пришлите скриншот в этот чат

✅ *После проверки вы будете добавлены в закрытый канал.*
*Обычно проверка занимает до 24 часов.*
        """

        await query.message.reply_text(payment_text, parse_mode='Markdown')

    async def handle_screenshot(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка скриншотов от пользователей"""
        user = update.effective_user
        
        if update.message.photo:
            # Находим ожидающий платеж пользователя
            self.cursor.execute('''
                SELECT id FROM pending_payments 
                WHERE user_id = ? AND status = 'pending'
                ORDER BY created_date DESC LIMIT 1
            ''', (user.id,))
            
            result = self.cursor.fetchone()
            
            if result:
                payment_id = result[0]
                
                # Помечаем как отправленный
                self.cursor.execute('''
                    UPDATE pending_payments SET screenshot_sent = TRUE WHERE id = ?
                ''', (payment_id,))
                self.conn.commit()

                await update.message.reply_text(
                    "✅ *Скриншот получен!*\n\n"
                    "Платеж передан на проверку. Обычно это занимает до 24 часов.\n"
                    "Вы получите уведомление, когда будете добавлены в канал.",
                    parse_mode='Markdown'
                )

                # Уведомляем администратора
                await self.notify_admin(context.bot, user, payment_id, update.message.photo[-1].file_id)
            else:
                await update.message.reply_text(
                    "❌ *Сначала выберите опцию оплаты*\n\n"
                    "Нажмите /start и выберите 'Оплатить подписку'",
                    parse_mode='Markdown'
                )

    async def notify_admin(self, bot, user, payment_id, screenshot_file_id):
        """Уведомляет администратора о новом платеже"""
        admin_text = f"""
🔄 *Новый платеж на проверку*

*Пользователь:* {user.first_name} {user.last_name or ''}
*Username:* @{user.username or 'нет'}
*ID:* {user.id}
*Сумма:* {SUBSCRIPTION_PRICE}₽
*Время:* {datetime.now().strftime('%d.%m.%Y %H:%M')}

*Для подтверждения нажмите кнопку:*
        """

        keyboard = [
            [
                InlineKeyboardButton("✅ Подтвердить платеж", callback_data=f"confirm_{payment_id}"),
                InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{payment_id}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        try:
            await bot.send_photo(
                chat_id=ADMIN_CHAT_ID,
                photo=screenshot_file_id,
                caption=admin_text,
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
        except Exception as e:
            logger.error(f"Ошибка отправки уведомления админу: {e}")

    async def confirm_payment(self, update: Update, context: ContextTypes.DEFAULT_TYPE, payment_id):
        """Подтверждает платеж и добавляет в канал"""
        query = update.callback_query
        await query.answer()

        # Получаем информацию о платеже
        self.cursor.execute('''
            SELECT user_id FROM pending_payments WHERE id = ?
        ''', (payment_id,))
        
        result = self.cursor.fetchone()
        if not result:
            await query.message.reply_text("❌ Платеж не найден")
            return

        user_id = result[0]

        # Активируем подписку (1 месяц)
        subscription_end = datetime.now() + timedelta(days=30)
        await self.save_subscription(user_id, subscription_end, context.bot)

        # Добавляем в канал (исправляем CHANNEL_ID)
        try:
            # Убедимся, что CHANNEL_ID правильный (должен начинаться с -100 для супергрупп)
            channel_id = self.get_correct_channel_id(CHANNEL_ID)
            
            await context.bot.restrict_chat_member(
                chat_id=channel_id,
                user_id=user_id,
                permissions={
                    'can_send_messages': True,
                    'can_send_media_messages': True,
                    'can_send_polls': True,
                    'can_send_other_messages': True,
                    'can_add_web_page_previews': True,
                    'can_change_info': False,
                    'can_invite_users': False,
                    'can_pin_messages': False
                }
            )
            logger.info(f"✅ Пользователь {user_id} добавлен в канал {channel_id}")
            
        except BadRequest as e:
            if "chat not found" in str(e).lower():
                logger.error(f"❌ Канал не найден: {CHANNEL_ID}. Проверьте CHANNEL_ID в настройках.")
                await query.message.reply_text("❌ Ошибка: канал не найден. Проверьте настройки бота.")
            else:
                logger.error(f"❌ Ошибка добавления в канал: {e}")
        except Exception as e:
            logger.error(f"❌ Неизвестная ошибка при добавлении в канал: {e}")

        # Уведомляем пользователя
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"""
🎉 *Платеж подтвержден!*

Ваша подписка на MindWomen активирована до {subscription_end.strftime('%d.%m.%Y')}

*Ссылка на закрытый канал:* https://t.me/+Yx9m02RdviBmNjAy

Добро пожаловать в Клуб! 💖
                """,
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Ошибка уведомления пользователя: {e}")

        # Обновляем статус платежа
        self.cursor.execute('''
            UPDATE pending_payments SET status = 'confirmed' WHERE id = ?
        ''', (payment_id,))
        self.conn.commit()

        await query.edit_message_caption(caption="✅ *Платеж подтвержден*\n\nПользователь добавлен в канал")

    def get_correct_channel_id(self, channel_id):
        """Корректирует ID канала для Telegram API"""
        # Если это username (@channel), оставляем как есть
        if isinstance(channel_id, str) and channel_id.startswith('@'):
            return channel_id
        
        # Если это числовой ID, убедимся что он в правильном формате
        try:
            channel_id_int = int(channel_id)
            # Для супергрупп ID должен быть отрицательным и начинаться с -100
            if channel_id_int < 0 and not str(channel_id_int).startswith('-100'):
                # Преобразуем в формат -100 + исходный ID
                return f"-100{abs(channel_id_int)}"
            return channel_id_int
        except ValueError:
            # Если это не число, возвращаем как есть (скорее всего username)
            return channel_id

    async def save_subscription(self, user_id, subscription_end, bot):
        """Сохраняет информацию о подписке в БД (исправленная версия)"""
        try:
            # Получаем информацию о пользователе через await
            user_chat = await bot.get_chat(user_id)
            
            self.cursor.execute('''
                INSERT OR REPLACE INTO users (user_id, username, first_name, last_name, subscription_end)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                user_id, 
                user_chat.username, 
                user_chat.first_name, 
                user_chat.last_name, 
                subscription_end
            ))
            self.conn.commit()
            logger.info(f"✅ Подписка сохранена для пользователя {user_id}")
            
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения подписки: {e}")
            # Если не удалось получить данные пользователя, сохраняем хотя бы ID
            self.cursor.execute('''
                INSERT OR REPLACE INTO users (user_id, subscription_end)
                VALUES (?, ?)
            ''', (user_id, subscription_end))
            self.conn.commit()

    async def reject_payment(self, update: Update, context: ContextTypes.DEFAULT_TYPE, payment_id):
        """Отклоняет платеж"""
        query = update.callback_query
        await query.answer()

        self.cursor.execute('''
            SELECT user_id FROM pending_payments WHERE id = ?
        ''', (payment_id,))
        
        result = self.cursor.fetchone()
        if result:
            user_id = result[0]
            
            # Уведомляем пользователя
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text="❌ *Платеж отклонен*\n\nПожалуйста, свяжитесь с администратором.",
                    parse_mode='Markdown'
                )
            except Exception as e:
                logger.error(f"Ошибка уведомления пользователя: {e}")

        self.cursor.execute('''
            UPDATE pending_payments SET status = 'rejected' WHERE id = ?
        ''', (payment_id,))
        self.conn.commit()

        await query.edit_message_caption(caption="❌ *Платеж отклонен*")

    def get_user_subscription(self, user_id):
        """Получает информацию о подписке пользователя"""
        try:
            self.cursor.execute(
                'SELECT subscription_end FROM users WHERE user_id = ?',
                (user_id,)
            )
            result = self.cursor.fetchone()
            if result and result[0]:
                return datetime.strptime(result[0], '%Y-%m-%d %H:%M:%S')
            return None
        except Exception as e:
            logger.error(f"Ошибка получения подписки: {e}")
            return None

    async def my_subscription(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показывает информацию о подписке пользователя"""
        user = update.effective_user
        subscription_end = self.get_user_subscription(user.id)

        if subscription_end and subscription_end > datetime.now():
            text = f"""
✅ *Ваша подписка активна*

*Действует до:* {subscription_end.strftime('%d.%m.%Y')}
*Осталось:* {(subscription_end - datetime.now()).days} дней

*Ссылка на канал:* https://t.me/+Yx9m02RdviBmNjAy
            """
        else:
            text = """
❌ *У вас нет активной подписки*

Для доступа к закрытому сообществу MindWomen приобретите подписку.

Нажмите /start для оплаты.
            """

        await update.message.reply_text(text, parse_mode='Markdown')

    async def check_subscriptions(self, context: ContextTypes.DEFAULT_TYPE):
        """Проверяет подписки и удаляет тех, у кого закончилась"""
        now = datetime.now()

        try:
            self.cursor.execute(
                'SELECT user_id FROM users WHERE subscription_end < ?',
                (now.strftime('%Y-%m-%d %H:%M:%S'),)
            )
            expired_users = self.cursor.fetchall()

            for user_id, in expired_users:
                try:
                    # Удаляем из канала
                    channel_id = self.get_correct_channel_id(CHANNEL_ID)
                    await context.bot.ban_chat_member(chat_id=channel_id, user_id=user_id)
                    
                    # Уведомляем пользователя
                    try:
                        await context.bot.send_message(
                            chat_id=user_id,
                            text="❌ Ваша подписка закончилась. Для продления нажмите /start",
                            parse_mode='Markdown'
                        )
                    except:
                        pass

                    logger.info(f"Удален пользователь {user_id} - закончилась подписка")

                except Exception as e:
                    logger.error(f"Ошибка при удалении пользователя {user_id}: {e}")

        except Exception as e:
            logger.error(f"Ошибка проверки подписок: {e}")

    def run(self):
        """Запуск бота"""
        logger.info("Бот запускается...")
        self.application.run_polling()

if __name__ == "__main__":
    BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
    if not BOT_TOKEN:
        print("❌ ОШИБКА: TELEGRAM_BOT_TOKEN не найден!")
        exit(1)

    try:
        bot = SubscriptionBot(BOT_TOKEN)
        bot.run()
    except Exception as e:
        logger.error(f"Критическая ошибка запуска бота: {e}")
        exit(1)


