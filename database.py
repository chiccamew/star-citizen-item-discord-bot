import asyncpg
import logging

# Set up a logger for database errors
logger = logging.getLogger("Database")

class DatabaseManager:
    """
    Handles all interactions with the Supabase PostgreSQL database.
    """
    def __init__(self, pool: asyncpg.Pool):
        self.pool = pool

    # --- HELPER: Resolve Name to ID ---
    async def get_or_create_item_id(self, conn, item_name: str) -> int:
        """
        Helper to get an Item ID. If the item doesn't exist, it creates it.
        NOTE: Expects an open connection (conn) to be passed in.
        """
        # We use an 'upsert' pattern here that guarantees an ID is returned
        return await conn.fetchval("""
            INSERT INTO items (name) VALUES ($1) 
            ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name 
            RETURNING id
        """, item_name)

    async def get_item_id_by_name(self, item_name: str) -> int:
        """Read-only lookup. Returns None if not found."""
        async with self.pool.acquire() as conn:
            return await conn.fetchval("SELECT id FROM items WHERE name = $1", item_name)

    # --- USER INVENTORY ---
    async def update_user_stock(self, user_id: int, item_name: str, quantity: int):
        """Used by /deposit_item and bulk update."""
        async with self.pool.acquire() as conn:
            item_id = await self.get_or_create_item_id(conn, item_name)
            await conn.execute("""
                INSERT INTO user_inventory (user_id, item_id, quantity)
                VALUES ($1, $2, $3)
                ON CONFLICT (user_id, item_id) 
                DO UPDATE SET quantity = user_inventory.quantity + $3, last_updated = NOW()
            """, user_id, item_id, quantity)

    async def set_user_stock(self, user_id: int, item_name: str, quantity: int):
        """Used by /modify_item_qty (overwrites value)."""
        async with self.pool.acquire() as conn:
            item_id = await self.get_or_create_item_id(conn, item_name)
            if quantity == 0:
                await conn.execute("DELETE FROM user_inventory WHERE user_id = $1 AND item_id = $2", user_id, item_id)
            else:
                await conn.execute("""
                    INSERT INTO user_inventory (user_id, item_id, quantity)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (user_id, item_id) 
                    DO UPDATE SET quantity = $3, last_updated = NOW()
                """, user_id, item_id, quantity)
                
    async def withdraw_user_stock(self, user_id: int, item_name: str, amount: int) -> tuple[int, int]:
        """
        Returns (new_user_balance, new_global_total).
        Raises ValueError if insufficient funds.
        """
        async with self.pool.acquire() as conn:
            # 1. Get ID (Strict, don't create)
            item_id = await conn.fetchval("SELECT id FROM items WHERE name = $1", item_name)
            if not item_id:
                raise ValueError(f"Item '{item_name}' does not exist.")

            # 2. Check Balance
            current_qty = await conn.fetchval("""
                SELECT quantity FROM user_inventory WHERE user_id = $1 AND item_id = $2
            """, user_id, item_id)
            
            if current_qty is None or current_qty < amount:
                raise ValueError(f"Insufficient funds. You have {current_qty or 0}.")

            # 3. Withdraw
            new_qty = current_qty - amount
            if new_qty == 0:
                await conn.execute("DELETE FROM user_inventory WHERE user_id = $1 AND item_id = $2", user_id, item_id)
            else:
                await conn.execute("""
                    UPDATE user_inventory SET quantity = $3, last_updated = NOW()
                    WHERE user_id = $1 AND item_id = $2
                """, user_id, item_id, new_qty)

            # 4. Get Global Total
            global_total = await conn.fetchval("SELECT SUM(quantity) FROM user_inventory WHERE item_id = $1", item_id) or 0
            
            return new_qty, global_total

    async def get_user_inventory(self, user_id: int):
        """Returns list of records {item_name, quantity}"""
        async with self.pool.acquire() as conn:
            return await conn.fetch("""
                SELECT i.name as item_name, ui.quantity 
                FROM user_inventory ui
                JOIN items i ON ui.item_id = i.id
                WHERE ui.user_id = $1 AND ui.quantity > 0 
                ORDER BY i.name
            """, user_id)
            
    async def wipe_all_inventory(self):
        async with self.pool.acquire() as conn:
            await conn.execute("TRUNCATE TABLE user_inventory")

    # --- LOOKUPS & TOTALS ---
    async def get_global_total(self, item_name: str) -> int:
        async with self.pool.acquire() as conn:
            return await conn.fetchval("""
                SELECT COALESCE(SUM(ui.quantity), 0) 
                FROM user_inventory ui
                JOIN items i ON ui.item_id = i.id
                WHERE i.name = $1
            """, item_name)

    async def get_top_holders(self, item_name: str, limit: int = 10):
        async with self.pool.acquire() as conn:
            return await conn.fetch("""
                SELECT ui.user_id, ui.quantity 
                FROM user_inventory ui
                JOIN items i ON ui.item_id = i.id
                WHERE i.name = $1 AND ui.quantity > 0 
                ORDER BY ui.quantity DESC LIMIT $2
            """, item_name, limit)

    async def item_autocomplete(self, current: str):
        async with self.pool.acquire() as conn:
            return await conn.fetch("SELECT name FROM items WHERE name ILIKE $1 LIMIT 25", f"%{current}%")
        
    async def get_user_items_autocomplete(self, user_id: int, current: str):
        """Finds items ONLY in a specific user's inventory."""
        async with self.pool.acquire() as conn:
            return await conn.fetch("""
                SELECT i.name 
                FROM user_inventory ui
                JOIN items i ON ui.item_id = i.id
                WHERE ui.user_id = $1 AND ui.quantity > 0 AND i.name ILIKE $2
                ORDER BY i.name ASC
                LIMIT 25
            """, user_id, f"%{current}%")
        
    # --- PROJECTS & RECIPES ---
    async def create_project(self, name: str):
        async with self.pool.acquire() as conn:
            await conn.execute("INSERT INTO projects (name) VALUES ($1)", name)

    async def project_autocomplete(self, current: str):
        async with self.pool.acquire() as conn:
            return await conn.fetch("SELECT name FROM projects WHERE name ILIKE $1 LIMIT 25", f"%{current}%")

    async def add_project_requirement(self, project_name: str, item_name: str, amount: int):
        async with self.pool.acquire() as conn:
            project = await conn.fetchrow("SELECT id FROM projects WHERE name = $1", project_name)
            if not project:
                raise ValueError(f"Project '{project_name}' not found.")
            
            item_id = await self.get_or_create_item_id(conn, item_name)
            
            await conn.execute("""
                INSERT INTO project_requirements (project_id, item_id, target_amount)
                VALUES ($1, $2, $3)
                ON CONFLICT (project_id, item_id) DO UPDATE SET target_amount = $3
            """, project['id'], item_id, amount)

    async def get_project_requirements(self, project_name: str):
        async with self.pool.acquire() as conn:
            return await conn.fetch("""
                SELECT i.name as item_name, pr.target_amount 
                FROM project_requirements pr
                JOIN projects p ON pr.project_id = p.id
                JOIN items i ON pr.item_id = i.id
                WHERE p.name = $1 
                ORDER BY i.name
            """, project_name)

    async def add_recipe(self, output_item: str, input_item: str, ratio: int):
        async with self.pool.acquire() as conn:
            out_id = await self.get_or_create_item_id(conn, output_item)
            in_id = await self.get_or_create_item_id(conn, input_item)
            
            await conn.execute("""
                INSERT INTO recipes (output_item_id, input_item_id, quantity_required)
                VALUES ($1, $2, $3)
            """, out_id, in_id, ratio)
            
    async def get_recipe(self, output_item_name: str):
        async with self.pool.acquire() as conn:
             return await conn.fetchrow("""
                SELECT input_i.name as input_item_name, r.quantity_required
                FROM recipes r
                JOIN items output_i ON r.output_item_id = output_i.id
                JOIN items input_i ON r.input_item_id = input_i.id
                WHERE output_i.name = $1
            """, output_item_name)

    # --- DASHBOARD CONFIG ---
    async def set_dashboard_config(self, guild_id: int, channel_id: int, message_id: int, project_name: str):
        async with self.pool.acquire() as conn:
            project = await conn.fetchrow("SELECT id FROM projects WHERE name = $1", project_name)
            if not project:
                raise ValueError("Project not found")
                
            await conn.execute("""
                INSERT INTO server_config (guild_id, dashboard_channel_id, dashboard_message_id, active_project_id)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (guild_id) 
                DO UPDATE SET 
                    dashboard_channel_id = $2,
                    dashboard_message_id = $3,
                    active_project_id = $4
            """, guild_id, channel_id, message_id, project['id'])

    async def get_dashboard_config(self, guild_id: int):
        async with self.pool.acquire() as conn:
            return await conn.fetchrow("""
                SELECT sc.dashboard_channel_id, sc.dashboard_message_id, p.name as project_name
                FROM server_config sc
                JOIN projects p ON sc.active_project_id = p.id
                WHERE sc.guild_id = $1
            """, guild_id)