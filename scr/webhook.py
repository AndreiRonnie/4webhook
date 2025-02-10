import os
import json
import logging
import time
import threading
from flask import Flask, request, jsonify
import requests

# Попробуем импортировать openai в блоке try/except, чтобы отловить возможные проблемы
try:
    import openai
except ImportError as e:
    print(f"Не удалось импортировать openai: {e}")
    openai = None  # Можем установить в None, чтобы не ломать дальнейший код

# ------------------------------------------------------
# 1) Настройка прокси (если вам действительно нужно 
#    отправлять запросы к OpenAI через прокси)
# ------------------------------------------------------
proxy_host = "213.225.237.177"
proxy_port = "9239"
proxy_user = "user27099"
proxy_pass = "qf08ja"

proxy_url = f"http://{proxy_user}:{proxy_pass}@{proxy_host}:{proxy_port}"

# Если прокси действительно необходим, раскомментируйте:
os.environ['http_proxy'] = proxy_url
os.environ['https_proxy'] = proxy_url

# ------------------------------------------------------
# 2) Настройка OpenAI API
# ------------------------------------------------------
OPENAI_API_KEY = "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"  # <-- Вставьте сюда реальный ключ OpenAI

if openai:
    openai.api_key = OPENAI_API_KEY
else:
    print("Внимание! Модуль openai не импортирован. ChatGPT-запросы работать не будут.")

# ------------------------------------------------------
# 3) Логирование в файл с уровнем DEBUG
# ------------------------------------------------------
BASE_DIR = os.getcwd()  # вместо os.path.dirname(os.path.abspath(__file__))
LOGFILE_PATH = os.path.join(BASE_DIR, 'bot2.log')

logging.basicConfig(
    filename=LOGFILE_PATH,
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s'
)

# ------------------------------------------------------
# Создаем Flask-приложение
# ------------------------------------------------------
app = Flask(__name__)

# Устанавливаем уровень логирования для Flask
app.logger.setLevel(logging.DEBUG)

# ------------------------------------------------------
# Папка для хранения файлов-диалогов
# ------------------------------------------------------
CONVERSATIONS_DIR = os.path.join(BASE_DIR, 'conversations')
if not os.path.exists(CONVERSATIONS_DIR):
    try:
        os.makedirs(CONVERSATIONS_DIR)
        logging.info(f"Создана папка {CONVERSATIONS_DIR}")
    except Exception as e:
        logging.error(f"Ошибка при создании папки {CONVERSATIONS_DIR}: {e}")

# ------------------------------------------------------
# Фоновая задача: каждые 10 секунд записывать в лог, 
# чтобы было видно, что бот "жив"
# ------------------------------------------------------
def periodic_logger():
    while True:
        logging.info("Periodic log message: the bot3 is running")
        time.sleep(10)

thread = threading.Thread(target=periodic_logger, daemon=True)
thread.start()

# ------------------------------------------------------
# Функции для хранения/загрузки диалога
# ------------------------------------------------------
def get_conversation_file_path(conversation_id: str) -> str:
    """
    Возвращает путь к файлу, в котором хранится история 
    для заданного conversation_id.
    """
    safe_id = conversation_id.replace('/', '_').replace('\\', '_')
    return os.path.join(CONVERSATIONS_DIR, f"conversation_{safe_id}.json")

def get_default_system_history() -> list:
    """
    Возвращает стартовую историю, содержащую одно системное сообщение,
    описывающее роль бота (ассистент, помогающий студентам).
    """
    system_message = {
        "role": "system",
        "content": (
            "Ты — ассистент, который помогает студентам (платно) и старается узнать "
            "все детали об их заказе: тип работы (курсовая, диплом, реферат и т.д.), "
            "срок выполнения, методические материалы, предмет (или специальность), "
            "тему работы, проверку на антиплагиат и требуемый процент оригинальности. "
            "Будь вежливым, дружелюбным, отвечай кратко и по делу, при этом старайся "
            "задавать уточняющие вопросы, чтобы собрать полную информацию о заказе."
        )
    }
    return [system_message]

def load_history(conversation_id: str) -> list:
    """
    Загружает историю диалога (список dict с ключами role/content).
    Если файл отсутствует — возвращаем дефолтную историю (только system).
    """
    filepath = get_conversation_file_path(conversation_id)
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                history_data = json.load(f)
                logging.debug(f"Загружена история из файла {filepath}: {history_data}")
                return history_data
        except Exception as e:
            logging.error(f"Ошибка при чтении истории {filepath}: {e}")
            return get_default_system_history()
    else:
        logging.debug(f"Файл истории не найден, возвращаем default system history: {filepath}")
        return get_default_system_history()

