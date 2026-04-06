# Slim python version to save space and enter app dir
FROM python:3.9-slim
WORKDIR /tier_fever

# Install requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all files and run app
COPY . .
CMD ["python", "app.py"]
