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
- 50-row pagination on data lists and search-based customer, account and reward lookups.
- CSRF protection on state-changing forms.
- Account-level row locking for orders, returns, expiry and point redemption.
- Deterministic 20,000-customer / 100,000-order / 300,000-transaction benchmark generator.
- Five labelled injected anomalies with ground-truth output and reproducible SHA-256 checksums.
- Automated acceptance tests, including concurrent-redemption and full-scale dataset checks.

## 2. Requirements
- Python 3.10+
- MySQL 8+
- VS Code (recommended)

## 3. Installation (Windows / VS Code)
Open this folder in VS Code. In Terminal (PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
copy .env.example .env
```

Edit `.env` with your MySQL connection details and set `SECRET_KEY` to a random secret
(for example, generate one with `python -c "import secrets; print(secrets.token_hex(32))"`).
Do not commit `.env`. Set `SESSION_COOKIE_SECURE=true` when serving the application over HTTPS.

In MySQL Workbench, open `schema.sql` and execute it. It creates `loyalty_db`.

Then start the app:

```powershell
python app.py
```

Open `http://127.0.0.1:5000` and choose **Database setup** once to create tables and seed tiers, rules and rewards. The setup command applies an idempotent, additive migration to an existing supported loyalty schema and retains its tables and rows. This local-only version has no login or role-based access control; do not expose it to other machines or the public internet.

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
- ExpiryBatch 1:N PointsTransaction through `expiry_batch_id`.

## 8. Validation and production notes
- Unique constraints exist for all public codes and customer email.
- Foreign keys enforce parent-child integrity.
- Redemption locks the loyalty-account row before checking balance and debiting points; transaction code sequences are also locked when allocated.
- All state-changing forms, including login and logout, use CSRF protection.
- Expiry is idempotent because each run computes remaining balance per accrual lot.
- Return validation prevents returning more than the remaining order value.
- The app is an operational MVP, not a production-certified financial ledger. Before production, add immutable DB permissions/triggers, structured audit logs, backups, monitoring, and run concurrency acceptance tests against the production MySQL/InnoDB version.

## 9. Benchmark dataset and acceptance tests

The generator only writes to a database with no customer, account, order, ledger, redemption,
expiry-batch or snapshot rows. Use a dedicated benchmark database; it refuses to append to
existing datasets and never deletes existing rows.

Create an empty database named `loyalty_benchmark`, then set `BENCHMARK_DB_*` in your
ignored local `.env` file. Keep its database separate from the normal `DB_NAME`:

```powershell
python benchmark\generate_benchmark.py
```

The default run creates exactly 20,000 customers, 100,000 orders and 300,000 points
transactions. Use `--seed` to choose a repeatable seed. The JSON manifest records per-table
checksums, a dataset checksum and the five ground-truth anomaly cases from
`benchmark\anomaly_cases.json`. Re-run with the same seed against a fresh empty database to
compare manifests. The injected cases cover a balance snapshot mismatch, oversized
redemption, returned order without reversal, duplicate expiry and tier selection using gross
instead of qualifying spend. Generated manifests and bulk data are ignored by Git.

To append the same benchmark scale to the database configured for the Flask app without
replacing existing records, run:

```powershell
python benchmark\generate_benchmark.py --app-database --append
```

This appends 20,000 customers, 100,000 orders and 300,000 transactions using non-colliding
IDs. It uses the app's `DATABASE_URL` or `DB_*` settings and updates code sequences after
the import. Use this only for local testing.

Run the automated tests with:

```powershell
python -m pytest -q
```

The suite includes a full-scale count acceptance test and can take about a minute. It uses a
temporary SQLite database and does not connect to or alter the configured MySQL database.
