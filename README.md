# SquadUp Real-Time Social Platform Backend

Backend and infrastructure for a real-time group matching platform where users join live sessions and match with other groups.

## Overview

This system supports real-time coordination between multiple user groups, including chat, session management, and subscription-based access.

## Architecture

- Backend: Django + Django REST Framework  
- Real-time layer: Django Channels + Redis (WebSockets)  
- Database: PostgreSQL  
- Authentication: Firebase Auth (JWT)  
- Payments: Stripe (subscriptions, trials, webhooks)  
- Observability: Prometheus + Grafana + Loki  
- Infrastructure: Docker Compose, Nginx, Let's Encrypt  

## Key Features

- Real-time group coordination using WebSockets  
- Chat system with typing indicators  
- Session-based matching logic  
- Subscription and billing system  
- Metrics, logs, and monitoring dashboards  

## System Highlights

- 35+ data models  
- 40+ REST endpoints  
- Redis-based messaging layer for real-time communication  
- Full observability stack for production monitoring  

## Deployment

- Containerized using Docker Compose  
- Reverse proxy with Nginx  
- TLS with Let's Encrypt  
- Multi-environment support for staging and production  

## Notes

This repository focuses on backend systems, real-time communication, and infrastructure design.
