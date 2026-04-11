.PHONY: build up down restart migrate shell logs fresh-start

build:
    cd ../infra && docker-compose build ubuntu_backend

up:
    cd ../infra && docker-compose up -d

down:
    cd ../infra && docker-compose down

restart:
    docker-compose restart backend

migrate:
    docker exec -it ubuntu_backend python3 manage.py migrate

makemigrations:
    docker exec -it ubuntu_backend python3 manage.py makemigrations

shell:
    docker exec -it ubuntu_backend python3 manage.py shell

createsuperuser:
    docker exec -it ubuntu_backend python3 manage.py createsuperuser

logs:
    cd ../infra && docker-compose logs -f ubuntu_backend

fresh-start:
    docker-compose down -v
    docker-compose build
    docker-compose up -d