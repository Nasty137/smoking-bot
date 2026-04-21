from flask import Flask
import subprocess
import os

flask_app = Flask(__name__)

@flask_app.route('/')
def home():
    return "Бот работает!"

@flask_app.route('/health')
def health():
    return "OK", 200

if __name__ == "__main__":
    # Запускаем бота в фоновом процессе
    subprocess.Popen(["python3", "bot.py"])
    
    # Запускаем Flask для Render
    port = int(os.environ.get("PORT", 5000))
    flask_app.run(host="0.0.0.0", port=port)
