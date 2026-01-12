-- 1. Where we store what items exist and if they have a recipe
CREATE TABLE items (
    id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    is_crafted BOOLEAN DEFAULT FALSE
);

-- 2. Where we define recipes (e.g., 24 Quantanium -> 1 Polaris Bit)
CREATE TABLE recipes (
    id SERIAL PRIMARY KEY,
    output_item_name TEXT REFERENCES items(name),
    input_item_name TEXT REFERENCES items(name),
    quantity_required INT NOT NULL
);

-- 3. The Projects (e.g., "Operation Idris")
CREATE TABLE projects (
    id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    status TEXT DEFAULT 'active' -- active, completed
);

-- 4. Project Requirements (What does "Operation Idris" need?)
CREATE TABLE project_requirements (
    project_id INT REFERENCES projects(id),
    item_name TEXT REFERENCES items(name),
    target_amount INT NOT NULL,
    PRIMARY KEY (project_id, item_name)
);

-- 5. User Inventory (The "Distributed Warehouse")
CREATE TABLE user_inventory (
    user_id BIGINT NOT NULL, -- Discord User ID
    item_name TEXT REFERENCES items(name),
    quantity INT NOT NULL DEFAULT 0,
    last_updated TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (user_id, item_name)
);
