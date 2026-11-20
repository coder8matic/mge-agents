FROM python:3.12-slim
RUN useradd -m app
USER app
WORKDIR /home/app
COPY --chown=app requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt
COPY --chown=app server.py .
EXPOSE 8000
CMD ["python", "server.py"]
