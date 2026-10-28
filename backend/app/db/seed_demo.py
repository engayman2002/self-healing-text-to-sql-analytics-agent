"""Deterministic, idempotent E-Commerce & SaaS Analytics database seeder."""

from datetime import datetime, timedelta
import logging
import os
from pathlib import Path
import random
from typing import Optional

import sqlalchemy as sa
from sqlalchemy import create_engine, text

from app.core.config import get_settings
from app.core.security import encrypt_connection_uri, mask_connection_uri
from app.db.introspector import introspect_database
from app.db.manager import get_connection_manager

logger = logging.getLogger(__name__)


def get_demo_db_path() -> Path:
    """Resolve the absolute filesystem path for demo_ecommerce.db."""
    settings = get_settings()
    # Resolve relative to backend directory
    backend_dir = Path(__file__).resolve().parent.parent.parent
    return backend_dir / settings.DEMO_DB_FILENAME


def get_demo_db_uri(db_path: Optional[Path] = None) -> str:
    """Construct SQLite URI string for the demo database."""
    target_path = db_path or get_demo_db_path()
    # SQLite URI with absolute forward-slash path
    posix_path = str(target_path.resolve()).replace("\\", "/")
    return f"sqlite:///{posix_path}"


def seed_demo_database(custom_path: Optional[Path] = None, force_recreate: bool = False) -> Path:
    """Create and populate the 6-table E-Commerce Analytics SQLite database.

    Idempotent: Skips if database already exists with valid data unless force_recreate=True.
    """
    db_file = custom_path or get_demo_db_path()

    if db_file.exists() and not force_recreate:
        try:
            # Verify database has orders table and rows
            test_engine = create_engine(get_demo_db_uri(db_file), connect_args={"check_same_thread": False})
            with test_engine.connect() as conn:
                count = conn.execute(text("SELECT COUNT(*) FROM orders")).scalar()
                if count and count >= 50:
                    logger.info("Demo database '%s' already exists with %d orders.", db_file.name, count)
                    test_engine.dispose()
                    return db_file
            test_engine.dispose()
        except Exception:
            logger.info("Re-seeding incomplete or corrupted demo database...")

    logger.info("Seeding realistic E-Commerce Analytics database at '%s'...", db_file)
    db_file.parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(get_demo_db_uri(db_file), connect_args={"check_same_thread": False})

    # Deterministic pseudo-random seed so data is identical and repeatable
    rng = random.Random(42)

    with engine.begin() as conn:
        # Enable Foreign Key enforcement in SQLite
        conn.execute(text("PRAGMA foreign_keys = ON;"))

        # Drop existing tables cleanly
        conn.execute(text("DROP TABLE IF EXISTS order_items;"))
        conn.execute(text("DROP TABLE IF EXISTS orders;"))
        conn.execute(text("DROP TABLE IF EXISTS products;"))
        conn.execute(text("DROP TABLE IF EXISTS categories;"))
        conn.execute(text("DROP TABLE IF EXISTS customers;"))
        conn.execute(text("DROP TABLE IF EXISTS marketing_campaigns;"))

        # 1. Customers Table
        conn.execute(
            text(
                """
                CREATE TABLE customers (
                    customer_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    full_name TEXT NOT NULL,
                    email TEXT NOT NULL UNIQUE,
                    country TEXT NOT NULL,
                    segment TEXT NOT NULL CHECK(segment IN ('Enterprise', 'SMB', 'Consumer')),
                    signup_date TEXT NOT NULL
                );
                """
            )
        )

        # 2. Categories Table
        conn.execute(
            text(
                """
                CREATE TABLE categories (
                    category_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category_name TEXT NOT NULL UNIQUE,
                    department TEXT NOT NULL
                );
                """
            )
        )

        # 3. Products Table
        conn.execute(
            text(
                """
                CREATE TABLE products (
                    product_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_name TEXT NOT NULL,
                    category_id INTEGER NOT NULL REFERENCES categories(category_id),
                    unit_price DECIMAL(10, 2) NOT NULL,
                    cost_price DECIMAL(10, 2) NOT NULL,
                    stock_quantity INTEGER NOT NULL
                );
                """
            )
        )

        # 4. Orders Table
        conn.execute(
            text(
                """
                CREATE TABLE orders (
                    order_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    customer_id INTEGER NOT NULL REFERENCES customers(customer_id),
                    order_date TEXT NOT NULL,
                    order_status TEXT NOT NULL CHECK(order_status IN ('Completed', 'Shipped', 'Cancelled', 'Refunded')),
                    shipping_country TEXT NOT NULL,
                    discount_amount DECIMAL(10, 2) NOT NULL DEFAULT 0.00,
                    total_amount DECIMAL(10, 2) NOT NULL
                );
                """
            )
        )

        # 5. Order Items Table
        conn.execute(
            text(
                """
                CREATE TABLE order_items (
                    item_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id INTEGER NOT NULL REFERENCES orders(order_id),
                    product_id INTEGER NOT NULL REFERENCES products(product_id),
                    quantity INTEGER NOT NULL,
                    unit_price DECIMAL(10, 2) NOT NULL,
                    line_total DECIMAL(10, 2) NOT NULL
                );
                """
            )
        )

        # 6. Marketing Campaigns Table
        conn.execute(
            text(
                """
                CREATE TABLE marketing_campaigns (
                    campaign_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    campaign_name TEXT NOT NULL,
                    channel TEXT NOT NULL CHECK(channel IN ('Google Ads', 'LinkedIn', 'Email', 'Organic')),
                    budget_usd DECIMAL(10, 2) NOT NULL,
                    spend_usd DECIMAL(10, 2) NOT NULL,
                    conversions INTEGER NOT NULL,
                    start_date TEXT NOT NULL,
                    end_date TEXT NOT NULL
                );
                """
            )
        )

        # -------------------------------------------------------------------
        # Seed 1: Categories
        # -------------------------------------------------------------------
        category_records = [
            (1, "Enterprise SaaS", "Software Solutions"),
            (2, "Cloud Infrastructure", "Hosting & Compute"),
            (3, "Developer Productivity Tools", "Developer Tools"),
            (4, "Hardware & Data Center", "Hardware Equipment"),
            (5, "Professional Services", "Consulting & Training"),
        ]
        for cid, cname, dept in category_records:
            conn.execute(
                text("INSERT INTO categories VALUES (:cid, :cname, :dept)"),
                {"cid": cid, "cname": cname, "dept": dept},
            )

        # -------------------------------------------------------------------
        # Seed 2: Products (25 Products)
        # -------------------------------------------------------------------
        products_data = [
            (1, "Platform Analytics License (Annual)", 1, 12000.00, 2400.00, 100),
            (2, "Compliance & Security Suite", 1, 8500.00, 1700.00, 80),
            (3, "AI Agent Copilot Extension", 1, 4800.00, 960.00, 150),
            (4, "Workflow Automation Engine", 1, 3600.00, 720.00, 200),
            (5, "Single Sign-On (SSO) Module", 1, 1500.00, 300.00, 300),
            (6, "Dedicated Kubernetes Cluster", 2, 4500.00, 2200.00, 40),
            (7, "High-Throughput Read Replica", 2, 2800.00, 1400.00, 60),
            (8, "Serverless Compute Fleet", 2, 1900.00, 950.00, 120),
            (9, "Managed Redis Caching Tier", 2, 1200.00, 600.00, 180),
            (10, "Global Edge CDN Booster", 2, 850.00, 350.00, 250),
            (11, "CI/CD Pipeline Accelerator", 3, 2400.00, 480.00, 150),
            (12, "Code Quality & Vulnerability Scanner", 3, 1800.00, 360.00, 180),
            (13, "API Gateway & Testing Suite", 3, 1400.00, 280.00, 220),
            (14, "Distributed Tracing Agent", 3, 950.00, 190.00, 300),
            (15, "IDE Cloud Pairing Workspace", 3, 600.00, 120.00, 400),
            (16, "High-Density Rack Server", 4, 14500.00, 11000.00, 15),
            (17, "Managed Storage SAN Array", 4, 9800.00, 7400.00, 20),
            (18, "40GbE Top-of-Rack Switch", 4, 5200.00, 3900.00, 35),
            (19, "Hardware Security Module (HSM)", 4, 3800.00, 2850.00, 45),
            (20, "Redundant Enterprise UPS Unit", 4, 2600.00, 1950.00, 50),
            (21, "Architecture Design Review", 5, 15000.00, 6000.00, 10),
            (22, "Cloud Migration SOW", 5, 25000.00, 10000.00, 8),
            (23, "Full-Stack Security Audit", 5, 18000.00, 7200.00, 12),
            (24, "24/7 Dedicated SRE Support", 5, 6000.00, 2400.00, 30),
            (25, "Custom Integration Workshop", 5, 8000.00, 3200.00, 15),
        ]
        for pid, pname, cid, uprice, cprice, stock in products_data:
            conn.execute(
                text(
                    """
                    INSERT INTO products VALUES
                    (:pid, :pname, :cid, :uprice, :cprice, :stock)
                    """
                ),
                {
                    "pid": pid,
                    "pname": pname,
                    "cid": cid,
                    "uprice": uprice,
                    "cprice": cprice,
                    "stock": stock,
                },
            )

        # -------------------------------------------------------------------
        # Seed 3: Customers (48 Customers across global regions)
        # -------------------------------------------------------------------
        first_names = [
            "Alexander", "Sophia", "Marcus", "Elena", "Liam", "Olivia", "Noah",
            "Emma", "James", "Ava", "William", "Isabella", "Benjamin", "Mia",
            "Lucas", "Charlotte", "Henry", "Amelia", "Daniel", "Harper",
            "Matthew", "Evelyn", "David", "Abigail", "Joseph", "Emily",
            "Samuel", "Elizabeth", "Sebastian", "Sofia", "Jack", "Avery",
            "Owen", "Ella", "Theodore", "Scarlett", "Leo", "Grace",
            "Julian", "Chloe", "Christopher", "Victoria", "Gabriel", "Riley",
            "Anthony", "Aria", "Jaxon", "Lily",
        ]
        last_names = [
            "Vance", "Chen", "Sterling", "Kowalski", "Dubois", "Nakamura",
            "Thornton", "Mercer", "Al-Mansoor", "Silva", "Lindqvist", "Patel",
            "O'Connor", "Rossi", "Bauer", "Fischer", "Gomez", "Kim",
            "Schneider", "Larsen", "Mendoza", "Ivanov", "Santos", "Novak",
        ]
        countries = ["United States", "United Kingdom", "Germany", "Canada", "Australia", "France", "Japan"]
        segments = ["Enterprise", "SMB", "Consumer"]
        segment_weights = [0.25, 0.45, 0.30]

        start_date = datetime(2023, 1, 1)
        for i in range(1, 49):
            fname = first_names[i - 1]
            lname = last_names[(i * 3) % len(last_names)]
            full_name = f"{fname} {lname}"
            email = f"{fname.lower()}.{lname.lower()}{i}@example.com"
            country = rng.choice(countries)
            segment = rng.choices(segments, weights=segment_weights)[0]
            signup_dt = start_date + timedelta(days=rng.randint(0, 365))
            conn.execute(
                text(
                    """
                    INSERT INTO customers VALUES
                    (:cid, :name, :email, :country, :segment, :signup)
                    """
                ),
                {
                    "cid": i,
                    "name": full_name,
                    "email": email,
                    "country": country,
                    "segment": segment,
                    "signup": signup_dt.strftime("%Y-%m-%d"),
                },
            )

        # -------------------------------------------------------------------
        # Seed 4: Orders & Order Items (160 Realistic Orders over 12 Months)
        # -------------------------------------------------------------------
        order_statuses = ["Completed", "Shipped", "Cancelled", "Refunded"]
        status_weights = [0.75, 0.15, 0.06, 0.04]
        base_order_date = datetime(2024, 1, 1)

        item_id_counter = 1
        for order_id in range(1, 161):
            customer_id = rng.randint(1, 48)
            order_days_offset = rng.randint(0, 360)
            order_dt = base_order_date + timedelta(days=order_days_offset)
            status_val = rng.choices(order_statuses, weights=status_weights)[0]
            ship_country = rng.choice(countries)

            # Pick 1 to 4 distinct products for this order
            num_items = rng.randint(1, 4)
            chosen_products = rng.sample(products_data, num_items)

            subtotal = 0.0
            order_items_to_insert = []
            for p_tuple in chosen_products:
                pid, _, _, uprice, _, _ = p_tuple
                qty = rng.randint(1, 5)
                line_total = round(uprice * qty, 2)
                subtotal += line_total
                order_items_to_insert.append((item_id_counter, order_id, pid, qty, uprice, line_total))
                item_id_counter += 1

            # Discount logic
            discount = 0.0
            if subtotal > 10000.0:
                discount = round(subtotal * 0.10, 2)
            elif subtotal > 5000.0:
                discount = round(subtotal * 0.05, 2)

            total_amount = round(subtotal - discount, 2)

            conn.execute(
                text(
                    """
                    INSERT INTO orders VALUES
                    (:oid, :cid, :odate, :status, :scountry, :discount, :total)
                    """
                ),
                {
                    "oid": order_id,
                    "cid": customer_id,
                    "odate": order_dt.strftime("%Y-%m-%d"),
                    "status": status_val,
                    "scountry": ship_country,
                    "discount": discount,
                    "total": total_amount,
                },
            )

            for iid, oid, pid, qty, uprice, ltotal in order_items_to_insert:
                conn.execute(
                    text(
                        """
                        INSERT INTO order_items VALUES
                        (:iid, :oid, :pid, :qty, :uprice, :ltotal)
                        """
                    ),
                    {
                        "iid": iid,
                        "oid": oid,
                        "pid": pid,
                        "qty": qty,
                        "uprice": uprice,
                        "ltotal": ltotal,
                    },
                )

        # -------------------------------------------------------------------
        # Seed 5: Marketing Campaigns (12 Multi-Channel Campaigns)
        # -------------------------------------------------------------------
        campaigns_data = [
            (1, "Q1 Enterprise AI Cloud Launch", "Google Ads", 45000.00, 44200.00, 185, "2024-01-10", "2024-03-31"),
            (2, "Q1 SRE & DevOps Summit Sponsorship", "LinkedIn", 30000.00, 29800.00, 140, "2024-02-01", "2024-03-15"),
            (3, "Spring Cloud Migration Webinar Series", "Email", 12000.00, 11500.00, 210, "2024-03-01", "2024-04-15"),
            (4, "Developer Advocacy & Open Source Grants", "Organic", 25000.00, 23900.00, 320, "2024-01-01", "2024-06-30"),
            (5, "Q2 Kubernetes Cost Optimization Campaign", "Google Ads", 50000.00, 48500.00, 220, "2024-04-01", "2024-06-30"),
            (6, "B2B Executive CIO Roundtable", "LinkedIn", 35000.00, 34200.00, 95, "2024-05-01", "2024-06-15"),
            (7, "SOC2 & ISO27001 Security Blueprint Promo", "Email", 15000.00, 14800.00, 175, "2024-05-15", "2024-07-01"),
            (8, "Q3 Global Multi-Region Latency Benchmark", "Organic", 20000.00, 19200.00, 280, "2024-07-01", "2024-09-30"),
            (9, "Late Summer FinOps Cloud Efficiency", "Google Ads", 40000.00, 39600.00, 190, "2024-08-01", "2024-09-30"),
            (10, "Q4 Enterprise Budget Flush Discount Push", "LinkedIn", 60000.00, 58900.00, 260, "2024-10-01", "2024-12-15"),
            (11, "Black Friday Infrastructure Reserved Instance Deal", "Email", 22000.00, 21900.00, 340, "2024-11-15", "2024-12-05"),
            (12, "Year-End Enterprise Analytics Retrospective", "Organic", 18000.00, 17500.00, 240, "2024-11-01", "2024-12-31"),
        ]

        for cid, cname, ch, bud, sp, conv, sdate, edate in campaigns_data:
            conn.execute(
                text(
                    """
                    INSERT INTO marketing_campaigns VALUES
                    (:cid, :cname, :ch, :bud, :sp, :conv, :sdate, :edate)
                    """
                ),
                {
                    "cid": cid,
                    "cname": cname,
                    "ch": ch,
                    "bud": bud,
                    "sp": sp,
                    "conv": conv,
                    "sdate": sdate,
                    "edate": edate,
                },
            )

    engine.dispose()
    logger.info("Successfully seeded demo database '%s' with 6 tables and 160 orders.", db_file.name)
    return db_file


