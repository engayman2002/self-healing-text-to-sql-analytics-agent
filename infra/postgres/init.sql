-- PostgreSQL Initialization Script for Demo E-Commerce Analytics Database
-- Executed automatically on first start of postgres-demo container

CREATE TABLE IF NOT EXISTS categories (
    category_id SERIAL PRIMARY KEY,
    category_name VARCHAR(100) NOT NULL UNIQUE,
    department VARCHAR(100) NOT NULL
);

CREATE TABLE IF NOT EXISTS customers (
    customer_id SERIAL PRIMARY KEY,
    full_name VARCHAR(150) NOT NULL,
    email VARCHAR(150) NOT NULL UNIQUE,
    country VARCHAR(100) NOT NULL,
    segment VARCHAR(50) NOT NULL CHECK(segment IN ('Enterprise', 'SMB', 'Consumer')),
    signup_date DATE NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
    product_id SERIAL PRIMARY KEY,
    product_name VARCHAR(150) NOT NULL,
    category_id INT NOT NULL REFERENCES categories(category_id) ON DELETE CASCADE,
    unit_price NUMERIC(10, 2) NOT NULL,
    cost_price NUMERIC(10, 2) NOT NULL,
    stock_quantity INT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    order_id SERIAL PRIMARY KEY,
    customer_id INT NOT NULL REFERENCES customers(customer_id) ON DELETE CASCADE,
    order_date DATE NOT NULL,
    order_status VARCHAR(50) NOT NULL CHECK(order_status IN ('Completed', 'Shipped', 'Cancelled', 'Refunded')),
    shipping_country VARCHAR(100) NOT NULL,
    discount_amount NUMERIC(10, 2) NOT NULL DEFAULT 0.00,
    total_amount NUMERIC(10, 2) NOT NULL
);

CREATE TABLE IF NOT EXISTS order_items (
    item_id SERIAL PRIMARY KEY,
    order_id INT NOT NULL REFERENCES orders(order_id) ON DELETE CASCADE,
    product_id INT NOT NULL REFERENCES products(product_id) ON DELETE CASCADE,
    quantity INT NOT NULL,
    unit_price NUMERIC(10, 2) NOT NULL,
    line_total NUMERIC(10, 2) NOT NULL
);

CREATE TABLE IF NOT EXISTS marketing_campaigns (
    campaign_id SERIAL PRIMARY KEY,
    campaign_name VARCHAR(150) NOT NULL,
    channel VARCHAR(50) NOT NULL CHECK(channel IN ('Google Ads', 'LinkedIn', 'Email', 'Organic')),
    budget_usd NUMERIC(10, 2) NOT NULL,
    spend_usd NUMERIC(10, 2) NOT NULL,
    conversions INT NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL
);

-- Seed Categories
INSERT INTO categories (category_id, category_name, department) VALUES
(1, 'Enterprise SaaS', 'Software Solutions'),
(2, 'Cloud Infrastructure', 'Hosting & Compute'),
(3, 'Developer Productivity Tools', 'Developer Tools'),
(4, 'Hardware & Data Center', 'Hardware Equipment'),
(5, 'Professional Services', 'Consulting & Training')
ON CONFLICT (category_id) DO NOTHING;

-- Seed Products
INSERT INTO products (product_id, product_name, category_id, unit_price, cost_price, stock_quantity) VALUES
(1, 'Platform Analytics License (Annual)', 1, 12000.00, 2400.00, 100),
(2, 'Compliance & Security Suite', 1, 8500.00, 1700.00, 80),
(3, 'AI Agent Copilot Extension', 1, 4800.00, 960.00, 150),
(4, 'Workflow Automation Engine', 1, 3600.00, 720.00, 200),
(5, 'Single Sign-On (SSO) Module', 1, 1500.00, 300.00, 300),
(6, 'Dedicated Kubernetes Cluster', 2, 4500.00, 2200.00, 40),
(7, 'High-Throughput Read Replica', 2, 2800.00, 1400.00, 60),
(8, 'Serverless Compute Fleet', 2, 1900.00, 950.00, 120),
(9, 'Managed Redis Caching Tier', 2, 1200.00, 600.00, 180),
(10, 'Global Edge CDN Booster', 2, 850.00, 350.00, 250),
(11, 'CI/CD Pipeline Accelerator', 3, 2400.00, 480.00, 150),
(12, 'Code Quality & Vulnerability Scanner', 3, 1800.00, 360.00, 180),
(13, 'API Gateway & Testing Suite', 3, 1400.00, 280.00, 220),
(14, 'Distributed Tracing Agent', 3, 950.00, 190.00, 300),
(15, 'IDE Cloud Pairing Workspace', 3, 600.00, 120.00, 400),
(16, 'High-Density Rack Server', 4, 14500.00, 11000.00, 15),
(17, 'Managed Storage SAN Array', 4, 9800.00, 7400.00, 20),
(18, '40GbE Top-of-Rack Switch', 4, 5200.00, 3900.00, 35),
(19, 'Hardware Security Module (HSM)', 4, 3800.00, 2850.00, 45),
(20, 'Redundant Enterprise UPS Unit', 4, 2600.00, 1950.00, 50),
(21, 'Architecture Design Review', 5, 15000.00, 6000.00, 10),
(22, 'Cloud Migration SOW', 5, 25000.00, 10000.00, 8),
(23, 'Full-Stack Security Audit', 5, 18000.00, 7200.00, 12),
(24, '24/7 Dedicated SRE Support', 5, 6000.00, 2400.00, 30),
(25, 'Custom Integration Workshop', 5, 8000.00, 3200.00, 15)
ON CONFLICT (product_id) DO NOTHING;

