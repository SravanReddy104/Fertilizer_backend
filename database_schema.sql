-- Fertilizer Shop Dashboard Database Schema
-- Run this in your Supabase SQL editor

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Products table
CREATE TABLE products (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    type VARCHAR(50) NOT NULL CHECK (type IN ('fertilizer', 'pesticide', 'seed')),
    brand VARCHAR(255) NOT NULL,
    unit VARCHAR(50) NOT NULL,
    price_per_unit DECIMAL(10,2) NOT NULL,
    stock_quantity DECIMAL(10,2) NOT NULL DEFAULT 0,
    minimum_stock DECIMAL(10,2) NOT NULL DEFAULT 0,
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Sales table
CREATE TABLE sales (
    id SERIAL PRIMARY KEY,
    customer_name VARCHAR(255) NOT NULL,
    customer_phone VARCHAR(20),
    customer_address TEXT,
    total_amount DECIMAL(10,2) NOT NULL,
    paid_amount DECIMAL(10,2) NOT NULL DEFAULT 0,
    payment_status VARCHAR(20) NOT NULL CHECK (payment_status IN ('paid', 'pending', 'partial', 'overdue')),
    notes TEXT,
    sale_date TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Sale items table
CREATE TABLE sale_items (
    id SERIAL PRIMARY KEY,
    sale_id INTEGER REFERENCES sales(id) ON DELETE CASCADE,
    product_id INTEGER REFERENCES products(id) ON DELETE RESTRICT,
    quantity DECIMAL(10,2) NOT NULL,
    unit_price DECIMAL(10,2) NOT NULL,
    total_price DECIMAL(10,2) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Purchases table
CREATE TABLE purchases (
    id SERIAL PRIMARY KEY,
    supplier_name VARCHAR(255) NOT NULL,
    supplier_phone VARCHAR(20),
    supplier_address TEXT,
    total_amount DECIMAL(10,2) NOT NULL,
    paid_amount DECIMAL(10,2) NOT NULL DEFAULT 0,
    payment_status VARCHAR(20) NOT NULL CHECK (payment_status IN ('paid', 'pending', 'partial', 'overdue')),
    notes TEXT,
    purchase_date TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Purchase items table
CREATE TABLE purchase_items (
    id SERIAL PRIMARY KEY,
    purchase_id INTEGER REFERENCES purchases(id) ON DELETE CASCADE,
    product_id INTEGER REFERENCES products(id) ON DELETE RESTRICT,
    quantity DECIMAL(10,2) NOT NULL,
    unit_price DECIMAL(10,2) NOT NULL,
    total_price DECIMAL(10,2) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Debts table
CREATE TABLE debts (
    id SERIAL PRIMARY KEY,
    customer_name VARCHAR(255) NOT NULL,
    customer_phone VARCHAR(20),
    amount DECIMAL(10,2) NOT NULL,
    description TEXT NOT NULL,
    due_date DATE,
    status VARCHAR(20) NOT NULL CHECK (status IN ('paid', 'pending', 'partial', 'overdue')),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Function to update stock
CREATE OR REPLACE FUNCTION update_product_stock(product_id INTEGER, quantity_change DECIMAL)
RETURNS VOID AS $$
BEGIN
    UPDATE products 
    SET stock_quantity = stock_quantity + quantity_change,
        updated_at = NOW()
    WHERE id = product_id;
END;
$$ LANGUAGE plpgsql;

-- Trigger to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply triggers
CREATE TRIGGER update_products_updated_at BEFORE UPDATE ON products
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_sales_updated_at BEFORE UPDATE ON sales
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_purchases_updated_at BEFORE UPDATE ON purchases
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_debts_updated_at BEFORE UPDATE ON debts
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- Indexes for better performance
CREATE INDEX idx_products_type ON products(type);
CREATE INDEX idx_products_stock ON products(stock_quantity);
CREATE INDEX idx_sales_date ON sales(sale_date);
CREATE INDEX idx_sales_customer ON sales(customer_name);
CREATE INDEX idx_sales_status ON sales(payment_status);
CREATE INDEX idx_purchases_date ON purchases(purchase_date);
CREATE INDEX idx_purchases_supplier ON purchases(supplier_name);
CREATE INDEX idx_purchases_status ON purchases(payment_status);
CREATE INDEX idx_debts_customer ON debts(customer_name);
CREATE INDEX idx_debts_status ON debts(status);
CREATE INDEX idx_debts_due_date ON debts(due_date);

-- Sample data
INSERT INTO products (name, type, brand, unit, price_per_unit, stock_quantity, minimum_stock, description) VALUES
('NPK 20-20-20', 'fertilizer', 'Yara', 'kg', 45.00, 500, 50, 'Balanced NPK fertilizer for all crops'),
('Urea 46%', 'fertilizer', 'IFFCO', 'kg', 25.00, 1000, 100, 'High nitrogen fertilizer'),
('DAP', 'fertilizer', 'Coromandel', 'kg', 35.00, 750, 75, 'Di-ammonium phosphate'),
('Chlorpyrifos 20% EC', 'pesticide', 'Bayer', 'liter', 120.00, 200, 20, 'Broad spectrum insecticide'),
('Glyphosate 41% SL', 'pesticide', 'Monsanto', 'liter', 180.00, 150, 15, 'Non-selective herbicide'),
('Tomato Seeds F1', 'seed', 'Syngenta', 'packet', 450.00, 100, 10, 'Hybrid tomato seeds'),
('Wheat Seeds HD-2967', 'seed', 'IARI', 'kg', 35.00, 2000, 200, 'High yielding wheat variety'),
('Rice Seeds Basmati', 'seed', 'Punjab Seeds', 'kg', 85.00, 500, 50, 'Premium basmati rice seeds');

-- Sample sales
INSERT INTO sales (customer_name, customer_phone, customer_address, total_amount, paid_amount, payment_status, notes) VALUES
('Rajesh Kumar', '9876543210', 'Village Rampur, District Meerut', 2250.00, 2250.00, 'paid', 'Regular customer'),
('Suresh Sharma', '9876543211', 'Village Kashipur, District Haridwar', 1800.00, 1000.00, 'partial', 'Partial payment received'),
('Mahesh Singh', '9876543212', 'Village Roorkee, District Haridwar', 3200.00, 0.00, 'pending', 'Will pay next week');

-- Sample sale items
INSERT INTO sale_items (sale_id, product_id, quantity, unit_price, total_price) VALUES
(1, 1, 25, 45.00, 1125.00),
(1, 2, 45, 25.00, 1125.00),
(2, 3, 30, 35.00, 1050.00),
(2, 4, 5, 120.00, 600.00),
(2, 5, 1, 180.00, 180.00),
(3, 6, 4, 450.00, 1800.00),
(3, 7, 40, 35.00, 1400.00);

-- Sample purchases
INSERT INTO purchases (supplier_name, supplier_phone, supplier_address, total_amount, paid_amount, payment_status, notes) VALUES
('Yara India Ltd', '011-12345678', 'Gurgaon, Haryana', 22500.00, 22500.00, 'paid', 'Monthly stock purchase'),
('IFFCO Distributor', '011-87654321', 'Delhi', 25000.00, 20000.00, 'partial', 'Balance to be paid');

-- Sample purchase items
INSERT INTO purchase_items (purchase_id, product_id, quantity, unit_price, total_price) VALUES
(1, 1, 500, 40.00, 20000.00),
(1, 4, 20, 100.00, 2000.00),
(1, 5, 3, 150.00, 450.00),
(2, 2, 1000, 22.00, 22000.00),
(2, 3, 100, 30.00, 3000.00);

-- Sample debts
INSERT INTO debts (customer_name, customer_phone, amount, description, due_date, status) VALUES
('Ramesh Gupta', '9876543213', 5000.00, 'Fertilizer purchase - to be paid after harvest', '2024-04-15', 'pending'),
('Dinesh Yadav', '9876543214', 2500.00, 'Seeds and pesticide purchase', '2024-03-30', 'overdue'),
('Vikash Kumar', '9876543215', 1200.00, 'NPK fertilizer purchase', '2024-04-10', 'pending');

-- =========================
-- Authentication & Sessions
-- =========================

-- Users table
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) UNIQUE NOT NULL,
    hashed_password TEXT NOT NULL,
    full_name VARCHAR(255),
    role VARCHAR(20) NOT NULL DEFAULT 'user' CHECK (role IN ('user','admin')),
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Refresh tokens table (session management)
CREATE TABLE IF NOT EXISTS refresh_tokens (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    jti TEXT NOT NULL UNIQUE,
    revoked BOOLEAN NOT NULL DEFAULT false,
    expires_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_active ON users(is_active);
CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user ON refresh_tokens(user_id);
