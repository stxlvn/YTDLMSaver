import asyncio
from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeDefault
import config

async def main():
    # Подключаемся к боту, используя токен из твоего конфига
    bot = Bot(token=config.BOT_TOKEN)

    # 🇷🇺 Русское меню
    commands_ru = [
        BotCommand(command="start", description="Запустить бота"),
        BotCommand(command="help", description="Помощь и инструкции"),
        BotCommand(command="lang", description="Выбрать язык / Choose language"),
        BotCommand(command="status", description="Статус текущих загрузок"),
        BotCommand(command="cancel", description="Отменить загрузку"),
        BotCommand(command="stats", description="Ваша статистика")
    ]

    # 🇬🇧 Английское меню
    commands_en = [
        BotCommand(command="start", description="Start the bot"),
        BotCommand(command="help", description="Help and instructions"),
        BotCommand(command="lang", description="Choose language / Выбрать язык"),
        BotCommand(command="status", description="Current downloads status"),
        BotCommand(command="cancel", description="Cancel active download"),
        BotCommand(command="stats", description="Your statistics")
    ]

    try:
        # Отправляем английские команды для пользователей с английским Telegram
        await bot.set_my_commands(commands_en, scope=BotCommandScopeDefault(), language_code="en")
        
        # Отправляем русские команды для пользователей с русским Telegram
        await bot.set_my_commands(commands_ru, scope=BotCommandScopeDefault(), language_code="ru")
        
        # Устанавливаем русские команды по умолчанию (для всех остальных языков)
        await bot.set_my_commands(commands_ru, scope=BotCommandScopeDefault())
        
        print("✅ Меню команд успешно обновлено для обоих языков!")
    except Exception as e:
        print(f"❌ Ошибка при обновлении команд: {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