-- Seed Customers Sample
INSERT INTO customers (customer_id, full_name, email, country, segment, signup_date) VALUES
(1, 'Alexander Vance', 'alexander.vance1@example.com', 'United States', 'Enterprise', '2023-02-14'),
(2, 'Sophia Chen', 'sophia.chen2@example.com', 'Canada', 'Enterprise', '2023-03-22'),
(3, 'Marcus Sterling', 'marcus.sterling3@example.com', 'United Kingdom', 'SMB', '2023-01-08'),
(4, 'Elena Kowalski', 'elena.kowalski4@example.com', 'Germany', 'Consumer', '2023-05-19'),
(5, 'Liam Dubois', 'liam.dubois5@example.com', 'France', 'Enterprise', '2023-06-11'),
(6, 'Olivia Nakamura', 'olivia.nakamura6@example.com', 'Japan', 'SMB', '2023-07-04'),
(7, 'Noah Thornton', 'noah.thornton7@example.com', 'Australia', 'Enterprise', '2023-08-30'),
(8, 'Emma Mercer', 'emma.mercer8@example.com', 'United States', 'Consumer', '2023-09-15'),
(9, 'James Al-Mansoor', 'james.al-mansoor9@example.com', 'United Kingdom', 'SMB', '2023-04-12'),
(10, 'Ava Silva', 'ava.silva10@example.com', 'Germany', 'Enterprise', '2023-11-03')
ON CONFLICT (customer_id) DO NOTHING;

-- Seed Orders Sample
INSERT INTO orders (order_id, customer_id, order_date, order_status, shipping_country, discount_amount, total_amount) VALUES
(1, 1, '2024-01-15', 'Completed', 'United States', 1200.00, 10800.00),
(2, 2, '2024-02-20', 'Completed', 'Canada', 0.00, 4800.00),
(3, 3, '2024-03-10', 'Completed', 'United Kingdom', 0.00, 2400.00),
(4, 1, '2024-04-05', 'Completed', 'United States', 2500.00, 22500.00),
(5, 5, '2024-05-12', 'Completed', 'France', 500.00, 8000.00),
(6, 6, '2024-06-18', 'Completed', 'Japan', 0.00, 3600.00),
(7, 7, '2024-07-22', 'Completed', 'Australia', 1800.00, 16200.00),
(8, 9, '2024-08-14', 'Completed', 'United Kingdom', 0.00, 4500.00),
(9, 2, '2024-09-09', 'Completed', 'Canada', 850.00, 7650.00),
(10, 10, '2024-10-30', 'Completed', 'Germany', 1500.00, 13500.00)
ON CONFLICT (order_id) DO NOTHING;

-- Seed Order Items Sample
INSERT INTO order_items (item_id, order_id, product_id, quantity, unit_price, line_total) VALUES
(1, 1, 1, 1, 12000.00, 12000.00),
(2, 2, 3, 1, 4800.00, 4800.00),
(3, 3, 11, 1, 2400.00, 2400.00),
(4, 4, 22, 1, 25000.00, 25000.00),
(5, 5, 2, 1, 8500.00, 8500.00),
(6, 6, 4, 1, 3600.00, 3600.00),
(7, 7, 23, 1, 18000.00, 18000.00),
(8, 8, 6, 1, 4500.00, 4500.00),
(9, 9, 2, 1, 8500.00, 8500.00),
(10, 10, 21, 1, 15000.00, 15000.00)
ON CONFLICT (item_id) DO NOTHING;

-- Seed Marketing Campaigns
INSERT INTO marketing_campaigns (campaign_id, campaign_name, channel, budget_usd, spend_usd, conversions, start_date, end_date) VALUES
(1, 'Q1 Enterprise AI Cloud Launch', 'Google Ads', 45000.00, 44200.00, 185, '2024-01-10', '2024-03-31'),
(2, 'Q1 SRE & DevOps Summit Sponsorship', 'LinkedIn', 30000.00, 29800.00, 140, '2024-02-01', '2024-03-15'),
(3, 'Spring Cloud Migration Webinar Series', 'Email', 12000.00, 11500.00, 210, '2024-03-01', '2024-04-15'),
(4, 'Developer Advocacy & Open Source Grants', 'Organic', 25000.00, 23900.00, 320, '2024-01-01', '2024-06-30'),
(5, 'Q2 Kubernetes Cost Optimization Campaign', 'Google Ads', 50000.00, 48500.00, 220, '2024-04-01', '2024-06-30')
ON CONFLICT (campaign_id) DO NOTHING;
