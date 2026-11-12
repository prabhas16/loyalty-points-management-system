import re
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest
from sqlalchemy import func

from app import (
    BalanceSnapshot,
    Customer,
    ExpiryBatch,
    LoyaltyAccount,
    Order,
    PointsTransaction,
    Redemption,
    Reward,
    Tier,
    app,
    balance_for,
    db,
    initialize_sequences,
)
from benchmark.data_builder import generate_dataset


def _csrf_token(response):
    match = re.search(rb'name="csrf_token" value="([^"]+)"', response.data)
    assert match, "Expected the page to render a CSRF token."
    return match.group(1).decode("ascii")


def test_local_app_routes_are_public_and_posts_still_require_csrf():
    client = app.test_client()
    assert client.get("/").status_code == 200
    assert client.get("/customers").status_code == 200
    assert client.get("/rewards").status_code == 200
    assert client.get("/expiry").status_code == 200
    assert client.get("/setup").status_code == 302
    assert client.get("/login").status_code == 404
    assert client.get("/users").status_code == 404
    assert client.post(
        "/customers/new",
        data={"full_name": "No CSRF", "email": "no-csrf@example.test"},
    ).status_code == 400


def test_benchmark_counts_ground_truth_and_repeatability():
    with app.app_context():
        first = generate_dataset(
            customer_count=10,
            order_count=40,
            transaction_count=120,
            seed=917,
            batch_size=7,
        )
        assert first["counts"]["customer"] == 10
        assert first["counts"]["order"] == 40
        assert first["counts"]["pointstransaction"] == 120
        assert [case["case_id"] for case in first["ground_truth"]] == [
            "AN-001", "AN-002", "AN-003", "AN-004", "AN-005",
        ]
        assert db.session.query(Customer).count() == 10
        assert db.session.query(LoyaltyAccount).count() == 10
        assert db.session.query(PointsTransaction).count() == 120

        ledger_balance = balance_for("LOY-000001")
        snapshot = db.session.get(BalanceSnapshot, "LOY-000001")
        assert snapshot.points_balance == ledger_balance + 37

        redemption = db.session.get(Redemption, "RDM-2026-100001")
        accrued = (
            db.session.query(func.sum(PointsTransaction.points))
            .filter_by(account_id="LOY-000002", transaction_type="ACCRUAL")
            .scalar()
        )
        assert redemption.points_spent == accrued + 1000

        returned_order = db.session.get(Order, "ORD-2026-000004")
        assert returned_order.status == "REFUNDED"
        assert (
            PointsTransaction.query.filter_by(
                order_id=returned_order.id,
                transaction_type="REVERSAL",
            ).count()
            == 0
        )
        assert (
            PointsTransaction.query.filter_by(
                expiry_batch_id="EXP-2026-080001",
                transaction_type="EXPIRY",
            ).count()
            == 1
        )
        assert (
            PointsTransaction.query.filter_by(
                expiry_batch_id="EXP-2026-080000",
                transaction_type="EXPIRY",
            ).count()
            == 1
        )
        assert ExpiryBatch.query.count() == 2
        account = db.session.get(LoyaltyAccount, "LOY-000001")
        assert account.tier.name == "Gold"
        assert account.qualifying_spend < Decimal(account.tier.min_qualifying_spend)

        db.session.remove()
        db.drop_all()
        db.create_all()
        second = generate_dataset(
            customer_count=10,
            order_count=40,
            transaction_count=120,
            seed=917,
            batch_size=7,
        )
        assert first["checksums"] == second["checksums"]
        assert first["dataset_checksum"] == second["dataset_checksum"]


