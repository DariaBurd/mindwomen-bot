import os
import logging
import asyncio
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler, PreCheckoutQueryHandler, \
    MessageHandler, filters
from telegram.error import BadRequest, Forbidden
from yandex_checkout import Configuration, Payment
import sqlite3
import uuid
from dotenv import load_dotenv

load_dotenv()

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

required_vars = [
    'TELEGRAM_BOT_TOKEN',
    'YUKASSA_SHOP_ID',
    'YUKASSA_SECRET_KEY',
    'YUKASSA_PROVIDER_TOKEN',
    'CHANNEL_ID',
    'ADMIN_CHAT_ID'
]

missing_vars = []
for var in required_vars:
    if not os.getenv(var):
        missing_vars.append(var)

if missing_vars:
    logger.error(f"❌ Отсутствуют переменные: {missing_vars}")
    logger.error("Проверь Railway Settings → Variables")
    exit(1)

# Конфигурация ЮKassa
Configuration.account_id = os.getenv('YUKASSA_SHOP_ID')
Configuration.secret_key = os.getenv('YUKASSA_SECRET_KEY')

# ID канала/чата
CHANNEL_ID = os.getenv('CHANNEL_ID')
ADMIN_CHAT_ID = os.getenv('ADMIN_CHAT_ID')

# Добавила URL картинки
WELCOME_IMAGE_URL = "https://raw.githubusercontent.com/DariaBurd/mindwomen-bot/main/images/welcome.png"


