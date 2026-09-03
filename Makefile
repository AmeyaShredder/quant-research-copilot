.PHONY: up down migrate views test dashboard
up:
	docker compose up -d
down:
	docker compose down
migrate:
	alembic upgrade head
views:
	psql "$$DATABASE_URL" -f db/views.sql
test:
	pytest -v
dashboard:
	streamlit run dashboard/app.py