def test_benchmark_append_offsets_ids_and_preserves_existing_rows():
    with app.app_context():
        generate_dataset(
            customer_count=4,
            order_count=16,
            transaction_count=48,
            seed=917,
            batch_size=7,
        )
        tier = Tier.query.filter_by(name="Bronze").one()
        for customer_id, account_id in (
            ("CUS-000005", "LOY-000201"),
            ("CUS-000006", "LOY-C000200"),
        ):
            customer = Customer(
                id=customer_id,
                full_name=f"Existing {customer_id}",
                email=f"{customer_id}@example.test",
            )
            db.session.add(customer)
            db.session.flush()
            db.session.add(
                LoyaltyAccount(
                    id=account_id,
                    customer_id=customer.id,
                    tier_id=tier.id,
                )
            )
        db.session.commit()
        appended = generate_dataset(
            customer_count=4,
            order_count=16,
            transaction_count=48,
            seed=918,
            batch_size=7,
            append=True,
        )

        assert Customer.query.count() == 10
        assert LoyaltyAccount.query.count() == 10
        assert Order.query.count() == 32
        assert PointsTransaction.query.count() == 96
        assert db.session.get(Customer, "CUS-000001") is not None
        assert db.session.get(Customer, "CUS-000007") is not None
        assert db.session.get(Order, "ORD-2026-000001") is not None
        assert db.session.get(Order, "ORD-2026-000017") is not None
        assert db.session.get(LoyaltyAccount, "LOY-000201") is not None
        assert db.session.get(LoyaltyAccount, "LOY-C000200") is not None
        assert db.session.get(LoyaltyAccount, "LOY-000202") is not None
        assert db.session.get(PointsTransaction, "PTS-2026-00000001") is not None
        assert db.session.get(PointsTransaction, "PTS-2026-00000049") is not None

        cases = {case["case_id"]: case for case in appended["ground_truth"]}
        assert cases["AN-001"]["entity_id"] == "LOY-000202"
        assert cases["AN-002"]["entity_id"] == "RDM-2026-100002"
        assert cases["AN-002"]["account_id"] == "LOY-000203"
        assert cases["AN-003"]["entity_id"] == "ORD-2026-000020"
        assert cases["AN-004"]["entity_id"] == "EXP-2026-080003"
        assert cases["AN-004"]["original_batch_id"] == "EXP-2026-080002"


def test_list_pages_and_large_lookups_are_bounded():
    with app.app_context():
        generate_dataset(
            customer_count=60,
            order_count=240,
            transaction_count=720,
            seed=919,
            batch_size=25,
        )

    client = app.test_client()
    customer_page = client.get("/customers?page=2")
    assert customer_page.status_code == 200
    assert b"Showing 51-60 of 60 customers" in customer_page.data

    order_page = client.get("/orders?page=2")
    assert order_page.status_code == 200
    assert b"Showing 51-100 of 240 orders" in order_page.data
    for path in (
        "/returns?page=2",
        "/rewards?page=1",
        "/redeem?page=1",
        "/expiry?page=1",
        "/ledger?page=2",
    ):
        assert client.get(path).status_code == 200

    customer_results = client.get("/lookup/customers?q=Benchmark").get_json()["results"]
    account_results = client.get("/lookup/accounts?q=Benchmark").get_json()["results"]
    reward_results = client.get("/lookup/rewards?q=Benchmark").get_json()["results"]
    assert len(customer_results) == 20
    assert len(account_results) == 20
    assert len(reward_results) == 1


@pytest.mark.slow
def test_full_benchmark_acceptance_counts():
    with app.app_context():
        manifest = generate_dataset()
        assert manifest["counts"]["customer"] == 20_000
        assert manifest["counts"]["order"] == 100_000
        assert manifest["counts"]["pointstransaction"] == 300_000
        assert db.session.query(Customer).count() == 20_000
        assert db.session.query(Order).count() == 100_000
        assert PointsTransaction.query.count() == 300_000


def test_concurrent_redemptions_do_not_overdraw_account():
    with app.app_context():
        tier = Tier(name="Bronze", min_qualifying_spend=0, earning_rate=1)
        db.session.add(tier)
        db.session.flush()
        customer = Customer(
            id="CUS-000001",
            full_name="Concurrent Customer",
            email="concurrent@example.test",
        )
        db.session.add(customer)
        db.session.flush()
        account = LoyaltyAccount(
            id="LOY-000001",
            customer_id=customer.id,
            tier_id=tier.id,
        )
        reward = Reward(id="RWD-0001", name="Test reward", points_cost=80)
        accrual = PointsTransaction(
            id="PTS-2026-00000001",
            account_id=account.id,
            transaction_type="ACCRUAL",
            points=100,
            issue_type="NONE",
        )
        db.session.add_all([account, reward, accrual])
        db.session.commit()
        initialize_sequences()

    def redeem_once():
        client = app.test_client()
        redeem_page = client.get("/redeem")
        return client.post(
            "/redeem",
            data={
                "csrf_token": _csrf_token(redeem_page),
                "account_code": "LOY-000001",
                "reward_id": "RWD-0001",
            },
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: redeem_once(), range(2)))
    assert all(status in {200, 302} for status in results)
    with app.app_context():
        assert balance_for("LOY-000001") >= 0
        assert Redemption.query.count() <= 1
        assert (
            PointsTransaction.query.filter_by(
                account_id="LOY-000001",
                transaction_type="REDEMPTION",
            ).count()
            <= 1
        )
