import os
import logging
import asyncio
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler, PreCheckoutQueryHandler, \
    MessageHandler, filters
from telegram.error import BadRequest
from yandex_checkout import Configuration, Payment
import sqlite3
import uuid

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Конфигурация ЮKassa
Configuration.account_id = os.getenv('YUKASSA_SHOP_ID')
Configuration.secret_key = os.getenv('YUKASSA_SECRET_KEY')

# ID канала/чата
CHANNEL_ID = os.getenv('CHANNEL_ID')
ADMIN_CHAT_ID = os.getenv('ADMIN_CHAT_ID')

# 🔥 ИЗМЕНЕНИЕ: Добавила URL картинки
WELCOME_IMAGE_URL = "https://raw.githubusercontent.com/DariaBurd/mindwomen-bot/main/images/welcome.png"


class SubscriptionBot:
    def __init__(self, token):
        self.application = Application.builder().token(token).build()
        self.setup_handlers()
        self.setup_database()
        self.setup_tasks()

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
        self.application.job_queue.run_repeating(
            self.check_subscriptions,
            interval=3600,  # Проверка каждый час
            first=10
        )

    def setup_handlers(self):
        """Настройка обработчиков"""
        # Команды
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("my_subscription", self.my_subscription))

        # Обработчики платежей
        self.application.add_handler(PreCheckoutQueryHandler(self.precheckout))
        self.application.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, self.successful_payment))
        self.application.add_handler(CallbackQueryHandler(self.handle_callback))

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Приветственное сообщение с картинкой"""
        user = update.effective_user

        # 🔥 ИЗМЕНЕНИЕ: Красивое приветствие как на скриншоте
        welcome_text = """
*(start *eze.*)*

*Что нам на самом деле важно* - это не бояться быть самой собой. Быть среди женщин. Все мы - сестры и отражаясь в глазах сестры мы начинаем видеть себя очень ясно.

*Закрытый Клуб Осознанной Женственности* - это твое безопасное поле, где мы вместе будем практиковать, общаться, создавая общее женское комьюнити осознанности и жизни в моменте здесь и сейчас. 

*Путешествие начинается.* 🌸
        """

        #  Пытаемся отправить с картинкой
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

*Ссылка на канал:* @mindwomen_channel

*Чтобы проверить статус подписки:* /my_subscription

*Мы рады тебе!* 💖
        """

        await update.message.reply_text(welcome_text, parse_mode='Markdown')

    async def offer_payment(self, update: Update, user):
        """Предложение оплатить подписку"""
        keyboard = [
            [
                InlineKeyboardButton("💳 Месяц - 555₽", callback_data="sub_month"),
                InlineKeyboardButton("💎 3 месяца - 1555₽", callback_data="sub_3months"),
            ],
            [
                InlineKeyboardButton("👑 Год - 6130₽", callback_data="sub_year"),
            ]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)

        text = """
💰 *Приобрести подписку на MindWomen*

*Выберите тариф:*
• *Месяц* - 555₽ - Идеально для начала
• *3 месяца* - 1555₽  - Глубокое погружение
• *Год* - 6120₽  - Полное преображение

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
        #  Цены
        prices = {
            'month': 555,
            '3months': 1555,
            'year': 6130
        }

        periods_text = {
            'month': '1 месяц',
            '3months': '3 месяца',
            'year': '1 год'
        }

        amount = prices[period]
        description = f"Подписка MindWomen ({periods_text[period]})"

        # Создаем инвойс
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

    async def precheckout(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Предварительная проверка платежа"""
        query = update.pre_checkout_query
        await query.answer(ok=True)

    async def successful_payment(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Успешная оплата"""
        payment = update.message.successful_payment
        user = update.effective_user

        # Определяем период подписки из payload
        payload_parts = payment.invoice_payload.split('_')
        period = payload_parts[1]

        # Рассчитываем дату окончания подписки
        subscription_end = self.calculate_subscription_end(period)

        # Сохраняем в базу данных
        self.save_subscription(user, subscription_end)

        # Добавляем пользователя в канал
        try:
            await self.application.bot.unban_chat_member(  # Используем unban
                chat_id=CHANNEL_ID,
                user_id=user.id,
                only_if_banned=True
            )
        except BadRequest as e:
            logger.error(f"Ошибка добавления в канал: {e}")

        # Отправляем приветственное сообщение
        welcome_text = f"""
🎉 *Поздравляем с приобретением подписки!* 🎉

*Твоя подписка активна до:* {subscription_end.strftime('%d.%m.%Y')}

*Ссылка на закрытый канал:* @mindwomen_channel

*Что делать дальше:*
1. Перейди в канал по ссылке выше
2. Напиши приветственное сообщение о себе
3. Изучи закрепленные материалы
4. Участвуй в ежедневных активностях

*Для проверки статуса подписки:* /my_subscription
        """

        await update.message.reply_text(welcome_text, parse_mode='Markdown')

        #  Уведомляем владелицу с передачей context
        await self.notify_admins(user, payment, subscription_end, context)

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
        self.cursor.execute('''
            INSERT OR REPLACE INTO users (user_id, username, first_name, last_name, subscription_end)
            VALUES (?, ?, ?, ?, ?)
        ''', (user.id, user.username, user.first_name, user.last_name, subscription_end))
        self.conn.commit()

    def get_user_subscription(self, user_id):
        """Получает информацию о подписке пользователя"""
        self.cursor.execute(
            'SELECT subscription_end FROM users WHERE user_id = ?',
            (user_id,)
        )
        result = self.cursor.fetchone()
        if result and result[0]:
            return datetime.strptime(result[0], '%Y-%m-%d %H:%M:%S')
        return None

    async def check_subscriptions(self, context: ContextTypes.DEFAULT_TYPE):
        """Проверяет подписки и удаляет тех, у кого закончилась"""
        now = datetime.now()

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

    async def my_subscription(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Показывает информацию о подписке пользователя"""
        user = update.effective_user
        subscription_end = self.get_user_subscription(user.id)

        if subscription_end and subscription_end > datetime.now():
            text = f"""
✅ *Ваша подписка активна*

*Действует до:* {subscription_end.strftime('%d.%m.%Y %H:%M')}
*Осталось:* {(subscription_end - datetime.now()).days} дней

*Ссылка на канал:* @mindwomen_channel
            """
        else:
            text = """
❌ *У вас нет активной подписки*

Для доступа к закрытому сообществу MindWomen приобретите подписку.

Нажмите /start для выбора тарифа и оплаты.
            """

        await update.message.reply_text(text, parse_mode='Markdown')

    async def notify_admins(self, user, payment, subscription_end, context):
        """Уведомляет владелицу о новой подписке"""
        admin_text = f"""
👑 *Новая подписка MindWomen*

*Пользователь:* {user.first_name} {user.last_name or ''}
*Username:* @{user.username}
*ID:* {user.id}
*Тариф:* {payment.total_amount / 100}₽
*Подписка до:* {subscription_end.strftime('%d.%m.%Y')}
*Время:* {datetime.now().strftime('%Y-%m-%d %H:%M')}
        """

        #  Отправляем сообщение владелице
        try:
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=admin_text,
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Ошибка отправки уведомления: {e}")

    def run(self):
        """Запуск бота"""
        self.application.run_polling()


# Запуск бота
if __name__ == "__main__":
    BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
    bot = SubscriptionBot(BOT_TOKEN)
    bot.run()