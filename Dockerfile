# Slim python version to save space and enter app dir
FROM python:3.11-slim
WORKDIR /tier-fever

# Install requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all files and run app with gunicorn for better performance
COPY . .
CMD ["gunicorn", "--worker-class", "eventlet", "-w", "1", "--bind", "0.0.0.0:5000", "app:socketio"]
