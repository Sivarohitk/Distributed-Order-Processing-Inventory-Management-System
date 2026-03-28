.PHONY: up down rebuild logs ps test clean

COMPOSE ?= docker compose
PYTHON ?= python

up:
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

rebuild:
	$(COMPOSE) up --build -d

logs:
	$(COMPOSE) logs -f

ps:
	$(COMPOSE) ps

test:
	$(PYTHON) -m pytest tests -v

clean:
	$(COMPOSE) down -v --remove-orphans
