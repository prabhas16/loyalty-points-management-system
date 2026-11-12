import argparse
import json
import os
import sys
from pathlib import Path
from sqlalchemy.engine import URL

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


def main():
    parser = argparse.ArgumentParser(
        description="Generate deterministic synthetic loyalty data."
    )
    parser.add_argument("--customers", type=int, default=20_000)
    parser.add_argument("--orders", type=int, default=100_000)
    parser.add_argument("--transactions", type=int, default=300_000)
    parser.add_argument("--seed", type=int, default=20261112)
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument(
        "--app-database",
        action="store_true",
        help="Target the database configured for the Flask application instead of a benchmark database.",
    )
    parser.add_argument(
        "--append",
        action="store_true",
        help="Append a new dataset with non-colliding IDs; requires --app-database.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=PROJECT_ROOT / "benchmark" / "output" / "manifest.json",
    )
    args = parser.parse_args()
    load_dotenv()
    if args.app_database:
        if not args.append:
            parser.error("--app-database requires --append to preserve existing application data.")
        if not os.environ.get("DATABASE_URL") and not os.environ.get("DB_NAME"):
            parser.error("Configure DATABASE_URL or DB_NAME in the application's .env file first.")
    else:
        if args.append:
            parser.error("--append requires --app-database.")
        database_url = os.environ.get("BENCHMARK_DATABASE_URL")
        if not database_url and os.environ.get("BENCHMARK_DB_NAME"):
            database_url = URL.create(
                "mysql+pymysql",
                username=os.environ.get("BENCHMARK_DB_USER", "root"),
                password=os.environ.get("BENCHMARK_DB_PASSWORD", ""),
                host=os.environ.get("BENCHMARK_DB_HOST", "localhost"),
                port=int(os.environ.get("BENCHMARK_DB_PORT", "3306")),
                database=os.environ["BENCHMARK_DB_NAME"],
            ).render_as_string(hide_password=False)
        if not database_url:
            parser.error(
                "Set BENCHMARK_DATABASE_URL or BENCHMARK_DB_NAME to a dedicated empty benchmark database first."
            )
        os.environ["DATABASE_URL"] = database_url

    from benchmark.data_builder import generate_dataset
    from app import app

    with app.app_context():
        manifest = generate_dataset(
            customer_count=args.customers,
            order_count=args.orders,
            transaction_count=args.transactions,
            seed=args.seed,
            batch_size=args.batch_size,
            append=args.append,
        )
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "counts": manifest["counts"],
                "dataset_checksum": manifest["dataset_checksum"],
                "manifest": str(args.manifest),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
