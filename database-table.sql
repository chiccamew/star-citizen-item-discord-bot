-- 1. Where we store what items exist and if they have a recipe
CREATE TABLE IF NOT EXISTS items (
    id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    is_crafted BOOLEAN DEFAULT FALSE
);

-- 2. Where we define recipes (e.g., 24 Quantanium -> 1 Polaris Bit)
CREATE TABLE IF NOT EXISTS recipes (
    id SERIAL PRIMARY KEY,
    output_item_name TEXT REFERENCES items(name),
    input_item_name TEXT REFERENCES items(name),
    quantity_required INT NOT NULL
);

-- 3. The Projects (e.g., "Operation Idris")
CREATE TABLE IF NOT EXISTS rojects (
    id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    status TEXT DEFAULT 'active' -- active, completed
);

-- 4. Project Requirements (What does "Operation Idris" need?)
CREATE TABLE IF NOT EXISTS project_requirements (
    project_id INT REFERENCES projects(id),
    item_name TEXT REFERENCES items(name),
    target_amount INT NOT NULL,
    PRIMARY KEY (project_id, item_name)
);

-- 5. User Inventory (The "Distributed Warehouse")
CREATE TABLE IF NOT EXISTS user_inventory (
    user_id BIGINT NOT NULL, -- Discord User ID
    item_name TEXT REFERENCES items(name),
    quantity INT NOT NULL DEFAULT 0,
    last_updated TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (user_id, item_name)
);

-- 6. Server Configuration (e.g., which channel to post updates in)
CREATE TABLE IF NOT EXISTS server_config (
    guild_id BIGINT PRIMARY KEY,
    dashboard_channel_id BIGINT,
    dashboard_message_id BIGINT,
    active_project_id INT REFERENCES projects(id)
);

-- Secure the supabase tables
ALTER TABLE items ENABLE ROW LEVEL SECURITY;
ALTER TABLE recipes ENABLE ROW LEVEL SECURITY;
ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE project_requirements ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_inventory ENABLE ROW LEVEL SECURITY;
ALTER TABLE server_config ENABLE ROW LEVEL SECURITY;

CREATE TABLE items_backup AS SELECT * FROM user_inventory;
CREATE TABLE recipes_backup AS SELECT * FROM recipes;
CREATE TABLE projects_backup AS SELECT * FROM projects;
CREATE TABLE project_requirements_backup AS SELECT * FROM project_requirements;
CREATE TABLE user_inventory_backup AS SELECT * FROM user_inventory;
CREATE TABLE server_config_backup AS SELECT * FROM server_config;

BEGIN;

-- 1. MIGRATE RECIPES
-- Add new ID columns
ALTER TABLE recipes ADD COLUMN output_item_id INT REFERENCES items(id);
ALTER TABLE recipes ADD COLUMN input_item_id INT REFERENCES items(id);

-- Populate them by looking up the IDs based on the names
UPDATE recipes r SET output_item_id = i.id FROM items i WHERE r.output_item_name = i.name;
UPDATE recipes r SET input_item_id = i.id FROM items i WHERE r.input_item_name = i.name;

-- Enforce that they cannot be empty
ALTER TABLE recipes ALTER COLUMN output_item_id SET NOT NULL;
ALTER TABLE recipes ALTER COLUMN input_item_id SET NOT NULL;

-- 2. MIGRATE PROJECT REQUIREMENTS
ALTER TABLE project_requirements ADD COLUMN item_id INT REFERENCES items(id);

UPDATE project_requirements pr SET item_id = i.id FROM items i WHERE pr.item_name = i.name;

ALTER TABLE project_requirements ALTER COLUMN item_id SET NOT NULL;

-- Update the Primary Key
ALTER TABLE project_requirements DROP CONSTRAINT project_requirements_pkey;
ALTER TABLE project_requirements ADD PRIMARY KEY (project_id, item_id);


-- 3. MIGRATE USER INVENTORY
ALTER TABLE user_inventory ADD COLUMN item_id INT REFERENCES items(id);

UPDATE user_inventory ui SET item_id = i.id FROM items i WHERE ui.item_name = i.name;

ALTER TABLE user_inventory ALTER COLUMN item_id SET NOT NULL;

-- Update the Primary Key
ALTER TABLE user_inventory DROP CONSTRAINT user_inventory_pkey;
ALTER TABLE user_inventory ADD PRIMARY KEY (user_id, item_id);

COMMIT;

BEGIN;
-- Drop the old text columns
ALTER TABLE recipes DROP COLUMN output_item_name;
ALTER TABLE recipes DROP COLUMN input_item_name;
ALTER TABLE project_requirements DROP COLUMN item_name;
ALTER TABLE user_inventory DROP COLUMN item_name;

COMMIT;