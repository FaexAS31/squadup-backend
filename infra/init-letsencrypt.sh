#!/bin/bash
# =============================================================================
# Script de inicialización de Let's Encrypt
# Ejecutar UNA SOLA VEZ en el VPS después de configurar los DNS
#
# Uso:
#   chmod +x init-letsencrypt.sh
#   ./init-letsencrypt.sh
# =============================================================================

set -e

DOMAIN="jesuslab135.com"
EMAIL="lidering.esteban@gmail.com"  # <-- CAMBIA por tu email real
DEPLOY_PATH="/root/app/infra"

cd "$DEPLOY_PATH"

echo ""
echo "============================================"
echo "  Inicializando SSL para $DOMAIN"
echo "============================================"
echo ""

# 1. Guardar el default.conf original (con SSL) para restaurarlo después
echo "=== 1. Guardando configuración SSL para después ==="
cp nginx/default.conf nginx/default.conf.ssl

# 2. Usar init.conf temporalmente (solo HTTP, sin SSL)
echo "=== 2. Usando configuración temporal (solo HTTP) ==="
cp nginx/init.conf nginx/default.conf

# 3. Levantar nginx (y dependencias) en modo HTTP
echo "=== 3. Levantando Nginx en modo HTTP ==="
docker compose up -d nginx

# Esperar a que nginx esté listo
sleep 3

# 4. Verificar que nginx responde
echo "=== 4. Verificando que Nginx responde ==="
curl -s -o /dev/null -w "HTTP Status: %{http_code}\n" http://$DOMAIN || echo "ADVERTENCIA: No se pudo conectar a http://$DOMAIN — verifica que los DNS hayan propagado"

# 5. Obtener certificado SSL
echo "=== 5. Obteniendo certificado SSL de Let's Encrypt ==="
docker compose --profile ssl run --rm --entrypoint "certbot" certbot certonly \
    --webroot \
    --webroot-path=/var/www/certbot \
    --email "$EMAIL" \
    --agree-tos \
    --no-eff-email \
    -d "$DOMAIN" \
    -d "www.$DOMAIN"

# 6. Restaurar configuración con SSL
echo "=== 6. Restaurando configuración Nginx con SSL ==="
cp nginx/default.conf.ssl nginx/default.conf

# 7. Recargar nginx
echo "=== 7. Recargando Nginx ==="
docker compose exec -T nginx nginx -s reload

# 8. Verificar
echo "=== 8. Verificando configuración ==="
docker compose exec -T nginx nginx -t

echo ""
echo "============================================"
echo "  LISTO! Certificado SSL instalado"
echo "  Visita https://$DOMAIN"
echo "============================================"
echo ""
echo "El certificado se renueva automáticamente"
echo "cada 12 horas via el contenedor certbot."
