from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

@app.route('/talkme_webhook', methods=['POST'])
def talkme_webhook():
    # 1) Получаем JSON
    data = request.get_json(force=True)

    # 2) Извлекаем нужные поля:
    token = data.get("token", "")  # Токен, который нам нужно будет использовать в заголовке X-Token
    incoming_text = data.get("message", {}).get("text", "")  # Текст сообщения от клиента
    
    # 3) Формируем ответ для клиента. (Тут можно вызвать ваш ИИ.)
    #    Например, сделаем простую заглушку:
    reply_text = f"Вы написали: {incoming_text}\nСпасибо за обращение!"

    # 4) Отправляем ответ обратно в Talk-Me по их API:
    url = "https://lcab.talk-me.ru/json/v1.0/customBot/send"
    
    # Тело запроса:
    body = {
        "content": {
            "type": "comment",
            "comment": reply_text
        }
    }
    
    # Заголовки:
    headers = {
        "X-Token": token,        # Передаём тот же токен, который прислали в webhook
        "Content-Type": "application/json"
    }
    
    response = requests.post(url, json=body, headers=headers)
    
    # Можно посмотреть, что вернул Talk-Me:
    print("Talk-Me response:", response.status_code, response.text)

    # 5) Возвращаем Talk-Me обычный ответ, чтобы webhook считался обработанным
    return "OK", 200

# Остальные роуты, если нужны
@app.route('/', methods=['GET'])
def index():
    return "Server is running", 200


if __name__ == '__main__':
    app.run(port=5000, debug=True)

