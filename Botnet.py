import subprocess
import os
import asyncio
import logging
import smtplib
import concurrent.futures
from telethon import TelegramClient, types
from telethon.sessions import SQLiteSession
from telethon.tl.functions.users import GetFullUserRequest
from telethon.tl.types import User
from telethon.errors import AuthKeyDuplicatedError
from pystyle import Colors, Colorate
from colorama import init

init(autoreset=True)
from config import SESSION_DIR, senders, smtp_servers, clients

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def print_email_info(email, info, delete_reason=None):
    info_lines = info.split('\n')
    if delete_reason:
        info_lines.append(delete_reason)
    max_length = max(len(line) for line in info_lines)
    max_length = max(max_length, len(email) + 10)
    border = "╔" + "═" * (max_length + 2) + "╗"
    bottom_border = "╚" + "═" * (max_length + 2) + "╝"
    email_line = f"║ Почта: {email.ljust(max_length - 8)}  ║"
    info_lines_formatted = [f"║ {line.ljust(max_length)} ║" for line in info_lines]
    info_text = f"{border}\n{email_line}\n" + "\n".join(info_lines_formatted) + f"\n{bottom_border}"
    print(Colorate.Horizontal(Colors.red_to_green, info_text))

def print_session_info(session_name, info, delete_reason=None):
    info_lines = info.split('\n')
    if delete_reason:
        info_lines.append(delete_reason)
    max_length = max(len(line) for line in info_lines)
    max_length = max(max_length, len(session_name) + 10)
    border = "╔" + "═" * (max_length + 2) + "╗"
    bottom_border = "╚" + "═" * (max_length + 2) + "╝"
    session_line = f"║ Сессия: {session_name.ljust(max_length - 8)} ║"
    info_lines_formatted = [f"║ {line.ljust(max_length)} ║" for line in info_lines]
    info_text = f"{border}\n{session_line}\n" + "\n".join(info_lines_formatted) + f"\n{bottom_border}"
    print(Colorate.Horizontal(Colors.red_to_green, info_text))

