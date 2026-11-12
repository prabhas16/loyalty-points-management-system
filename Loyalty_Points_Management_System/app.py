import os
from datetime import datetime, date, timedelta
from decimal import Decimal, ROUND_FLOOR
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, flash, Response
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, inspect as sa_inspect, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.engine import URL
from sqlalchemy.orm import joinedload, synonym
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "change-this-secret-key")
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
    "DATABASE_URL", "mysql+pymysql://root:password@localhost:3306/loyalty_db"
)
if not os.getenv("DATABASE_URL") and os.getenv("DB_NAME"):
    app.config["SQLALCHEMY_DATABASE_URI"] = URL.create(
        "mysql+pymysql",
        username=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASSWORD", ""),
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "3306")),
        database=os.environ["DB_NAME"],
    )
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

class Tier(db.Model):
    __tablename__ = "tier"

    id = db.Column("tier_id", db.Integer, primary_key=True)
    name = db.Column("tier_name", db.String(30), unique=True, nullable=False)
    min_qualifying_spend = db.Column(db.Numeric(12,2), nullable=False, default=0)
    earning_rate = db.Column("earn_rate", db.Numeric(8,3), nullable=False, default=1)
    active = db.Column(db.Boolean, default=True, nullable=False)

class Rule(db.Model):
    __tablename__ = "rule"

    id = db.Column("rule_id", db.Integer, primary_key=True)
    name = db.Column("rule_name", db.String(100), nullable=False)
    points_per_currency = db.Column(db.Numeric(8,3), nullable=False, default=1)
    minimum_order_amount = db.Column("min_order_amount", db.Numeric(12,2), nullable=False, default=0)
    expiry_days = db.Column(db.Integer, nullable=False, default=365)
    effective_from = db.Column(db.Date, nullable=False, default=date.today)
    effective_to = db.Column(db.Date)
    active = db.Column(db.Boolean, default=True, nullable=False)

