TALLY_INSTANCE_NAME ?= tally-dev
TALLY_ENV_FILE ?=
export TALLY_INSTANCE_NAME TALLY_DEV_PORT

COMPOSE = docker compose $(if $(TALLY_ENV_FILE),--env-file "$(TALLY_ENV_FILE)") -p "$(TALLY_INSTANCE_NAME)" -f compose.yaml -f compose.dev.yaml

.DEFAULT_GOAL := help
.PHONY: help up demo seed login superuser down logs

help:
	@printf '%s\n' \
	  'make up         Build and start a local instance; show URL and login' \
	  'make demo       Start an instance and populate an empty portfolio with fictional data' \
	  'make seed       Populate a running, empty portfolio with fictional data' \
	  'make login      Show the saved development login and URL' \
	  'make superuser  Interactively create an additional administrator' \
	  'make down       Stop this instance, preserving its data' \
	  'make logs       Follow this instance logs' \
	  '' \
	  'Options: TALLY_INSTANCE_NAME=tally-dev TALLY_DEV_PORT=8000 TALLY_ENV_FILE=.env.local'

up:
	$(COMPOSE) build
	$(COMPOSE) run --rm app python manage.py migrate --noinput
	$(COMPOSE) up -d
	@$(MAKE) --no-print-directory login

demo: up
	@$(MAKE) --no-print-directory seed

seed:
	$(COMPOSE) exec -T app python manage.py seed_demo

login:
	@port="$$( $(COMPOSE) port app 8000 )"; \
	  test -n "$$port" || exit 1; \
	  printf '\nURL: http://localhost:%s\n' "$${port##*:}"
	@$(COMPOSE) exec -T app python manage.py dev_login

superuser:
	$(COMPOSE) exec app python manage.py createsuperuser

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f app
