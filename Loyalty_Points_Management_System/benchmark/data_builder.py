import hashlib
import json
import random
import re
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path

from app import (
    BalanceSnapshot,
    CodeSequence,
    Customer,
    ExpiryBatch,
    LoyaltyAccount,
    Order,
    OrderLine,
    PointsTransaction,
    Redemption,
    Reward,
    Rule,
    SEQUENCE_MODELS,
    Tier,
    db,
    initialize_sequences,
)


ROOT = Path(__file__).resolve().parent
BASE_DATE = date(2024, 1, 1)
TABLES = {
    "customer": Customer.__table__,
    "loyaltyaccount": LoyaltyAccount.__table__,
    "order": Order.__table__,
    "orderline": OrderLine.__table__,
    "pointstransaction": PointsTransaction.__table__,
    "redemption": Redemption.__table__,
    "expiry_batch_run": ExpiryBatch.__table__,
    "balance_snapshot": BalanceSnapshot.__table__,
}


def _insert_chunk(table, rows):
    if rows:
        db.session.execute(table.insert(), rows)


def _canonical_row(table_name, row):
    return (
        json.dumps(
            {"table": table_name, "row": row},
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        + b"\n"
    )


def _ensure_catalog():
    if Tier.query.count() == 0:
        db.session.add_all(
            [
                Tier(name="Bronze", min_qualifying_spend=0, earning_rate=1.0),
                Tier(name="Silver", min_qualifying_spend=5000, earning_rate=1.25),
                Tier(name="Gold", min_qualifying_spend=15000, earning_rate=1.5),
                Tier(name="Platinum", min_qualifying_spend=30000, earning_rate=2.0),
            ]
        )
    if Rule.query.count() == 0:
        db.session.add(
            Rule(
                name="Standard earning rule",
                points_per_currency=1,
                minimum_order_amount=100,
                expiry_days=365,
                effective_from=BASE_DATE,
                active=True,
            )
        )
    if Reward.query.count() == 0:
        db.session.add(Reward(id="RWD-0001", name="Benchmark voucher", points_cost=500))
    db.session.commit()


def _validate_empty_database():
    existing = {
        "customers": db.session.query(Customer.id).first(),
        "accounts": db.session.query(LoyaltyAccount.id).first(),
        "orders": db.session.query(Order.id).first(),
        "order lines": db.session.query(OrderLine.id).first(),
        "points transactions": db.session.query(PointsTransaction.id).first(),
        "redemptions": db.session.query(Redemption.id).first(),
        "expiry batches": db.session.query(ExpiryBatch.id).first(),
        "balance snapshots": db.session.query(BalanceSnapshot.account_id).first(),
    }
    populated = [name for name, row in existing.items() if row is not None]
    if populated:
        raise ValueError(
            "Benchmark generation requires an empty dataset database; existing rows found in: "
            + ", ".join(populated)
        )


def _anomaly_definitions():
    with (ROOT / "anomaly_cases.json").open(encoding="utf-8") as file:
        return json.load(file)


def _account_index(account_id):
    match = account_id.removeprefix("LOY-")
    if not match.isdigit():
        raise ValueError(f"Invalid account ID in anomaly ground truth: {account_id}")
    return int(match) - 1


def _order_number(order_id):
    match = order_id.removeprefix("ORD-2026-")
    if not match.isdigit():
        raise ValueError(f"Invalid order ID in anomaly ground truth: {order_id}")
    return int(match)


def _code(prefix, number, width):
    return f"{prefix}{number:0{width}d}"


def _existing_sequence_value(prefix, model):
    values = (
        db.session.query(model.id)
        .filter(model.id.like(f"{prefix}%"))
        .yield_per(1000)
    )
    maximum = 0
    for (record_id,) in values:
        match = re.search(r"(\d+)$", record_id)
        if match:
            maximum = max(maximum, int(match.group(1)))
    return maximum


def generate_dataset(
    customer_count=20_000,
    order_count=100_000,
    transaction_count=300_000,
    seed=20261112,
    batch_size=1000,
    append=False,
):
    if customer_count < 4:
        raise ValueError("At least four customers are required by the anomaly ground truth.")
    if order_count < 4 * customer_count:
        raise ValueError(
            "At least four orders per customer are required for the gross-versus-qualifying tier anomaly."
        )
    if transaction_count != order_count * 3:
        raise ValueError("Use exactly three target transactions per order.")
    if batch_size < 1:
        raise ValueError("Batch size must be a positive integer.")

    db.create_all()
    if append:
        initialize_sequences()
        sequence_offsets = {}
        for prefix, model in SEQUENCE_MODELS.items():
            sequence = CodeSequence.query.filter_by(prefix=prefix).with_for_update().first()
            offset = max(
                sequence.value if sequence else 0,
                _existing_sequence_value(prefix, model),
            )
            if sequence is None:
                db.session.add(CodeSequence(prefix=prefix, value=offset))
            else:
                sequence.value = offset
            sequence_offsets[prefix] = offset
        db.session.commit()
    else:
        _validate_empty_database()
        sequence_offsets = {prefix: 0 for prefix in SEQUENCE_MODELS}
    _ensure_catalog()
    definitions = _anomaly_definitions()
    cases = {case["case_id"]: case for case in definitions}
    required_cases = {"AN-001", "AN-002", "AN-003", "AN-004", "AN-005"}
    if set(cases) != required_cases:
        raise ValueError("The anomaly ground truth must contain AN-001 through AN-005 exactly once.")
    snapshot_anomaly_index = _account_index(cases["AN-001"]["entity_id"])
    redemption_account_index = _account_index(cases["AN-002"]["account_id"])
    tier_anomaly_index = _account_index(cases["AN-005"]["entity_id"])
    expiry_source_order_number = _order_number(cases["AN-004"]["source_order_id"])
    if max(snapshot_anomaly_index, redemption_account_index, tier_anomaly_index) >= customer_count:
        raise ValueError("The requested customer count is too small for the configured anomaly cases.")
    if expiry_source_order_number > order_count or _order_number(cases["AN-003"]["entity_id"]) > order_count:
        raise ValueError("The requested order count is too small for the configured anomaly cases.")

    tiers = Tier.query.filter_by(active=True).order_by(Tier.min_qualifying_spend).all()
    if not tiers:
        raise ValueError("At least one active tier is required for benchmark generation.")
    rule = Rule.query.filter_by(active=True).order_by(Rule.id.desc()).first()
    if rule is None:
        raise ValueError("At least one active earning rule is required.")
    incorrect_tier = next(
        (tier for tier in tiers if tier.name.lower() == cases["AN-005"]["incorrect_tier_name"].lower()),
        None,
    )
    if incorrect_tier is None:
        raise ValueError(
            f"The configured tiers must include {cases['AN-005']['incorrect_tier_name']}."
        )
    rng = random.Random(seed)
    customer_offset = sequence_offsets["CUS-"]
    account_offset = sequence_offsets["LOY-"]
    order_offset = sequence_offsets["ORD-2026-"]
    line_offset = sequence_offsets["LINE-"]
    transaction_offset = sequence_offsets["PTS-2026-"]
    redemption_offset = sequence_offsets["RDM-2026-"]
    expiry_offset = sequence_offsets["EXP-2026-"]
    redemption_id = (
        cases["AN-002"]["entity_id"]
        if redemption_offset == 0
        else _code("RDM-2026-", redemption_offset + 1, 6)
    )
    if expiry_offset == 0:
        original_expiry_batch_id = cases["AN-004"]["original_batch_id"]
        expiry_batch_id = cases["AN-004"]["entity_id"]
    else:
        original_expiry_batch_id = _code("EXP-2026-", expiry_offset + 1, 6)
        expiry_batch_id = _code("EXP-2026-", expiry_offset + 2, 6)
    returned_order_id = _code(
        "ORD-2026-",
        order_offset + _order_number(cases["AN-003"]["entity_id"]),
        6,
    )
    counters = {name: 0 for name in TABLES}
    digests = {name: hashlib.sha256() for name in TABLES}
    buffers = {name: [] for name in TABLES}
    account_spend = [Decimal("0.00")] * customer_count
    ledger_balances = [0] * customer_count
    expiry_source = None
    source_by_customer = {}
    transaction_sequence = transaction_offset
    generated_transaction_count = 0
    line_sequence = line_offset

    def write(table_name, row):
        counters[table_name] += 1
        digests[table_name].update(_canonical_row(table_name, row))
        buffers[table_name].append(row)
        if len(buffers[table_name]) >= batch_size:
            if table_name in {"orderline", "pointstransaction"}:
                _insert_chunk(TABLES["order"], buffers["order"])
                buffers["order"] = []
            _insert_chunk(TABLES[table_name], buffers[table_name])
            buffers[table_name] = []

    def flush_all():
        for table_name, rows in buffers.items():
            _insert_chunk(TABLES[table_name], rows)
            buffers[table_name] = []

    customer_rows = []
    account_rows = []
    generated_account_ids = set()
    for customer_index in range(customer_count):
        customer_number = customer_offset + customer_index + 1
        account_number = account_offset + customer_index + 1
        customer_id = _code("CUS-", customer_number, 6)
        account_id = _code("LOY-", account_number, 6)
        customer_row = {
            "customer_id": customer_id,
            "first_name": f"Benchmark Customer {customer_number:06d}",
            "email": f"benchmark-customer-{seed}-{customer_number:06d}@example.test",
            "phone": f"+910000{customer_number:06d}",
            "created_at": datetime.combine(BASE_DATE, datetime.min.time()),
        }
        account_row = {
            "account_id": account_id,
            "customer_id": customer_id,
            "tier_id": tiers[0].id,
            "qualifying_spend": Decimal("0.00"),
            "account_status": "ACTIVE",
            "created_at": datetime.combine(BASE_DATE, datetime.min.time()),
        }
        write("customer", customer_row)
        write("loyaltyaccount", account_row)
        customer_rows.append(customer_id)
        account_rows.append(account_id)
        generated_account_ids.add(account_id)
    _insert_chunk(TABLES["customer"], buffers["customer"])
    buffers["customer"] = []
    _insert_chunk(TABLES["loyaltyaccount"], buffers["loyaltyaccount"])
    buffers["loyaltyaccount"] = []

    # Orders are distributed round-robin so the requested population scales predictably.
    generated_order_ids = set()
    for order_number in range(1, order_count + 1):
        customer_index = (order_number - 1) % customer_count
        customer_id = customer_rows[customer_index]
        account_id = account_rows[customer_index]
        order_id = _code("ORD-2026-", order_offset + order_number, 6)
        generated_order_ids.add(order_id)
        order_date = datetime.combine(
            BASE_DATE + timedelta(days=(order_number - 1) % 730),
            datetime.min.time(),
        )
        if customer_index == tier_anomaly_index:
            incorrect_threshold = Decimal(incorrect_tier.min_qualifying_spend)
            if incorrect_threshold <= 0:
                raise ValueError("The incorrect tier must have a positive spend threshold.")
            if order_number == tier_anomaly_index + 1:
                gross = incorrect_threshold + Decimal("100.00")
                net_target = max(Decimal("0.00"), incorrect_threshold - Decimal("1.00"))
                discount = gross - net_target
            else:
                gross = Decimal("100.00")
                discount = gross
        else:
            gross_cents = rng.randint(25_000, 1_000_000)
            discount_cents = rng.randint(0, gross_cents // 4)
            gross = Decimal(gross_cents) / 100
            discount = Decimal(discount_cents) / 100
        net = (gross - discount).quantize(Decimal("0.01"))
        spend_before = account_spend[customer_index]
        current_tier = tiers[0]
        for tier in tiers:
            if spend_before >= Decimal(tier.min_qualifying_spend):
                current_tier = tier
        points = 0
        if net >= Decimal(rule.minimum_order_amount):
            points = int(
                (net * Decimal(rule.points_per_currency) * Decimal(current_tier.earning_rate))
                .to_integral_value(rounding=ROUND_FLOOR)
            )
        order_row = {
            "order_id": order_id,
            "customer_id": customer_id,
            "order_date": order_date,
            "gross_amount": gross,
            "discount_amount": discount,
            "net_amount": net,
            "returned_amount": Decimal("0.00"),
            "eligible_net_spend": net,
            "order_status": "COMPLETED",
        }
        write("order", order_row)

        gross_cents = int(gross * 100)
        discount_cents = int(discount * 100)
        net_cents = gross_cents - discount_cents
        line_cents, remainder = divmod(net_cents, 3)
        line_amounts = [line_cents + (1 if i < remainder else 0) for i in range(3)]
        for line_index, line_amount in enumerate(line_amounts):
            line_sequence += 1
            line_row = {
                "order_line_id": _code("LINE-", line_sequence, 8),
                "order_id": order_id,
                "sku": f"SKU-{line_index + 1:02d}",
                "quantity": 1,
                "unit_price": Decimal(line_amount) / 100,
                "line_net_amount": Decimal(line_amount) / 100,
            }
            write("orderline", line_row)

        lot_count = 2 if order_number in {1, 2, 3} else 3
        point_parts = [points // lot_count + (1 if i < points % lot_count else 0)
                       for i in range(lot_count)]
        expiry_date = order_date.date() + timedelta(days=rule.expiry_days)
        for part in point_parts:
            transaction_sequence += 1
            generated_transaction_count += 1
            transaction_id = _code("PTS-2026-", transaction_sequence, 8)
            transaction_row = {
                "transaction_id": transaction_id,
                "account_id": account_id,
                "transaction_type": "ACCRUAL",
                "points_change": part,
                "order_id": order_id,
                "redemption_id": None,
                "reference_transaction_id": None,
                "lot_expiry_date": expiry_date,
                "expiry_batch_id": None,
                "description": f"Benchmark accrual on {order_id}",
                "issue_type": "NONE",
                "transaction_date": order_date,
            }
            write("pointstransaction", transaction_row)
            ledger_balances[customer_index] += part
            source_by_customer.setdefault(customer_index, transaction_id)
            if order_number == expiry_source_order_number and expiry_source is None:
                expiry_source = (
                    transaction_id,
                    account_id,
                    part,
                    expiry_date,
                    customer_index,
                )

        account_spend[customer_index] += net

    # Inject deterministic, labelled anomalies while preserving the exact transaction target.
    if account_spend[tier_anomaly_index] >= Decimal(incorrect_tier.min_qualifying_spend):
        raise ValueError("The tier anomaly account must remain below the incorrect tier's spend threshold.")
    flush_all()
    account_two_balance = ledger_balances[redemption_account_index]
    overspend = account_two_balance + cases["AN-002"]["excess_points"]
    transaction_sequence += 1
    redemption_row = {
        "redemption_id": redemption_id,
        "account_id": account_rows[redemption_account_index],
        "reward_id": Reward.query.order_by(Reward.id).first().id,
        "points_spent": overspend,
        "status": "APPROVED",
        "redemption_date": datetime.combine(BASE_DATE, datetime.min.time()),
    }
    write("redemption", redemption_row)
    _insert_chunk(TABLES["redemption"], buffers["redemption"])
    buffers["redemption"] = []
    redemption_transaction = {
        "transaction_id": _code("PTS-2026-", transaction_sequence, 8),
        "account_id": account_rows[redemption_account_index],
        "transaction_type": "REDEMPTION",
        "points_change": -overspend,
        "order_id": None,
        "redemption_id": redemption_id,
        "reference_transaction_id": source_by_customer[redemption_account_index],
        "lot_expiry_date": None,
        "expiry_batch_id": None,
        "description": "Injected oversized redemption",
        "issue_type": "REDEMPTION_EXCEEDS_BALANCE",
        "transaction_date": datetime.combine(BASE_DATE, datetime.min.time()),
    }
    write("pointstransaction", redemption_transaction)
    generated_transaction_count += 1
    ledger_balances[redemption_account_index] -= overspend

    db.session.execute(
        Order.__table__.update()
        .where(Order.__table__.c.order_id == returned_order_id)
        .values(returned_amount=Order.__table__.c.eligible_net_spend, order_status="REFUNDED")
    )
    returned_order = db.session.query(Order).filter_by(id=returned_order_id).one()
    digests["order"] = hashlib.sha256()
    for row in db.session.query(Order).order_by(Order.id).yield_per(batch_size):
        if row.id not in generated_order_ids:
            continue
        digests["order"].update(
            _canonical_row(
                "order",
                {
                    "order_id": row.id,
                    "customer_id": row.customer_id,
                    "order_date": row.order_date,
                    "gross_amount": row.gross_amount,
                    "discount_amount": row.discount_amount,
                    "net_amount": row.net_amount,
                    "returned_amount": row.returned_amount,
                    "eligible_net_spend": row.qualifying_spend,
                    "order_status": row.status,
                },
            )
        )

    if expiry_source is None:
        raise RuntimeError("The benchmark failed to create an accrual lot for the expiry anomaly.")
    source_id, source_account, source_points, source_expiry, _ = expiry_source
    original_expiry_batch_row = {
        "id": original_expiry_batch_id,
        "run_date": source_expiry + timedelta(days=1),
        "points_expired": source_points,
        "status": "COMPLETED",
        "created_at": datetime.combine(BASE_DATE, datetime.min.time()),
    }
    expiry_batch_row = {
        "id": expiry_batch_id,
        "run_date": source_expiry + timedelta(days=1),
        "points_expired": source_points,
        "status": "COMPLETED",
        "created_at": datetime.combine(BASE_DATE, datetime.min.time()),
    }
    write("expiry_batch_run", original_expiry_batch_row)
    write("expiry_batch_run", expiry_batch_row)
    _insert_chunk(TABLES["expiry_batch_run"], buffers["expiry_batch_run"])
    buffers["expiry_batch_run"] = []
    for _ in range(2):
        transaction_sequence += 1
        generated_transaction_count += 1
        batch_id = original_expiry_batch_id if _ == 0 else expiry_batch_id
        expiry_transaction = {
            "transaction_id": _code("PTS-2026-", transaction_sequence, 8),
            "account_id": source_account,
            "transaction_type": "EXPIRY",
            "points_change": -source_points,
            "order_id": None,
            "redemption_id": None,
            "reference_transaction_id": source_id,
            "lot_expiry_date": source_expiry,
            "expiry_batch_id": batch_id,
            "description": "Injected duplicate expiry debit",
            "issue_type": "DUPLICATE_EXPIRY",
            "transaction_date": datetime.combine(source_expiry + timedelta(days=1), datetime.min.time()),
        }
        write("pointstransaction", expiry_transaction)
        ledger_balances[expiry_source[4]] -= source_points

    if generated_transaction_count != transaction_count:
        raise RuntimeError(
            f"Generated {generated_transaction_count} transactions; expected {transaction_count}."
        )

    snapshot_time = datetime.combine(BASE_DATE + timedelta(days=730), datetime.min.time())
    for customer_index, account_id in enumerate(account_rows):
        points_balance = ledger_balances[customer_index]
        if customer_index == snapshot_anomaly_index:
            points_balance += cases["AN-001"]["offset_points"]
        snapshot_row = {
            "account_id": account_id,
            "points_balance": points_balance,
            "snapshot_at": snapshot_time,
        }
        write("balance_snapshot", snapshot_row)

    cases["AN-001"]["entity_id"] = account_rows[snapshot_anomaly_index]
    cases["AN-002"]["entity_id"] = redemption_id
    cases["AN-002"]["account_id"] = account_rows[redemption_account_index]
    cases["AN-003"]["entity_id"] = returned_order_id
    cases["AN-004"]["entity_id"] = expiry_batch_id
    cases["AN-004"]["original_batch_id"] = original_expiry_batch_id
    cases["AN-004"]["source_order_id"] = _code(
        "ORD-2026-",
        order_offset + expiry_source_order_number,
        6,
    )
    cases["AN-005"]["entity_id"] = account_rows[tier_anomaly_index]

    tier_ids_by_threshold = sorted(tiers, key=lambda tier: Decimal(tier.min_qualifying_spend))
    account_updates = []
    for customer_index, account_id in enumerate(account_rows):
        tier = tier_ids_by_threshold[0]
        for candidate in tier_ids_by_threshold:
            if account_spend[customer_index] >= Decimal(candidate.min_qualifying_spend):
                tier = candidate
        if customer_index == tier_anomaly_index:
            tier = incorrect_tier
        account_updates.append(
            {
                "account_id": account_id,
                "customer_id": customer_rows[customer_index],
                "tier_id": tier.id,
                "qualifying_spend": account_spend[customer_index],
                "account_status": "ACTIVE",
                "created_at": datetime.combine(BASE_DATE, datetime.min.time()),
            }
        )
    for account_row in account_updates:
        db.session.execute(
            LoyaltyAccount.__table__.update()
            .where(LoyaltyAccount.__table__.c.account_id == account_row["account_id"])
            .values(
                tier_id=account_row["tier_id"],
                qualifying_spend=account_row["qualifying_spend"],
            )
        )
    db.session.flush()
    digests["loyaltyaccount"] = hashlib.sha256()
    for row in db.session.query(LoyaltyAccount).order_by(LoyaltyAccount.id).yield_per(batch_size):
        if row.id not in generated_account_ids:
            continue
        digests["loyaltyaccount"].update(
            _canonical_row(
                "loyaltyaccount",
                {
                    "account_id": row.id,
                    "customer_id": row.customer_id,
                    "tier_id": row.tier_id,
                    "qualifying_spend": row.qualifying_spend,
                    "account_status": row.status,
                    "created_at": row.created_at,
                },
            )
        )

    flush_all()
    initialize_sequences()
    db.session.commit()

    anomaly_ground_truth = []
    for definition in definitions:
        case = dict(definition)
        case["injected_effect"] = definition["injected_effect"]
        anomaly_ground_truth.append(case)
    if counters["pointstransaction"] != transaction_count:
        raise RuntimeError(
            f"Stored {counters['pointstransaction']} transactions; expected {transaction_count}."
        )
    if counters["customer"] != customer_count or counters["order"] != order_count:
        raise RuntimeError("Generated dataset counts did not match the requested acceptance targets.")

    table_checksums = {name: digest.hexdigest() for name, digest in sorted(digests.items())}
    dataset_digest = hashlib.sha256(
        json.dumps(table_checksums, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "seed": seed,
        "counts": counters,
        "checksums": table_checksums,
        "dataset_checksum": dataset_digest,
        "ground_truth": anomaly_ground_truth,
    }
