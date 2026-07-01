FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .

# Remove macOS-specific pyobjc from requirements to prevent Linux build errors
RUN grep -v "pyobjc" requirements.txt > requirements-docker.txt

RUN pip install --no-cache-dir -r requirements-docker.txt

COPY . .

EXPOSE 3001

CMD ["python", "run.py"]
