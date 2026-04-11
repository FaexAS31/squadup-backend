set -e

echo " Actualizando Backend "
apt-get update && apt-get upgrade -y

echo " Instalando Python y dependencias de compilacion "
apt-get install -y --no-install-recommends \
    git nano curl ca-certificates \
    python3 python3-pip pip \
    build-essential libpq-dev postgresql-client \
    netcat-openbsd

echo " Limpieza "
apt-get clean
rm -rf /var/lib/apt/lists/*