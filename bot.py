админу: {e}")

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