class SubscriptionBot:
    def __init__(self, token):

        if not token or token == "your_bot_token_here":
            logger.error("❌ TELEGRAM_BOT_TOKEN не найден или не установлен!")
            logger.error("Проверь Railway Variables → TELEGRAM_BOT_TOKEN")
            exit(1)

        self.application = Application.builder().token(token).build()
        self.setup_handlers()
        self.setup_database()
        self.setup_tasks()
        self.application.add_error_handler(self.error_handler)

    def setup_database(self):
        """Инициализация базы данных"""
        self.conn = sqlite3.connect('subscriptions.db', check_same_thread=False)
        self.cursor = self.conn.cursor()

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
        self.conn.commit()

    def setup_tasks(self):
        """Настройка фоновых задач"""
        # self.application.job_queue.run_repeating(
        #     self.check_subscriptions,
        #     interval=3600,  # Проверка каждый час
        #     first=10
        # )
        pass

    def setup_handlers(self):
        """Настройка обработчиков"""
        # Команды
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("my_subscription", self.my_subscription))

        # Обработчики платежей
        self.application.add_handler(PreCheckoutQueryHandler(self.precheckout))
        self.application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, self.successful_payment))
        self.application.add_handler(CallbackQueryHandler(self.handle_callback))

    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка ошибок"""
        logger.error(f"Ошибка в обработчике: {context.error}", exc_info=context.error)

        try:
            if update and update.effective_message:
                await update.effective_message.reply_text(
                    "❌ Произошла ошибка. Пожалуйста, попробуйте позже или обратитесь к администратору."
                )
        except Exception as e:
            logger.error(f"Ошибка при отправке сообщения об ошибке: {e}")

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Приветственное сообщение с картинкой"""
        user = update.effective_user

        # Красивое приветствие как на скриншоте
        welcome_text = """
*Добро пожаловать, моя прекрасная!*

*Что нам на самом деле важно* - это не бояться быть самой собой. Быть среди женщин. Все мы - сестры и отражаясь в глазах сестры мы начинаем видеть себя очень ясно.

*Закрытый Клуб Осознанной Женственности* - это твое безопасное поле, где мы вместе будем практиковать, общаться, создавая общее женское комьюнити осознанности и жизни в моменте здесь и сейчас. 

*Путешествие начинается.* 🌸
        """

        # Пытаемся отправить с картинкой
        try:
            await update.message.reply_photo(
                photo=WELCOME_IMAGE_URL,
                caption=welcome_text,
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Ошибка загрузки картинки: {e}")
            await update.message.reply_text(
                welcome_text,
                parse_mode='Markdown'
            )

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
        keyboard = [
            [
                InlineKeyboardButton("💳 Месяц - 888₽", callback_data="sub_month"),
                InlineKeyboardButton("💎 3 месяца - 2500₽", callback_data="sub_3months"),
            ],
            [
                InlineKeyboardButton("👑 Год - 10100₽", callback_data="sub_year"),
            ]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)

        text = """
💰 *Приобрести подписку на MindWomen*

*Выберите тариф:*
• *Месяц* - 888₽ - Идеально для начала
• *3 месяца* - 2500₽  - Глубокое погружение
• *Год* - 10100₽  - Полное преображение

*Что включено:*
- Доступ к закрытому каналу
- Все практики и медитации
- Участие в живых встречах
- Индивидуальные разборы в Матрице Судьбы
        """

        await update.message.reply_text(
            text,
            parse_mode='Markdown',
            reply_markup=reply_markup
        )

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка нажатий кнопок"""
        query = update.callback_query
        await query.answer()

        if query.data.startswith('sub_'):
            period = query.data.replace('sub_', '')
            await self.create_invoice(query, period)

    async def create_invoice(self, query, period):
        """Создание счета на оплату"""
        # Цены
        prices = {
            'month': 88800,
            '3months': 250000,
            'year': 1010000
        }

        periods_text = {
            'month': '1 месяц',
            '3months': '3 месяца',
            'year': '1 год'
        }

        amount = prices[period]
        description = f"Подписка MindWomen ({periods_text[period]})"

        # Создаем инвойс
        try:
            await query.message.reply_invoice(
                title="Подписка на MindWomen",
                description=description,
                payload=f"subscription_{period}_{query.from_user.id}",
                provider_token=os.getenv('YUKASSA_PROVIDER_TOKEN'),
                currency="RUB",
                prices=[{"label": description, "amount": amount}],
                need_name=True,
                need_email=True,
                need_phone_number=False,
                send_email_to_provider=True
            )
        except Exception as e:
            logger.error(f"Ошибка создания инвойса: {e}")
            await query.message.reply_text("❌ Ошибка при создании счета. Попробуйте позже.")

    async def precheckout(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Предварительная проверка платежа"""
        query = update.pre_checkout_query
        await query.answer(ok=True)

    async def successful_payment(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Успешная оплата"""
        payment = update.message.successful_payment
        user = update.effective_user

        logger.info(f"Успешный платеж от {user.id} - {payment.total_amount}₽")

        # Определяем период подписки из payload
        payload_parts = payment.invoice_payload.split('_')
        if len(payload_parts) < 3:
            logger.error(f"Неверный формат payload: {payment.invoice_payload}")
            await update.message.reply_text("❌ Ошибка обработки платежа. Свяжитесь с администратором.")
            return

        period = payload_parts[1]

        # Рассчитываем дату окончания подписки
        subscription_end = self.calculate_subscription_end(period)

        # Сохраняем в базу данных
        self.save_subscription(user, subscription_end)

        # Добавляем пользователя в канал
        try:
            # Используем restrict_chat_member вместо unban_chat_member
            await context.bot.restrict_chat_member(
                chat_id=CHANNEL_ID,
                user_id=user.id,
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
            logger.info(f"Пользователь {user.id} добавлен в канал")
            
        except BadRequest as e:
            if "chat not found" in str(e).lower():
                logger.error(f"Канал не найден: {CHANNEL_ID}")
                await update.message.reply_text("❌ Ошибка доступа к каналу. Администратор уведомлен.")
            elif "user is an administrator" in str(e).lower():
                logger.info(f"Пользователь {user.id} уже админ канала")
            elif "user not found" in str(e).lower():
                logger.error(f"Пользователь {user.id} не найден")
            else:
                logger.error(f"Ошибка добавления в канал: {e}")
                await update.message.reply_text("❌ Ошибка доступа к каналу. Администратор уведомлен.")
                
        except Forbidden as e:
            logger.error(f"Нет прав для добавления в канал: {e}")
            await update.message.reply_text("❌ Ошибка доступа к каналу. Администратор уведомлен.")
            
        except Exception as e:
            logger.error(f"Неизвестная ошибка при добавлении в канал: {e}")
            await update.message.reply_text("❌ Ошибка доступа к каналу. Администратор уведомлен.")

        # Отправляем приветственное сообщение
        welcome_text = f"""
🎉 *Поздравляем с приобретением подписки!* 🎉

*Твоя подписка активна до:* {subscription_end.strftime('%d.%m.%Y')}

*Ссылка на закрытый канал:* https://t.me/+Yx9m02RdviBmNjAy

*Что делать дальше:*
1. Перейди в канал по ссылке выше
2. Напиши приветственное сообщение о себе
3. Изучи закрепленные материалы
4. Участвуй в ежедневных активностях

*Для проверки статуса подписки:* /my_subscription
        """

        await update.message.reply_text(welcome_text, parse_mode='Markdown')

        # Уведомляем владелицу
        await self.notify_admins(user, payment, subscription_end, context.bot)

    def calculate_subscription_end(self, period):
        """Рассчитывает дату окончания подписки"""
        now = datetime.now()
        if period == 'month':
            return now + timedelta(days=30)
        elif period == '3months':
            return now + timedelta(days=90)
        elif period == 'year':
            return now + timedelta(days=365)
        return now + timedelta(days=30)

    def save_subscription(self, user, subscription_end):
        """Сохраняет информацию о подписке в БД"""
        try:
            self.cursor.execute('''
                INSERT OR REPLACE INTO users (user_id, username, first_name, last_name, subscription_end)
                VALUES (?, ?, ?, ?, ?)
            ''', (user.id, user.username, user.first_name, user.last_name, subscription_end))
            self.conn.commit()
            logger.info(f"Подписка сохранена для пользователя {user.id}")
        except Exception as e:
            logger.error(f"Ошибка сохранения в БД: {e}")

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
                    await context.bot.ban_chat_member(
                        chat_id=CHANNEL_ID,
                        user_id=user_id
                    )

                    # Отправляем уведомление пользователю
                    try:
                        await context.bot.send_message(
                            chat_id=user_id,
                            text="❌ *Ваша подписка на MindWomen закончилась*\n\nЧтобы продолжить участие в сообществе, продлите подписку через /start",
                            parse_mode='Markdown'
                        )
                    except:
                        pass  # Пользователь заблокировал бота

                    # Удаляем из базы данных
                    self.cursor.execute(
                        'DELETE FROM users WHERE user_id = ?',
                        (user_id,)
                    )
                    self.conn.commit()

                    logger.info(f"Удален пользователь {user_id} - закончилась подписка")

                except Exception as e:
                    logger.error(f"Ошибка при удалении пользователя {user_id}: {e}")

        except Exception as e:
            logger.error(f"Ошибка проверки подписок: {e}")

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

Нажмите /start для выбора тарифа и оплаты.
            """

        await update.message.reply_text(text, parse_mode='Markdown')

    async def notify_admins(self, user, payment, subscription_end, bot):
        """Уведомляет владелицу о новой подписке"""
        admin_text = f"""
👑 *Новая подписка MindWomen*

*Пользователь:* {user.first_name} {user.last_name or ''}
*Username:* @{user.username or 'нет'}
*ID:* {user.id}
*Тариф:* {payment.total_amount / 100}₽
*Подписка до:* {subscription_end.strftime('%d.%m.%Y')}
*Время:* {datetime.now().strftime('%Y-%m-%d %H:%M')}
        """

        # Отправляем сообщение владелице
        try:
            await bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=admin_text,
                parse_mode='Markdown'
            )
            logger.info(f"Уведомление отправлено админу {ADMIN_CHAT_ID}")
        except Exception as e:
            logger.error(f"Ошибка отправки уведомления админу: {e}")

    def run(self):
        """Запуск бота"""
        logger.info("Бот запускается...")
        self.application.run_polling()


# Запуск бота
if __name__ == "__main__":
    BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')

    if not BOT_TOKEN:
        print("❌ ОШИБКА: TELEGRAM_BOT_TOKEN не найден!")
        print("Проверь что в Railway Variables добавлено:")
        print("TELEGRAM_BOT_TOKEN=токен_твоего_бота")
        exit(1)

    try:
        bot = SubscriptionBot(BOT_TOKEN)
        bot.run()
    except Exception as e:
        logger.error(f"Критическая ошибка запуска бота: {e}")
        exit(1)
