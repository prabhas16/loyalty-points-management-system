# Customer Loyalty Points Management System

A Flask + MySQL web application for managing customer loyalty accounts, orders, accruals, redemptions, returns/reversals, expiry and an auditable points ledger.

## 1. Features
- Dashboard KPIs and recent ledger activity.
- Customer registration with a one-to-one loyalty account.
- Order entry; eligible net spend determines points earned.
- Tier-based earning multipliers and qualifying-spend progression.
- Reward catalogue and points redemption with balance validation.
- Partial/full returns; proportional points reversals reference the original accrual.
- Lot-based FIFO redemption and expiry; expiry runs are idempotent.
- Searchable transaction ledger and CSV export.
- Reports by transaction type and tier.

## 2. Requirements
- Python 3.10+
- MySQL 8+
- VS Code (recommended)

## 3. Installation (Windows / VS Code)
Open this folder in VS Code. In Terminal (PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
copy .env.example .env
```

Edit `.env`. Replace `YOUR_MYSQL_PASSWORD` with your MySQL root password.

In MySQL Workbench, open `schema.sql` and execute it. It creates `loyalty_db`.

Then start the app:

```powershell
python app.py
```

Open `http://127.0.0.1:5000/setup` once to create tables and seed tiers, rules and rewards. For the existing loyalty database schema, this step applies an idempotent, additive migration: it retains existing tables and rows, maps the app to the existing column names, and adds only fields the app requires. It also creates a separate `expiry_batch_run` table; the existing `expirybatch` table is left unchanged. Then open `http://127.0.0.1:5000`.

## 4. Main workflow
1. Add a customer in Customers.
2. Create an order in Orders. The app calculates net spend and accrues points if the minimum order threshold is met.
3. Register returns in Returns. Points are reversed proportionally and linked to the source accrual.
4. Add rewards in Rewards.
5. Redeem points in Redeem. The app checks the live ledger balance and consumes oldest available accrual lots first.
6. Run Expiry using a date. Only unspent points in expired lots are debited. Repeating the same date does not expire those points twice.
7. Review Ledger and Reports; export the ledger as CSV.

## 5. IDs and ledger design
- Loyalty account: `LOY-<customer-id>` (zero-padded customer ID in the UI).
- Orders: `ORD-2026-000001`.
- Points transactions: `PTS-2026-00000001`.
- Redemptions: `RDM-2026-000001`.
- Expiry batches: `EXP-2026-000001`.

The points ledger is append-only through the UI: operations add new rows instead of editing or deleting old points transactions. `source_accrual_id` traces redemption, reversal and expiry debits to the accrual lot. The account balance is calculated as the sum of all ledger entries, not stored as a mutable balance.

## 6. Default business rules
- Bronze: 1.00x; Silver: 1.25x from ₹5,000; Gold: 1.50x from ₹15,000; Platinum: 2.00x from ₹30,000.
- Default rule: 1 point per ₹1 before tier multiplier; minimum eligible order ₹100; expiry after 365 days.
- Net spend = gross amount − discount amount.
- Points = floor(net spend × rule rate × tier multiplier).
- Tier progression uses qualifying net spend; returns reduce qualifying spend.
- Redemption consumes earliest-expiring/oldest accrual lots first (FIFO by creation date).

Change tier thresholds, rates and expiry policy to match the organisation's approved rules before production use.

## 7. Database relationships
- Customer 1:1 LoyaltyAccount.
- Tier 1:N LoyaltyAccount.
- Customer 1:N Order.
- Order 1:N OrderLine.
- LoyaltyAccount 1:N PointsTransaction.
- Order 1:N PointsTransaction (optional for non-order ledger events).
- PointsTransaction 1:N child transactions through `source_accrual_id`.
- LoyaltyAccount 1:N Redemption; Reward 1:N Redemption.
- ExpiryBatch 1:N conceptually through the transaction description in this starter version. For regulated production audit, add an explicit `expiry_batch_id` FK to PointsTransaction.

## 8. Validation and production notes
- Unique constraints exist for all public codes and customer email.
- Foreign keys enforce parent-child integrity.
- Redemption validates available balance before committing.
- Expiry is idempotent because each run computes remaining balance per accrual lot.
- Return validation prevents returning more than the remaining order value.
- The app is an operational MVP, not yet a production-certified financial ledger. Before production: add authentication/role-based permissions, CSRF protection, row-level locking or serializable isolation for concurrent redemptions, immutable DB triggers/permissions, structured audit logs, migrations, backups, monitoring, automated tests, and explicit expiry-batch linkage.
- The required 20,000 customer / 100,000 order / 300,000 transaction synthetic benchmark generator, labelled anomaly ground truth and deterministic checksum comparison are separate acceptance tasks; this UI MVP does not claim those are completed.
