FROM python:3.9-slim

WORKDIR /app

# Установка зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копирование файлов
COPY BackEnd/ ./BackEnd/

# Создание директорий
RUN mkdir -p ./BackEnd/uploads ./BackEnd/uploads/images ./BackEnd/uploads/stickers ./BackEnd/uploads/files

# Открытие порта
EXPOSE 8000

# Запуск приложения
CMD ["uvicorn", "BackEnd.main:app", "--host", "0.0.0.0", "--port", "8000"]
