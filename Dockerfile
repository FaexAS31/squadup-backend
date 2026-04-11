FROM ubuntu:latest
ENV DEBIAN_FRONTEND=noninteractive
ENV PIP_BREAK_SYSTEM_PACKAGES=1

# Instalar sistema base
COPY scripts/install.sh /tmp/install.sh
COPY scripts/entrypoint.sh /entrypoint.sh

RUN chmod +x /tmp/install.sh /entrypoint.sh && bash /tmp/install.sh

WORKDIR /app

# Copiar e instalar dependencias Python
COPY src/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Copiar código fuente
COPY src/ /app/

ENTRYPOINT ["/entrypoint.sh"]

# Working directory for Django project
WORKDIR /app/core

# Use Daphne for ASGI (WebSocket support)
# Se ejecuta desde /app/core donde está manage.py
# Para desarrollo sin WebSockets: python3 manage.py runserver 0.0.0.0:8000
CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", "core.asgi:application"]