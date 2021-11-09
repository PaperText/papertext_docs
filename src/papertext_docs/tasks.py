import os

from celery import Celery

default_info = {
    "name": "papertext_docs",
    "protocol": "amqp",
    "user": "guest",
    "password": "12345",
    "host": "localhost",
    "port": "5672",
    "vhost": "",
}
info = {}

for key, default in default_info.items():
    info[key] = os.environ.get(f"PT__docs__task_queue__{key}", default)

app = Celery(
    info["name"],
    broker=f"{info['protocol']}://{info['user']}:{info['password']}@{info['host']}:{info['port']}/{info['vhost']}",
    # backend="redis://user:password@hostname:6379/0",
)


@app.task
def hello() -> int:
    print("Hello, world!")
    return 200


@app.task
def add_document(
    text: str,
) -> str:
    print("started task 'add_document'")
    # xml = something(text)
    return 200