def register_demo_connection_if_needed() -> Optional[str]:
    """Auto-register demo_ecommerce.db in connection registry if no connections exist."""
    from app.api.connections import connection_store

    settings = get_settings()
    if not settings.AUTO_SEED_DEMO:
        return None

    # Check if connection store already has registered connections
    existing = connection_store.list_all()
    if len(existing) > 0:
        return existing[0]["id"]

    # Seed the database
    db_path = seed_demo_database()
    raw_uri = get_demo_db_uri(db_path)
    conn_id = "conn_demo_ecommerce"
    conn_name = "Demo E-Commerce Analytics (SQLite)"

    # Encrypt credentials
    encrypted_uri = encrypt_connection_uri(raw_uri)
    masked_uri = mask_connection_uri(raw_uri)

    # Register in engine manager
    manager = get_connection_manager()
    engine = manager.register_engine(conn_id, raw_uri)

    # Warm up schema introspection
    table_count = 6
    try:
        schema = introspect_database(engine, connection_id=conn_id, force_refresh=True)
        table_count = len(schema.tables)
    except Exception as exc:
        logger.warning("Error warming up demo schema: %s", exc)

    # Save in connection store
    connection_store.add(
        conn_id=conn_id,
        name=conn_name,
        dialect="sqlite",
        encrypted_uri=encrypted_uri,
        masked_uri=masked_uri,
        table_count=table_count,
    )

    logger.info("Auto-registered demo connection '%s' (%s)", conn_id, conn_name)
    return conn_id