def save_history(conversation_id: str, history: list):
    """
    Сохраняет историю диалога в JSON-файл.
    """
    filepath = get_conversation_file_path(conversation_id)
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
        logging.debug(f"История сохранена в файл {filepath}")
    except Exception as e:
        logging.error(f"Ошибка при сохранении истории {filepath}: {e}")

# ------------------------------------------------------
# Функция для вызова ChatGPT, учитывая историю
# ------------------------------------------------------
def get_chatgpt_response(user_text: str, conversation_id: str) -> str:
    """
    1) Загружаем текущую историю диалога
    2) Добавляем новое сообщение пользователя
    3) Отправляем всю историю в ChatCompletion
    4) Сохраняем ответ ChatGPT в историю
    5) Возвращаем ответ
    """
    # Если openai не импортирован или ключ не установлен, вернем «заглушку».
    if not openai or not OPENAI_API_KEY:
        logging.warning("OpenAI не доступен, возвращаем заглушку.")
        return "Извините, на данный момент ChatGPT недоступен."

    try:
        # 1) загрузка истории
        conversation_history = load_history(conversation_id)

        # 2) добавляем сообщение пользователя
        conversation_history.append({"role": "user", "content": user_text})
        logging.debug(f"Добавлено пользовательское сообщение: {user_text}")

        # 3) запрос к ChatGPT
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=conversation_history,
            temperature=0.7,
        )
        assistant_answer = response["choices"][0]["message"]["content"]
        logging.debug(f"Ответ ChatGPT: {assistant_answer}")

        # 4) добавляем ответ ассистента в историю
        conversation_history.append({"role": "assistant", "content": assistant_answer})

        # 5) сохраняем историю
        save_history(conversation_id, conversation_history)

        return assistant_answer

    except Exception as e:
        logging.error(f"Ошибка при запросе к ChatGPT: {e}")
        return "Извините, произошла ошибка при запросе к ИИ."

# ------------------------------------------------------
# Маршрут для приёма вебхуков от Talk-Me (POST)
# ------------------------------------------------------
@app.route('/talkme_webhook', methods=['POST'])
def talkme_webhook():
    try:
        data = request.get_json(force=True)
    except Exception as e:
        logging.error(f"Невозможно считать JSON из входящего запроса: {e}")
        return jsonify({"error": "Bad JSON"}), 400

    # Из JSON берем searchId (если он не пуст), иначе fallback — token или 'unknown'
    search_id = data.get("client", {}).get("searchId")
    if not search_id:
        search_id = data.get("token", "unknown")

    # Текст сообщения пользователя
    incoming_text = data.get("message", {}).get("text", "")

    # Talk-Me передаёт свой токен для авторизации обратного запроса
    talkme_token = data.get("token", "")

    logging.info(f"Получен webhook от Talk-Me: searchId={search_id}, text={incoming_text}")

    # Получаем ответ от ChatGPT с учётом истории
    reply_text = get_chatgpt_response(incoming_text, search_id)

    # Формируем запрос обратно в Talk-Me
    url = "https://lcab.talk-me.ru/json/v1.0/customBot/send"
    body = {
        "content": {
            "text": reply_text
        }
    }
    headers = {
        "X-Token": talkme_token,
        "Content-Type": "application/json"
    }

    # Отправляем ответ в Talk-Me
    try:
        response = requests.post(url, json=body, headers=headers)
        logging.info(f"Отправили ответ в Talk-Me: {response.status_code} {response.text}")
    except Exception as e:
        logging.error(f"Ошибка при отправке ответа в Talk-Me: {e}")

    # Возвращаем OK, чтобы Talk-Me знал, что вебхук обработан
    return jsonify({"status": "ok"}), 200

# ------------------------------------------------------
# Маршрут проверки: GET / 
# ------------------------------------------------------
@app.route('/', methods=['GET'])
def index():
    logging.debug("Вызван корневой маршрут /")
    return "Bot with ChatGPT (с памятью) is running", 200

# ------------------------------------------------------
# Локальный запуск (при разработке)
# ------------------------------------------------------
if __name__ == '__main__':
    logging.info("Запуск Flask-приложения...")
    try:
        app.run(host='0.0.0.0', port=5000, debug=True)
    except Exception as e:
        logging.error(f"Ошибка при запуске приложения: {e}")
