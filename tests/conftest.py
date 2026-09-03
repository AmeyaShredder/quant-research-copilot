"""
Repository-layer tests run against a real Postgres test DB (set
TEST_DATABASE_URL, defaults to a local `quant_research_copilot_test` db)
inside a SAVEPOINT-based transaction that's rolled back after every test
— fast, isolated, no fixture teardown SQL needed.

Requires the schema to already be migrated into the test DB:
    TEST_DATABASE_URL=postgresql+psycopg://qrc:qrc@localhost:5432/quant_research_copilot_test \
        alembic upgrade head
"""
from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://qrc:qrc@localhost:5432/quant_research_copilot_test",
)


@pytest.fixture(scope="session")
def test_engine():
    return create_engine(TEST_DATABASE_URL, future=True)


@pytest.fixture()
def session(test_engine):
    connection = test_engine.connect()
    outer_txn = connection.begin()
    Session = sessionmaker(bind=connection, future=True)
    sess = Session()

    # Nested SAVEPOINT so session.commit() inside application code
    # doesn't actually end the outer rollback-able transaction.
    nested = connection.begin_nested()

    @event.listens_for(sess, "after_transaction_end")
    def restart_savepoint(sess_, trans):
        nonlocal nested
        if not nested.is_active:
            nested = connection.begin_nested()

    yield sess

    sess.close()
    outer_txn.rollback()
    connection.close()