class Customer(db.Model):
    __tablename__ = "customer"

    id = db.Column("customer_id", db.String(20), primary_key=True)
    customer_code = synonym("id")
    full_name = db.Column("first_name", db.String(80), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    phone = db.Column(db.String(30))
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    account = db.relationship("LoyaltyAccount", backref="customer", uselist=False)

class LoyaltyAccount(db.Model):
    __tablename__ = "loyaltyaccount"

    id = db.Column("account_id", db.String(30), primary_key=True)
    account_code = synonym("id")
    customer_id = db.Column(db.String(20), db.ForeignKey("customer.customer_id"), unique=True, nullable=False)
    tier_id = db.Column(db.Integer, db.ForeignKey("tier.tier_id"), nullable=False)
    qualifying_spend = db.Column(db.Numeric(12,2), default=0, nullable=False)
    status = db.Column("account_status", db.String(20), default="ACTIVE", nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    tier = db.relationship("Tier")

class Order(db.Model):
    __tablename__ = "order"

    id = db.Column("order_id", db.String(30), primary_key=True)
    order_code = synonym("id")
    customer_id = db.Column(db.String(20), db.ForeignKey("customer.customer_id"), nullable=False)
    order_date = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    gross_amount = db.Column(db.Numeric(12,2), nullable=False)
    discount_amount = db.Column(db.Numeric(12,2), default=0, nullable=False)
    net_amount = db.Column(db.Numeric(12,2), nullable=False)
    returned_amount = db.Column(db.Numeric(12,2), default=0, nullable=False)
    qualifying_spend = db.Column("eligible_net_spend", db.Numeric(12,2), nullable=False)
    status = db.Column("order_status", db.String(30), default="COMPLETED", nullable=False)
    customer = db.relationship("Customer")

class OrderLine(db.Model):
    __tablename__ = "orderline"

    id = db.Column("order_line_id", db.String(30), primary_key=True)
    order_id = db.Column(db.String(30), db.ForeignKey("order.order_id"), nullable=False)
    item_name = db.Column("sku", db.String(40), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    unit_price = db.Column(db.Numeric(12,2), nullable=False)
    line_total = db.Column("line_net_amount", db.Numeric(12,2), nullable=False)
    order = db.relationship("Order", backref="lines")

class PointsTransaction(db.Model):
    __tablename__ = "pointstransaction"

    id = db.Column("transaction_id", db.String(30), primary_key=True)
    transaction_code = synonym("id")
    account_id = db.Column(db.String(30), db.ForeignKey("loyaltyaccount.account_id"), nullable=False)
    transaction_type = db.Column(db.String(20), nullable=False) # ACCRUAL, REDEMPTION, REVERSAL, EXPIRY, ADJUSTMENT
    points = db.Column("points_change", db.BigInteger, nullable=False) # positive accrual; negative debit
    order_id = db.Column(db.String(30), db.ForeignKey("order.order_id"))
    redemption_id = db.Column(db.String(30), db.ForeignKey("redemption.redemption_id"))
    source_accrual_id = db.Column("reference_transaction_id", db.String(30), db.ForeignKey("pointstransaction.transaction_id"))
    expiry_date = db.Column("lot_expiry_date", db.Date)
    expiry_batch_id = db.Column(db.String(30), db.ForeignKey("expiry_batch_run.id"))
    description = db.Column(db.String(255))
    issue_type = db.Column(db.String(60), nullable=False, default="NONE")
    created_at = db.Column("transaction_date", db.DateTime, default=datetime.utcnow, nullable=False)
    account = db.relationship("LoyaltyAccount")
    order = db.relationship("Order")
    source_accrual = db.relationship("PointsTransaction", remote_side=[id], foreign_keys=[source_accrual_id])

class Reward(db.Model):
    __tablename__ = "reward"

    id = db.Column("reward_id", db.String(20), primary_key=True)
    reward_code = synonym("id")
    name = db.Column("reward_name", db.String(100), nullable=False)
    points_cost = db.Column(db.BigInteger, nullable=False)
    active = db.Column(db.Boolean, default=True, nullable=False)

class Redemption(db.Model):
    __tablename__ = "redemption"

    id = db.Column("redemption_id", db.String(30), primary_key=True)
    redemption_code = synonym("id")
    account_id = db.Column(db.String(30), db.ForeignKey("loyaltyaccount.account_id"), nullable=False)
    reward_id = db.Column(db.String(20), db.ForeignKey("reward.reward_id"), nullable=False)
    points_spent = db.Column(db.BigInteger, nullable=False)
    status = db.Column(db.String(20), default="APPROVED", nullable=False)
    created_at = db.Column("redemption_date", db.DateTime, default=datetime.utcnow, nullable=False)
    account = db.relationship("LoyaltyAccount")
    reward = db.relationship("Reward")

class ExpiryBatch(db.Model):
    __tablename__ = "expiry_batch_run"

    id = db.Column(db.String(30), primary_key=True)
    batch_code = synonym("id")
    run_date = db.Column(db.Date, nullable=False)
    points_expired = db.Column(db.Integer, nullable=False, default=0)
    status = db.Column(db.String(20), nullable=False, default="COMPLETED")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

def next_code(prefix, model, width=8):
    count = db.session.query(func.count(model.id)).scalar() or 0
    sequence = count + 1
    code = f"{prefix}{sequence:0{width}d}"
    while db.session.query(model.id).filter_by(id=code).first():
        sequence += 1
        code = f"{prefix}{sequence:0{width}d}"
    return code


def migrate_existing_schema():
    inspector = sa_inspect(db.engine)
    tables = set(inspector.get_table_names())
    if not tables:
        db.create_all()
        return

    required_columns = {
        "customer": {"customer_id", "first_name", "email"},
        "tier": {"tier_id", "tier_name", "min_qualifying_spend", "earn_rate"},
        "loyaltyaccount": {"account_id", "customer_id", "tier_id", "account_status"},
        "rule": {"rule_id", "rule_name", "points_per_currency", "min_order_amount"},
        "order": {
            "order_id", "customer_id", "gross_amount", "discount_amount",
            "net_amount", "eligible_net_spend", "order_status",
        },
        "orderline": {"order_line_id", "order_id", "sku", "line_net_amount"},
        "pointstransaction": {
            "transaction_id", "account_id", "transaction_type", "points_change",
            "transaction_date", "reference_transaction_id", "lot_expiry_date", "issue_type",
        },
        "reward": {"reward_id", "reward_name", "points_cost", "active"},
        "redemption": {"redemption_id", "account_id", "reward_id", "redemption_date", "status"},
        "expirybatch": {"expiry_batch_id", "account_id", "transaction_id", "expiry_date", "status"},
    }
    if not set(required_columns).issubset(tables):
        missing = ", ".join(sorted(set(required_columns) - tables))
        raise RuntimeError(
            "The configured database has an unsupported existing schema. "
            f"Missing required tables: {missing}. No schema changes were made."
        )
    for table, expected in required_columns.items():
        existing = {column["name"] for column in inspector.get_columns(table)}
        missing = expected - existing
        if missing:
            raise RuntimeError(
                f"The existing {table} table is missing required columns: "
                f"{', '.join(sorted(missing))}. No schema changes were made."
            )

    additions = {
        "customer": {"phone": "VARCHAR(30) NULL"},
        "tier": {"active": "BOOLEAN NOT NULL DEFAULT TRUE"},
        "loyaltyaccount": {"qualifying_spend": "DECIMAL(12,2) NOT NULL DEFAULT 0"},
        "rule": {
            "expiry_days": "INTEGER NOT NULL DEFAULT 365",
            "active": "BOOLEAN NOT NULL DEFAULT TRUE",
        },
        "order": {"returned_amount": "DECIMAL(12,2) NOT NULL DEFAULT 0"},
        "pointstransaction": {
            "redemption_id": "VARCHAR(30) NULL",
            "expiry_batch_id": "VARCHAR(30) NULL",
            "description": "VARCHAR(255) NULL",
        },
    }
    added_columns = set()
    preparer = db.engine.dialect.identifier_preparer
    with db.engine.begin() as connection:
        for table, columns in additions.items():
            present = {column["name"] for column in sa_inspect(connection).get_columns(table)}
            for name, definition in columns.items():
                if name not in present:
                    quoted_table = preparer.quote(table)
                    quoted_name = preparer.quote(name)
                    connection.exec_driver_sql(
                        f"ALTER TABLE {quoted_table} ADD COLUMN {quoted_name} {definition}"
                    )
                    added_columns.add((table, name))

        if ("order", "returned_amount") in added_columns:
            connection.exec_driver_sql(
                'UPDATE `order` SET returned_amount = eligible_net_spend '
                "WHERE order_status = 'REFUNDED'"
            )
        if ("loyaltyaccount", "qualifying_spend") in added_columns:
            connection.exec_driver_sql(
                "UPDATE loyaltyaccount AS a SET qualifying_spend = ("
                "SELECT COALESCE(SUM(GREATEST(o.eligible_net_spend - o.returned_amount, 0)), 0) "
                "FROM `order` AS o WHERE o.customer_id = a.customer_id)"
            )

    db.create_all()
    inspector = sa_inspect(db.engine)
    foreign_keys = inspector.get_foreign_keys("pointstransaction")
    existing_fks = {
        tuple(fk.get("constrained_columns") or ()) for fk in foreign_keys
    }
    with db.engine.begin() as connection:
        if ("redemption_id",) not in existing_fks:
            connection.exec_driver_sql(
                "ALTER TABLE pointstransaction ADD CONSTRAINT "
                "fk_pointstransaction_redemption "
                "FOREIGN KEY (redemption_id) REFERENCES redemption (redemption_id)"
            )
        if ("expiry_batch_id",) not in existing_fks:
            connection.exec_driver_sql(
                "ALTER TABLE pointstransaction ADD CONSTRAINT "
                "fk_pointstransaction_expiry_batch "
                "FOREIGN KEY (expiry_batch_id) REFERENCES expiry_batch_run (id)"
            )


def balance_for(account_id):
    return int(db.session.query(func.coalesce(func.sum(PointsTransaction.points), 0))
               .filter_by(account_id=account_id).scalar() or 0)

def lot_remaining(accrual):
    rows = PointsTransaction.query.filter(
        or_(PointsTransaction.id == accrual.id,
            PointsTransaction.source_accrual_id == accrual.id)
    ).all()
    return sum(int(x.points) for x in rows)

def refresh_tier(account):
    tiers = Tier.query.filter_by(active=True).order_by(Tier.min_qualifying_spend.asc()).all()
    chosen = tiers[0] if tiers else account.tier
    for tier in tiers:
        if Decimal(account.qualifying_spend) >= Decimal(tier.min_qualifying_spend):
            chosen = tier
    account.tier_id = chosen.id

def record_transaction(account_id, kind, points, description, order_id=None,
                       redemption_id=None, source_accrual_id=None, expiry_date=None, expiry_batch_id=None):
    transaction_code = next_code("PTS-2026-", PointsTransaction)
    tx = PointsTransaction(
        id=transaction_code,
        account_id=account_id, transaction_type=kind, points=int(points),
        description=description, order_id=order_id, redemption_id=redemption_id,
        source_accrual_id=source_accrual_id, expiry_date=expiry_date, expiry_batch_id=expiry_batch_id
    )
    db.session.add(tx)
    return tx

@app.route("/")
def dashboard():
    customers = Customer.query.count()
    orders = Order.query.count()
    transactions = PointsTransaction.query.count()
    outstanding = db.session.query(func.coalesce(func.sum(PointsTransaction.points),0)).scalar() or 0
    total_redeemed = db.session.query(func.coalesce(func.sum(-PointsTransaction.points),0)).filter_by(transaction_type="REDEMPTION").scalar() or 0
    recent = PointsTransaction.query.options(joinedload(PointsTransaction.account)).order_by(PointsTransaction.created_at.desc()).limit(8).all()
    tier_counts = db.session.query(Tier.name, func.count(LoyaltyAccount.id)).outerjoin(LoyaltyAccount).group_by(Tier.name).all()
    return render_template("dashboard.html", customers=customers, orders=orders,
        transactions=transactions, outstanding=int(outstanding), total_redeemed=int(total_redeemed),
        recent=recent, tier_counts=tier_counts)

@app.route("/customers")
def customers():
    q = request.args.get("q","").strip()
    query = Customer.query
    if q:
        query = query.filter(or_(Customer.full_name.ilike(f"%{q}%"),
                                 Customer.customer_code.ilike(f"%{q}%"),
                                 Customer.email.ilike(f"%{q}%")))
    customer_rows = query.order_by(Customer.id.desc()).limit(300).all()
    balances = {c.account.id: balance_for(c.account.id) for c in customer_rows if c.account}
    return render_template("customers.html", customers=customer_rows, balances=balances, q=q)

@app.route("/customers/new", methods=["GET","POST"])
def new_customer():
    if request.method == "POST":
        name=request.form["full_name"].strip()
        email=request.form["email"].strip().lower()
        if not name or not email:
            flash("Name and email are required.", "danger")
        elif Customer.query.filter_by(email=email).first():
            flash("This email is already registered.", "danger")
        else:
            customer_code=next_code("CUS-",Customer,width=6)
            customer=Customer(id=customer_code,
                full_name=name,email=email,phone=request.form.get("phone","").strip())
            db.session.add(customer); db.session.flush()
            tier=Tier.query.order_by(Tier.min_qualifying_spend.asc()).first()
            if not tier:
                tier=Tier(name="Bronze",min_qualifying_spend=0,earning_rate=1)
                db.session.add(tier); db.session.flush()
            account_code=next_code("LOY-",LoyaltyAccount,width=6)
            db.session.add(LoyaltyAccount(id=account_code,
                customer_id=customer.id,tier_id=tier.id))
            db.session.commit()
            flash("Customer and loyalty account created.", "success")
            return redirect(url_for("customers"))
    return render_template("customer_form.html")

@app.route("/orders", methods=["GET","POST"])
def orders():
    if request.method=="POST":
        customer=Customer.query.get_or_404(request.form["customer_id"])
        gross=Decimal(request.form["gross_amount"])
        discount=Decimal(request.form.get("discount_amount") or "0")
        item_name=request.form.get("item_name","Purchase").strip() or "Purchase"
        if gross <= 0 or discount < 0 or discount > gross or len(item_name)>40:
            flash("Enter a positive order amount, a valid discount, and an item name of at most 40 characters.", "danger")
        else:
            net=(gross-discount).quantize(Decimal("0.01"))
            order_code=next_code("ORD-2026-",Order,width=6)
            order=Order(id=order_code,
                customer_id=customer.id,gross_amount=gross,discount_amount=discount,
                net_amount=net,qualifying_spend=net,status="COMPLETED")
            db.session.add(order); db.session.flush()
            db.session.add(OrderLine(id=next_code("LINE-",OrderLine),order_id=order.id,item_name=item_name,
                quantity=1,unit_price=net,line_total=net))
            account=customer.account
            rule=Rule.query.filter_by(active=True).order_by(Rule.id.desc()).first()
            rate=Decimal(account.tier.earning_rate) * (Decimal(rule.points_per_currency) if rule else Decimal("1"))
            minimum=Decimal(rule.minimum_order_amount) if rule else Decimal("0")
            points=int((net*rate).to_integral_value(rounding=ROUND_FLOOR)) if net>=minimum else 0
            if points:
                expiry_days=rule.expiry_days if rule else 365
                record_transaction(account.id,"ACCRUAL",points,f"Earned on {order.order_code}",
                    order_id=order.id,expiry_date=date.today()+timedelta(days=expiry_days))
            account.qualifying_spend=Decimal(account.qualifying_spend)+net
            refresh_tier(account)
            db.session.commit()
            flash(f"Order saved. {points} points accrued.", "success")
            return redirect(url_for("orders"))
    recent=Order.query.order_by(Order.id.desc()).limit(100).all()
    return render_template("orders.html", customers=Customer.query.order_by(Customer.full_name).all(), orders=recent)

@app.route("/returns", methods=["GET","POST"])
def returns():
    if request.method=="POST":
        order=Order.query.filter_by(order_code=request.form["order_code"].strip()).first()
        amount=Decimal(request.form["return_amount"])
        if not order:
            flash("Order not found.", "danger")
        elif amount<=0 or amount>Decimal(order.qualifying_spend)-Decimal(order.returned_amount):
            flash("Return amount must be positive and no greater than the unreturned qualifying amount.", "danger")
        else:
            accruals=PointsTransaction.query.filter_by(order_id=order.id,transaction_type="ACCRUAL").all()
            if not accruals:
                flash("No accrual exists for this order.", "warning")
            else:
                for accrual in accruals:
                    original_net=Decimal(order.qualifying_spend)
                    new_returned=Decimal(order.returned_amount)+amount
                    target_reversal=int((Decimal(accrual.points)*new_returned/original_net).to_integral_value(rounding=ROUND_FLOOR))
                    already=sum(-int(t.points) for t in PointsTransaction.query.filter_by(
                        source_accrual_id=accrual.id,transaction_type="REVERSAL").all())
                    delta=max(0,target_reversal-already)
                    if delta:
                        record_transaction(order.customer.account.id,"REVERSAL",-delta,
                            f"Return against {order.order_code}",order_id=order.id,source_accrual_id=accrual.id)
                order.returned_amount=Decimal(order.returned_amount)+amount
                order.status="PARTIALLY_RETURNED" if order.returned_amount<order.qualifying_spend else "REFUNDED"
                account=order.customer.account
                account.qualifying_spend=max(Decimal("0"),Decimal(account.qualifying_spend)-amount)
                refresh_tier(account)
                db.session.commit()
                flash("Return recorded and earned points reversed proportionally.", "success")
                return redirect(url_for("returns"))
    return render_template("returns.html", orders=Order.query.order_by(Order.id.desc()).limit(100).all())

@app.route("/rewards", methods=["GET","POST"])
def rewards():
    if request.method=="POST":
        name=request.form["name"].strip()
        cost=int(request.form["points_cost"])
        if not name or cost<=0:
            flash("Reward name and positive points cost are required.","danger")
        else:
            reward_code=next_code("RWD-",Reward,width=4)
            db.session.add(Reward(id=reward_code,name=name,points_cost=cost))
            db.session.commit(); flash("Reward created.","success")
            return redirect(url_for("rewards"))
    return render_template("rewards.html", rewards=Reward.query.order_by(Reward.id.desc()).all())

@app.route("/redeem", methods=["GET","POST"])
def redeem():
    if request.method=="POST":
        account=LoyaltyAccount.query.filter_by(account_code=request.form["account_code"].strip()).first()
        reward=Reward.query.get(request.form["reward_id"])
        if not account:
            flash("Loyalty account not found.","danger")
        elif not reward or not reward.active:
            flash("Select an active reward.","danger")
        elif balance_for(account.id)<reward.points_cost:
            flash(f"Insufficient points. Available balance: {balance_for(account.id)}.","danger")
        else:
            try:
                # Transaction is committed as one unit; production deployments should use row-level locking.
                redemption_code=next_code("RDM-2026-",Redemption,width=6)
                redemption=Redemption(id=redemption_code,
                    account_id=account.id,reward_id=reward.id,points_spent=reward.points_cost,status="APPROVED")
                db.session.add(redemption); db.session.flush()
                remaining=reward.points_cost
                lots=PointsTransaction.query.filter_by(account_id=account.id,transaction_type="ACCRUAL").order_by(
                    PointsTransaction.created_at.asc(),PointsTransaction.id.asc()).all()
                for lot in lots:
                    available=max(0,lot_remaining(lot))
                    take=min(available,remaining)
                    if take:
                        record_transaction(account.id,"REDEMPTION",-take,
                            f"Redeemed {reward.reward_code}",redemption_id=redemption.id,source_accrual_id=lot.id)
                        remaining-=take
                    if remaining==0: break
                if remaining:
                    raise ValueError("Balance changed during redemption. Please retry.")
                db.session.commit()
                flash(f"Redemption approved: {redemption.redemption_code}.","success")
                return redirect(url_for("redeem"))
            except Exception as exc:
                db.session.rollback(); flash(str(exc),"danger")
    return render_template("redeem.html", rewards=Reward.query.filter_by(active=True).all(),
        accounts=LoyaltyAccount.query.join(Customer).order_by(Customer.full_name).all(),
        redemptions=Redemption.query.order_by(Redemption.id.desc()).limit(50).all())

@app.route("/expiry", methods=["GET","POST"])
def expiry():
    if request.method=="POST":
        run_date=date.fromisoformat(request.form.get("run_date") or date.today().isoformat())
        batch_code=next_code("EXP-2026-",ExpiryBatch,width=6)
        batch=ExpiryBatch(id=batch_code,
            run_date=run_date,points_expired=0,status="RUNNING")
        db.session.add(batch); db.session.flush()
        total=0
        accruals=PointsTransaction.query.filter(
            PointsTransaction.transaction_type=="ACCRUAL",
            PointsTransaction.expiry_date.isnot(None),
            PointsTransaction.expiry_date<=run_date).order_by(PointsTransaction.id.asc()).all()
        for lot in accruals:
            remaining=max(0,lot_remaining(lot))
            if remaining:
                record_transaction(lot.account_id,"EXPIRY",-remaining,
                    f"Expired in {batch.batch_code}",source_accrual_id=lot.id,expiry_batch_id=batch.id)
                total+=remaining
        batch.points_expired=total; batch.status="COMPLETED"
        db.session.commit()
        flash(f"Expiry completed. {total} points expired. Running the same date again will expire zero additional points.","success")
        return redirect(url_for("expiry"))
    batches=ExpiryBatch.query.order_by(ExpiryBatch.id.desc()).limit(30).all()
    return render_template("expiry.html", batches=batches, today=date.today().isoformat())

@app.route("/ledger")
def ledger():
    q=request.args.get("q","").strip()
    query=PointsTransaction.query.join(LoyaltyAccount).join(Customer)
    if q:
        query=query.filter(or_(PointsTransaction.transaction_code.ilike(f"%{q}%"),
            PointsTransaction.description.ilike(f"%{q}%"),Customer.full_name.ilike(f"%{q}%"),
            Customer.customer_code.ilike(f"%{q}%")))
    rows=query.order_by(PointsTransaction.id.desc()).limit(500).all()
    return render_template("ledger.html", rows=rows, q=q)

@app.route("/reports")
def reports():
    by_type=db.session.query(PointsTransaction.transaction_type,func.count(PointsTransaction.id),
        func.coalesce(func.sum(PointsTransaction.points),0)).group_by(PointsTransaction.transaction_type).all()
    by_tier=db.session.query(Tier.name,func.count(LoyaltyAccount.id),
        func.coalesce(func.sum(LoyaltyAccount.qualifying_spend),0)).outerjoin(LoyaltyAccount).group_by(Tier.name).all()
    return render_template("reports.html", by_type=by_type,by_tier=by_tier)

@app.route("/export/ledger.csv")
def export_ledger():
    rows=PointsTransaction.query.order_by(PointsTransaction.id.asc()).all()
    def generate():
        yield "transaction_code,account_id,type,points,order_id,redemption_id,source_accrual_id,expiry_date,description,created_at\\n"
        for t in rows:
            vals=[t.transaction_code,t.account_id,t.transaction_type,t.points,t.order_id or "",
                t.redemption_id or "",t.source_accrual_id or "",t.expiry_date or "",(t.description or "").replace('"','""'),t.created_at.isoformat()]
            yield ",".join('"'+str(v)+'"' for v in vals)+"\\n"
    return Response(generate(),mimetype="text/csv",headers={"Content-Disposition":"attachment; filename=points_ledger.csv"})

@app.route("/setup")
def setup():
    migrate_existing_schema()
    if Tier.query.count()==0:
        db.session.add_all([
            Tier(name="Bronze",min_qualifying_spend=0,earning_rate=1.0),
            Tier(name="Silver",min_qualifying_spend=5000,earning_rate=1.25),
            Tier(name="Gold",min_qualifying_spend=15000,earning_rate=1.5),
            Tier(name="Platinum",min_qualifying_spend=30000,earning_rate=2.0)])
    if Rule.query.count()==0:
        db.session.add(Rule(name="Standard earning rule",points_per_currency=1,
            minimum_order_amount=100,expiry_days=365,effective_from=date.today(),active=True))
    if Reward.query.count()==0:
        db.session.add_all([
            Reward(id="RWD-0001",name="₹100 Voucher",points_cost=500),
            Reward(id="RWD-0002",name="₹250 Voucher",points_cost=1100),
            Reward(id="RWD-0003",name="Free Shipping",points_cost=200)])
    db.session.commit()
    flash("Database tables and default tiers, rule and rewards are ready.","success")
    return redirect(url_for("dashboard"))

@app.route("/health")
def health():
    try:
        db.session.execute(db.text("SELECT 1"))
        return {"status":"ok","database":"connected"}
    except Exception as e:
        return {"status":"error","message":str(e)},500

if __name__=="__main__":
    app.run(debug=True)