def check_email_sync(sender_email, sender_password):
    logging.info(f"Проверяю email: {sender_email}")
    domain = sender_email.split('@')[1]
    if domain not in smtp_servers:
        logging.info(f"{sender_email}: Неизвестный домен")
        print_email_info(sender_email, f"   ➥ Неизвестный домен")
        return False

    smtp_server, smtp_port = smtp_servers[domain]

    try:
        with smtplib.SMTP(smtp_server, smtp_port, timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(sender_email, sender_password)
            logging.info(f"{sender_email}: работает")
            print_email_info(sender_email, f"   ➥ работает")
            return True
    except smtplib.SMTPAuthenticationError as e:
        logging.error(f"{sender_email}: Ошибка аутентификации", exc_info=True)
        print_email_info(sender_email, f"   ➥ Ошибка аутентификации")
        return False
    except (smtplib.SMTPException, TimeoutError, OSError) as e:
        logging.error(f"{sender_email}: не работает", exc_info=True)
        print_email_info(sender_email, f"   ➥ не работает")
        return False

async def check_emails(email_list):
    working_emails = []
    with concurrent.futures.ThreadPoolExecutor() as executor:
        loop = asyncio.get_event_loop()
        futures = [
            loop.run_in_executor(executor, check_email_sync, email, password)
            for email, password in email_list.items()
        ]
        results = await asyncio.gather(*futures)

    for i, result in enumerate(results):
        email = list(email_list.keys())[i]
        password = email_list[email]
        if result:
            working_emails.append((email, password))
    return working_emails

async def check_session(session_file, api_id, api_hash):
    session_name = os.path.basename(session_file).replace('.session', '')
    client = None
    delete_session = False # Инициализируем delete_session
    try:
        client = TelegramClient(SQLiteSession(session_file), api_id, api_hash, timeout=10)
        await client.connect()

        if not await client.is_user_authorized():
            raise ValueError("Сессия не авторизована.")

        me = await client.get_me()
        if isinstance(me, types.User):
            account_type = "Пользователь"
        elif isinstance(me, types.Bot):
            account_type = "Бот"
        else:
            account_type = "Неизвестно"

        auth_info = f"Авторизован как: {me.first_name} (id: {me.id})"
        premium_status = "Premium: Да" if getattr(me, 'premium', False) else "Premium: Нет"
        username = f"username: @{me.username}" if me.username else "Нет username"
        session_info = (
            f"{auth_info}\n"
            f"{username}\n"
            f"{premium_status}\n"
            f"Тип аккаунта: {account_type}"
        )

        if isinstance(me, types.Bot):
            print_session_info(session_name, session_info, "Сессия удалена (это бот).")
            delete_session = True
        else:
            print_session_info(session_name, session_info)

    except AuthKeyDuplicatedError:
        print_session_info(session_name, "Ошибка: Сессия используется под разными IP.", "Сессия удалена.")
        delete_session = True
    except asyncio.TimeoutError:
        print_session_info(session_name, "Ошибка: Тайм-аут подключения.", "Сессия удалена.")
        delete_session = True
    except Exception as e:
        logging.exception(f"Ошибка при проверке сессии {session_name}: {e}")
        print_session_info(session_name, "Ошибка при проверке сессии", "Сессия удалена.")
        delete_session = True
    finally:
        try:
            if client:
                await client.disconnect()
        except Exception as e:
            logging.exception(f"Ошибка при отключении клиента {session_name}: {e}")

        if delete_session and os.path.exists(session_file):
            try:
                os.remove(session_file)
                logging.info(f"Удален файл сессии: {session_file}")
            except Exception as e:
                logging.exception(f"Ошибка при удалении файла сессии {session_file}: {e}")

def find_session_files():
    if not os.path.exists(SESSION_DIR):
        print(Colorate.Horizontal(Colors.red_to_green, "Папка Session не найдена."))
        return []

    session_files = []
    try:
        for client_folder in os.listdir(SESSION_DIR):
            client_path = os.path.join(SESSION_DIR, client_folder)
            if os.path.isdir(client_path):
                try:
                    for file in os.listdir(client_path):
                        if file.endswith('.session'):
                            session_files.append((os.path.join(client_path, file), client_folder))
                except OSError as e:
                    print(f"Ошибка при чтении папки {client_path}: {e}")  # Обработка ошибок чтения
        return session_files  # Перемещаем return за пределы внутреннего цикла
    except OSError as e:
        print(f"Ошибка при чтении папки {SESSION_DIR}: {e}")
        return []

menu_text = f"""
"""
async def run_checker():
    session_files = find_session_files()
    session_count = len(session_files)
    text = f"Количество сессий: {session_count}"
    text_width = len(text) + 4
    border = "╔" + "═" * text_width + "╗\n"
    border += "║ " + text.center(text_width - 4) + "   ║\n"
    border += "╚" + "═" * text_width + "╝"
    print(Colorate.Horizontal(Colors.red_to_green, menu_text))
    print(Colorate.Horizontal(Colors.red_to_green, border))

    if session_files:
        for session_file, client_folder in session_files:
            client_info = next((client for client in clients if client["name"] == client_folder), None)
            if client_info:
                await check_session(session_file, client_info["api_id"], client_info["api_hash"])
            else:
                print(Colorate.Horizontal(Colors.red_to_green, f"Не найдена конфигурация для папки {client_folder}."))

    working_emails = await check_emails(senders)
    if working_emails:
        email_count = len(working_emails)
        text = f"Количество работающих почт: {email_count}"
        text_width = len(text) + 4
        border = "╔" + "═" * text_width + "╗\n"
        border += "║ " + text.center(text_width - 4) + "   ║\n"
        border += "╚" + "═" * text_width + "╝"
        print(Colorate.Horizontal(Colors.red_to_green, border))
    else:
        print(Colorate.Horizontal(Colors.red_to_green, "Нет работающих почт."))

    try:
        print(Colorate.Horizontal(Colors.red_to_green, f"╔" + "═" * 21 + " Запуск бота " + "═" * 21 + "╗"))
        subprocess.run(["python", "бот.py"], check=True)
    except FileNotFoundError:
        print(Colorate.Horizontal(Colors.red_to_green, "Файл бот.py не найден."))
    except subprocess.CalledProcessError as e:
        print(Colorate.Horizontal(Colors.red_to_green, f"Ошибка при запуске: {e}"))

if __name__ == "__main__":
    asyncio.run(run_checker())
