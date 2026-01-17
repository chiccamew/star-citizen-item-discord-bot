import discord
from discord import app_commands, ui
from discord.ext import commands
import asyncpg
import os
from dotenv import load_dotenv
import math

load_dotenv()

# --- CONFIGURATION ---
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

try:
    WAREHOUSE_CHANNEL_ID = int(os.getenv("WAREHOUSE_CHANNEL_ID"))
    GUILD_ID = int(os.getenv("GUILD_ID"))
    OFFICER_ROLE_ID = int(os.getenv("OFFICER_ROLE_ID")) # <--- Loaded from .env
except (TypeError, ValueError):
    print("❌ ERROR: One of the ID variables (WAREHOUSE, GUILD, OFFICER) is missing or invalid in .env")
    exit(1)

MY_GUILD = discord.Object(id=GUILD_ID)

# --- SETUP ---
intents = discord.Intents.default()
intents.message_content = True 
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Global Database Pool
pool = None

# --- PERMISSION CHECKS ---
def is_officer():
    """
    Custom check: User must have 'Administrator' permission 
    OR have the specific OFFICER_ROLE_ID
    """
    def predicate(interaction: discord.Interaction) -> bool:
        # 1. Allow Server Admins always
        if interaction.user.guild_permissions.administrator:
            return True
            
        # 2. Check for Role ID
        return any(role.id == OFFICER_ROLE_ID for role in interaction.user.roles)
        
    return app_commands.check(predicate)

# --- DATABASE HELPERS ---
async def init_db_pool():
    global pool
    if pool is None:
        # statement_cache_size=0 tells asyncpg NOT to cache queries
        # This is REQUIRED for Supabase/PgBouncer
        pool = await asyncpg.create_pool(
            dsn=DATABASE_URL, 
            min_size=1, 
            max_size=10, 
            statement_cache_size=0
        )

async def item_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    """Suggests items from the database as you type."""
    try:
        # Use the global pool (Instant access)
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT name FROM items WHERE name ILIKE $1 LIMIT 25", f"%{current}%")
        
        return [app_commands.Choice(name=row['name'], value=row['name']) for row in rows]
    except Exception as e:
        print(f"⚠️ Autocomplete Error: {e}") # This will show in your console if it fails
        return []

async def project_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch("SELECT name FROM projects WHERE name ILIKE $1 LIMIT 25", f"%{current}%")
        return [app_commands.Choice(name=row['name'], value=row['name']) for row in rows]
    except Exception as e:
        print(f"⚠️ Project Autocomplete Error: {e}")
        return []

# --- MODAL: BULK UPDATE ---
async def update_dashboard_message(guild, project_name_hint=None):
    """
    Refreshes the pinned dashboard message.
    Note: We ignore 'project_name_hint' and fetch the *Active* project from DB to be safe.
    """
    async with pool.acquire() as conn:
        # 1. Get the saved config
        config = await conn.fetchrow("""
            SELECT sc.dashboard_channel_id, sc.dashboard_message_id, p.name as project_name
            FROM server_config sc
            JOIN projects p ON sc.active_project_id = p.id
            WHERE sc.guild_id = $1
        """, guild.id)
        
        if not config:
            return # No dashboard set up yet

        channel_id = config['dashboard_channel_id']
        message_id = config['dashboard_message_id']
        active_project = config['project_name']

    # 2. Get the Channel and Message objects
    channel = guild.get_channel(channel_id)
    if not channel: return

    try:
        message = await channel.fetch_message(message_id)
    except discord.NotFound:
        return # Message was deleted by a user

    # 3. Build new Embed data
    new_embed = await build_dashboard_embed(active_project)
    
    # 4. Edit the message
    if new_embed:
        await message.edit(embed=new_embed)

# --- MODALS ---

class InventoryModal(ui.Modal, title="Update Inventory"):
    inventory_input = ui.TextInput(
        label="Paste Inventory (Format: Item: Qty)",
        style=discord.TextStyle.paragraph,
        placeholder="Scrap: 500\nGold: 10\nQuantanium: 50",
        required=True,
        max_length=3000
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True) 
        
        data = self.inventory_input.value
        lines = data.split('\n')
        user_id = interaction.user.id
        
        updated_count = 0
        errors = []

        async with pool.acquire() as conn:
            for line in lines:
                if ":" in line:
                    try:
                        name_part, qty_part = line.split(":", 1)
                        item_name = name_part.strip()
                        qty = int(qty_part.strip().replace(',', '')) 

                        await conn.execute("INSERT INTO items (name) VALUES ($1) ON CONFLICT DO NOTHING", item_name)

                        await conn.execute("""
                            INSERT INTO user_inventory (user_id, item_name, quantity)
                            VALUES ($1, $2, $3)
                            ON CONFLICT (user_id, item_name) 
                            DO UPDATE SET quantity = $3, last_updated = NOW()
                        """, user_id, item_name, qty)
                        updated_count += 1
                    except Exception as e:
                        errors.append(f"Failed line '{line}': {e}")
        
        msg = f"✅ **Success:** **{interaction.user.display_name}** Updated {updated_count} items in their ledger."
        if errors:
            msg += "\n⚠️ **Errors:**\n" + "\n".join(errors[:5])
            
        await interaction.followup.send(msg)
        await update_dashboard_message(interaction.guild)
        # Check if active project exists before trying to update dashboard (Optional)
        # await update_dashboard_message(interaction.guild, "Operation Idris")

class WipeConfirmModal(ui.Modal, title="⚠️ CONFIRM WIPE"):
    confirmation = ui.TextInput(
        label="Type 'DELETE EVERYTHING' to confirm",
        style=discord.TextStyle.short,
        placeholder="DELETE EVERYTHING",
        required=True,
        max_length=20
    )

    async def on_submit(self, interaction: discord.Interaction):
        if self.confirmation.value != "DELETE EVERYTHING":
            await interaction.response.send_message("❌ Confirmation failed. Operation cancelled.", ephemeral=True)
            return
        
        await interaction.response.defer(ephemeral=True)
        
        async with pool.acquire() as conn:
            # We wipe ONLY the inventory, keeping recipes/projects intact
            await conn.execute("TRUNCATE TABLE user_inventory")
            
        await interaction.followup.send("💥 **System Wiped.** All user inventories have been cleared.", ephemeral=True)
        await update_dashboard_message(interaction.guild)

# --- MODAL FOR PROJECT BULK EDIT ---
class ProjectRequirementModal(ui.Modal, title="Bulk Edit Requirements"):
    # We need to know which project to edit. Since Modals can't take arguments directly 
    # from the command triggering them easily without subclassing, we pass it in __init__.
    
    def __init__(self, project_id, project_name):
        super().__init__()
        self.project_id = project_id
        self.project_name = project_name
        
    requirements_input = ui.TextInput(
        label="Paste Requirements (Format: Item: Qty)",
        style=discord.TextStyle.paragraph,
        placeholder="Scrap: 5000\nGold: 200",
        required=True,
        max_length=3000
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        data = self.requirements_input.value
        lines = data.split('\n')
        updated_count = 0
        errors = []

        async with pool.acquire() as conn:
            for line in lines:
                if ":" in line:
                    try:
                        name_part, qty_part = line.split(":", 1)
                        item_name = name_part.strip()
                        target_qty = int(qty_part.strip().replace(',', ''))

                        # 1. Ensure item exists
                        await conn.execute("INSERT INTO items (name) VALUES ($1) ON CONFLICT DO NOTHING", item_name)

                        # 2. Upsert Requirement
                        await conn.execute("""
                            INSERT INTO project_requirements (project_id, item_name, target_amount)
                            VALUES ($1, $2, $3)
                            ON CONFLICT (project_id, item_name) 
                            DO UPDATE SET target_amount = $3
                        """, self.project_id, item_name, target_qty)
                        
                        updated_count += 1
                    except Exception as e:
                        errors.append(f"Failed line '{line}': {e}")

        msg = f"✅ **Success:** Updated {updated_count} requirements for **{self.project_name}**."
        if errors:
            msg += "\n⚠️ **Errors:**\n" + "\n".join(errors[:5])
            
        await interaction.followup.send(msg, ephemeral=True)
        await update_dashboard_message(interaction.guild)

# --- COMMANDS: ADMIN & LOGISTICS (PROTECTED) ---

@bot.tree.command(name="wipe_all_user_stock", description="⚠️ NUCLEAR: Delete ALL user inventory data")
@is_officer() # <--- PROTECTED
async def wipe_all_user_stock(interaction: discord.Interaction):
    await interaction.response.send_modal(WipeConfirmModal())

@bot.tree.command(name="project_create", description="Start a new collection project")
@app_commands.describe(name="Name of the project (e.g. Operation Idris)")
@is_officer() # <--- PROTECTED
async def project_create(interaction: discord.Interaction, name: str):
    try:
        async with pool.acquire() as conn:
            await conn.execute("INSERT INTO projects (name) VALUES ($1)", name)
        await interaction.response.send_message(f"✅ Project **{name}** created.", ephemeral=True)
    except asyncpg.UniqueViolationError:
        await interaction.response.send_message(f"❌ Project **{name}** already exists.", ephemeral=True)

@bot.tree.command(name="project_add_item", description="Add a requirement to a project")
@app_commands.autocomplete(item_name=item_autocomplete, project_name=project_autocomplete)
@is_officer() # <--- PROTECTED
async def project_add_item(interaction: discord.Interaction, project_name: str, item_name: str, amount: int):
    async with pool.acquire() as conn:
        project_row = await conn.fetchrow("SELECT id FROM projects WHERE name = $1", project_name)
        
        if not project_row:
            await interaction.response.send_message(f"❌ Project **{project_name}** does not exist.", ephemeral=True)
            return
            
        project_id = project_row['id']
        await conn.execute("INSERT INTO items (name) VALUES ($1) ON CONFLICT DO NOTHING", item_name)
        
        await conn.execute("""
            INSERT INTO project_requirements (project_id, item_name, target_amount)
            VALUES ($1, $2, $3)
            ON CONFLICT (project_id, item_name) DO UPDATE SET target_amount = $3
        """, project_id, item_name, amount)
    
    await interaction.response.send_message(f"✅ Added **{amount}x {item_name}** to {project_name}.", ephemeral=True)

@bot.tree.command(name="project_item_export", description="Get a copy-paste list of current project requirements")
@app_commands.autocomplete(project_name=project_autocomplete)
@is_officer()
async def project_item_export(interaction: discord.Interaction, project_name: str):
    async with pool.acquire() as conn:
        # Verify project exists
        project = await conn.fetchrow("SELECT id FROM projects WHERE name = $1", project_name)
        if not project:
            await interaction.response.send_message(f"❌ Project **{project_name}** not found.", ephemeral=True)
            return

        rows = await conn.fetch("""
            SELECT item_name, target_amount 
            FROM project_requirements 
            WHERE project_id = $1 
            ORDER BY item_name
        """, project['id'])

    if not rows:
        await interaction.response.send_message(f"⚠️ Project **{project_name}** has no requirements yet.", ephemeral=True)
        return

    # Format specifically for the Bulk Edit modal
    export_text = ""
    for row in rows:
        export_text += f"{row['item_name']}: {row['target_amount']}\n"
    
    # Send inside a code block for easy copying
    await interaction.response.send_message(
        f"📋 **Export for {project_name}:**\nCopy the block below used in `/project_item_bulk_edit`", 
        ephemeral=True
    )
    await interaction.followup.send(f"```{export_text}```", ephemeral=True)


@bot.tree.command(name="project_item_bulk_edit", description="Bulk update/overwrite project requirements")
@app_commands.autocomplete(project_name=project_autocomplete)
@is_officer()
async def project_item_bulk_edit(interaction: discord.Interaction, project_name: str):
    # We need to fetch the ID first to pass it to the Modal
    async with pool.acquire() as conn:
        project = await conn.fetchrow("SELECT id FROM projects WHERE name = $1", project_name)
    
    if not project:
        await interaction.response.send_message(f"❌ Project **{project_name}** not found.", ephemeral=True)
        return

    # Pass ID and Name to the Modal
    await interaction.response.send_modal(ProjectRequirementModal(project_id=project['id'], project_name=project_name))

@bot.tree.command(name="recipe_add", description="Define how an item is crafted")
@app_commands.autocomplete(output_item=item_autocomplete, input_item=item_autocomplete)
@is_officer() # <--- PROTECTED
async def recipe_add(interaction: discord.Interaction, output_item: str, input_item: str, ratio: int):
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO items (name) VALUES ($1) ON CONFLICT DO NOTHING", output_item)
        await conn.execute("INSERT INTO items (name) VALUES ($1) ON CONFLICT DO NOTHING", input_item)
        
        await conn.execute("""
            INSERT INTO recipes (output_item_name, input_item_name, quantity_required)
            VALUES ($1, $2, $3)
        """, output_item, input_item, ratio)
    
    await interaction.response.send_message(f"✅ Recipe Saved: **{ratio} {input_item}** = 1 **{output_item}**", ephemeral=True)

@bot.tree.command(name="dashboard_set", description="Create/Reset the Live Dashboard for a specific project")
@app_commands.autocomplete(project_name=project_autocomplete)
@is_officer() # <--- PROTECTED
async def dashboard_set(interaction: discord.Interaction, project_name: str):
    # 1. DEFER IMMEDIATELY (Buys us 15 minutes)
    await interaction.response.defer(ephemeral=True)

    # 2. Verify Project Exists
    async with pool.acquire() as conn:
        project = await conn.fetchrow("SELECT id FROM projects WHERE name = $1", project_name)
        if not project:
            # Use followup instead of response
            await interaction.followup.send(f"❌ Project **{project_name}** not found.", ephemeral=True)
            return
        
        # 3. Build the initial Embed
        embed = await build_dashboard_embed(project_name)
        if not embed:
             await interaction.followup.send(f"❌ Project **{project_name}** has no requirements yet.", ephemeral=True)
             return

        # 4. Send the new Dashboard Message
        msg = await interaction.channel.send(embed=embed)
        
        # 5. Pin it
        try: await msg.pin()
        except: pass

        # 6. Save to DB
        await conn.execute("""
            INSERT INTO server_config (guild_id, dashboard_channel_id, dashboard_message_id, active_project_id)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (guild_id) 
            DO UPDATE SET 
                dashboard_channel_id = $2,
                dashboard_message_id = $3,
                active_project_id = $4
        """, interaction.guild.id, interaction.channel.id, msg.id, project['id'])

    # 7. Final Success Message (Use followup)
    await interaction.followup.send(f"✅ Dashboard set to **{project_name}**. It will auto-update.", ephemeral=True)

@bot.tree.command(name="admin_deposit", description="👮 Give items TO another user's inventory")
@app_commands.describe(target_user="Who gets the items?", item_name="Which item?", amount="How many?")
@app_commands.autocomplete(item_name=item_autocomplete)
@is_officer()
async def admin_deposit(interaction: discord.Interaction, target_user: discord.Member, item_name: str, amount: int):
    if amount <= 0:
        await interaction.response.send_message("❌ Amount must be positive.", ephemeral=True)
        return

    async with pool.acquire() as conn:
        # 1. Ensure item exists
        await conn.execute("INSERT INTO items (name) VALUES ($1) ON CONFLICT DO NOTHING", item_name)
        
        # 2. Add to TARGET USER'S stock (using target_user.id)
        await conn.execute("""
            INSERT INTO user_inventory (user_id, item_name, quantity)
            VALUES ($1, $2, $3)
            ON CONFLICT (user_id, item_name) 
            DO UPDATE SET quantity = user_inventory.quantity + $3, last_updated = NOW()
        """, target_user.id, item_name, amount)
        
        # 3. Get new personal total for that user
        new_personal = await conn.fetchval(
            "SELECT quantity FROM user_inventory WHERE user_id = $1 AND item_name = $2", 
            target_user.id, item_name
        )
        
        # 4. Get Global Total
        global_total = await conn.fetchval("SELECT SUM(quantity) FROM user_inventory WHERE item_name = $1", item_name)

    # 5. Public Announcement
    await interaction.response.send_message(
        f"👮 **Admin Action:** Deposited **{amount}** {item_name} into {target_user.mention}'s stash.\n"
        f"👤 **Their Total:** {new_personal}\n"
        f"🌍 **Global Stock:** {global_total}"
    )
    await update_dashboard_message(interaction.guild)

@bot.tree.command(name="admin_withdraw", description="👮 Remove items FROM another user's inventory")
@app_commands.describe(target_user="Who loses the items?", item_name="Which item?", amount="How many?")
@app_commands.autocomplete(item_name=item_autocomplete)
@is_officer()
async def admin_withdraw(interaction: discord.Interaction, target_user: discord.Member, item_name: str, amount: int):
    if amount <= 0:
        await interaction.response.send_message("❌ Amount must be positive.", ephemeral=True)
        return

    async with pool.acquire() as conn:
        # 1. Check target's current balance
        current_qty = await conn.fetchval("""
            SELECT quantity FROM user_inventory 
            WHERE user_id = $1 AND item_name = $2
        """, target_user.id, item_name)
        
        if current_qty is None or current_qty < amount:
            await interaction.response.send_message(
                f"❌ Cannot withdraw {amount}. {target_user.display_name} only has **{current_qty or 0}** {item_name}.", 
                ephemeral=True
            )
            return

        # 2. Perform withdrawal
        new_personal = current_qty - amount
        if new_personal == 0:
            await conn.execute("DELETE FROM user_inventory WHERE user_id = $1 AND item_name = $2", target_user.id, item_name)
        else:
            await conn.execute("""
                UPDATE user_inventory SET quantity = $3, last_updated = NOW()
                WHERE user_id = $1 AND item_name = $2
            """, target_user.id, item_name, new_personal)
            
        global_total = await conn.fetchval("SELECT SUM(quantity) FROM user_inventory WHERE item_name = $1", item_name) or 0

    await interaction.response.send_message(
        f"👮 **Admin Action:** Withdrew **{amount}** {item_name} from {target_user.mention}.\n"
        f"👤 **Their Remaining:** {new_personal}\n"
        f"🌍 **Global Stock:** {global_total}"
    )
    await update_dashboard_message(interaction.guild)

# --- COMMANDS: USER TOOLS (PUBLIC) ---

@bot.tree.command(name="deposit_item", description="Add items to your current stash (e.g. +50 Scrap)")
@app_commands.autocomplete(item_name=item_autocomplete)
async def deposit_item(interaction: discord.Interaction, item_name: str, amount: int):
    if amount <= 0:
        await interaction.response.send_message("❌ Amount must be positive.", ephemeral=True)
        return

    async with pool.acquire() as conn:
        # 1. Ensure item exists in DB registry
        await conn.execute("INSERT INTO items (name) VALUES ($1) ON CONFLICT DO NOTHING", item_name)
        
        # 2. Add to existing quantity (Upsert)
        await conn.execute("""
            INSERT INTO user_inventory (user_id, item_name, quantity)
            VALUES ($1, $2, $3)
            ON CONFLICT (user_id, item_name) 
            DO UPDATE SET quantity = user_inventory.quantity + $3, last_updated = NOW()
        """, interaction.user.id, item_name, amount)
        
        # 3. Get new total for confirmation
        new_total = await conn.fetchval(
            "SELECT quantity FROM user_inventory WHERE user_id = $1 AND item_name = $2", 
            interaction.user.id, item_name
        )

        global_total = await conn.fetchval(
            "SELECT SUM(quantity) FROM user_inventory WHERE item_name = $1", 
            item_name
        )

    await interaction.response.send_message(
        f"📦 **{interaction.user.display_name}** deposited **{amount}** {item_name}.\n"
        f"📦 **{interaction.user.display_name}** Total stock: **{new_total}**.\n"
        f"🌍 **Global Stock:** {global_total}"
    )
    await update_dashboard_message(interaction.guild)

@bot.tree.command(name="withdraw_item", description="Remove items from your stash (e.g. -50 Scrap)")
@app_commands.autocomplete(item_name=item_autocomplete)
async def withdraw_item(interaction: discord.Interaction, item_name: str, amount: int):
    if amount <= 0:
        await interaction.response.send_message("❌ Amount must be positive.", ephemeral=True)
        return

    async with pool.acquire() as conn:
        # 1. Check current balance
        current_qty = await conn.fetchval("""
            SELECT quantity FROM user_inventory 
            WHERE user_id = $1 AND item_name = $2
        """, interaction.user.id, item_name)
        
        if current_qty is None or current_qty < amount:
            await interaction.response.send_message(
                f"❌ You can't withdraw {amount}. You only have **{current_qty or 0}** {item_name}.", 
                ephemeral=True
            )
            return

        # 2. Perform withdrawal
        new_total = current_qty - amount
        if new_total == 0:
            # Optional: Delete row if 0 to keep DB clean, or just set to 0
            await conn.execute("DELETE FROM user_inventory WHERE user_id = $1 AND item_name = $2", interaction.user.id, item_name)
        else:
            await conn.execute("""
                UPDATE user_inventory SET quantity = $3, last_updated = NOW()
                WHERE user_id = $1 AND item_name = $2
            """, interaction.user.id, item_name, new_total)

        global_total = await conn.fetchval(
            "SELECT SUM(quantity) FROM user_inventory WHERE item_name = $1", 
            item_name
        )

    await interaction.response.send_message(
        f"� **{interaction.user.display_name}** withdrew **{amount}** {item_name}.\n"
        f"📦 **{interaction.user.display_name}** Total stock: **{new_total}**.\n"
        f"🌍 **Global Stock:** {global_total}"
    )
    await update_dashboard_message(interaction.guild)

@bot.tree.command(name="modify_item_qty", description="Set your EXACT stock (Overwrite old value)")
@app_commands.autocomplete(item_name=item_autocomplete)
async def modify_item_qty(interaction: discord.Interaction, item_name: str, quantity: int):
    if quantity < 0:
        await interaction.response.send_message("❌ Quantity cannot be negative.", ephemeral=True)
        return

    async with pool.acquire() as conn:
        # 1. Ensure item exists
        await conn.execute("INSERT INTO items (name) VALUES ($1) ON CONFLICT DO NOTHING", item_name)

        initial_total = await conn.fetchval(
            "SELECT quantity FROM user_inventory WHERE user_id = $1 AND item_name = $2", 
            interaction.user.id, item_name
        )

        if quantity == 0:
            # If setting to 0, just delete the row
            await conn.execute("DELETE FROM user_inventory WHERE user_id = $1 AND item_name = $2", interaction.user.id, item_name)
        else:
            # Upsert (Overwrite mode)
            await conn.execute("""
                INSERT INTO user_inventory (user_id, item_name, quantity)
                VALUES ($1, $2, $3)
                ON CONFLICT (user_id, item_name) 
                DO UPDATE SET quantity = $3, last_updated = NOW()
            """, interaction.user.id, item_name, quantity)

        global_total = await conn.fetchval(
            "SELECT SUM(quantity) FROM user_inventory WHERE item_name = $1", 
            item_name
        )

    await interaction.response.send_message(
        f"� **{interaction.user.display_name}** ✏️ Updated **{item_name}** from **{initial_total}** to **{quantity}**.\n"
        f"🌍 **Global Stock:** {global_total}"
    )
    await update_dashboard_message(interaction.guild)

@bot.tree.command(name="update_stock", description="Open the bulk inventory update form")
async def update_stock(interaction: discord.Interaction):
    await interaction.response.send_modal(InventoryModal())

@bot.tree.command(name="my_stock", description="View your personal inventory")
async def my_stock(interaction: discord.Interaction):
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT item_name, quantity FROM user_inventory WHERE user_id = $1 AND quantity > 0 ORDER BY item_name", interaction.user.id)
    
    if not rows:
        await interaction.response.send_message("You have no items registered. Use `/update_stock`!", ephemeral=True)
        return

    text = "**🎒 Your Ledger:**\n"
    for row in rows:
        text += f"• {row['item_name']}: {row['quantity']}\n"
    await interaction.response.send_message(text, ephemeral=True)

@bot.tree.command(name="my_stock_export", description="Get your current inventory in copy-paste format")
async def my_stock_export(interaction: discord.Interaction):
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT item_name, quantity 
            FROM user_inventory 
            WHERE user_id = $1 AND quantity > 0 
            ORDER BY item_name
        """, interaction.user.id)
    
    if not rows:
        await interaction.response.send_message("You have no items registered.", ephemeral=True)
        return

    export_text = ""
    for row in rows:
        export_text += f"{row['item_name']}: {row['quantity']}\n"

    await interaction.response.send_message(
        "📋 **Your Inventory Export:**\nCopy the block below to use in `/update_stock` or save as backup.", 
        ephemeral=True
    )
    await interaction.followup.send(f"```{export_text}```", ephemeral=True)

# --- COMMANDS: LOGISTICS & OFFICERS (PUBLIC) ---
# Note: Locate/Production/Status are public info, but you can protect them if you wish.
# Currently they are open to everyone.

@bot.tree.command(name="locate", description="Find who is holding a specific item")
@app_commands.autocomplete(item_name=item_autocomplete)
async def locate(interaction: discord.Interaction, item_name: str):
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT user_id, quantity FROM user_inventory 
            WHERE item_name = $1 AND quantity > 0 
            ORDER BY quantity DESC LIMIT 10
        """, item_name)
        total = await conn.fetchval("SELECT SUM(quantity) FROM user_inventory WHERE item_name = $1", item_name) or 0

    if not rows:
        await interaction.response.send_message(f"❌ No one has **{item_name}**.", ephemeral=True)
        return

    embed = discord.Embed(title=f"🔎 Stock Locator: {item_name}", description=f"**Global Total:** {total}", color=discord.Color.gold())
    
    list_text = ""
    for row in rows:
        user_id = row['user_id']
        qty = row['quantity']
        member = interaction.guild.get_member(user_id)
        if member is None:
            try:
                member = await interaction.guild.fetch_member(user_id)
            except discord.NotFound:
                member = None
        
        name = member.display_name if member else f"Unknown User ({user_id})"
        list_text += f"• **{name}**: {qty}\n"
        
    embed.add_field(name="Top Holders", value=list_text or "None")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="production", description="Check chain of production for a crafted item")
@app_commands.autocomplete(item_name=item_autocomplete)
async def production(interaction: discord.Interaction, item_name: str):
    async with pool.acquire() as conn:
        recipe = await conn.fetchrow("SELECT * FROM recipes WHERE output_item_name = $1", item_name)
        if not recipe:
            await interaction.response.send_message(f"⚠️ **{item_name}** has no recipe registered.", ephemeral=True)
            return

        input_item = recipe['input_item_name']
        ratio = recipe['quantity_required']
        
        holders = await conn.fetch("""
            SELECT user_id, quantity FROM user_inventory 
            WHERE item_name = $1 AND quantity >= $2
            ORDER BY quantity DESC LIMIT 10
        """, input_item, ratio)
    
    embed = discord.Embed(title=f"🏭 Production Chain: {item_name}", color=discord.Color.orange())
    embed.add_field(name="Recipe", value=f"Requires **{ratio}x {input_item}**", inline=False)
    
    if holders:
        text = ""
        for row in holders:
            member = interaction.guild.get_member(row['user_id'])
            if not member:
                try: member = await interaction.guild.fetch_member(row['user_id'])
                except: pass
            name = member.display_name if member else "Unknown"
            can_make = row['quantity'] // ratio
            text += f"• **{name}**: Has {row['quantity']} {input_item} (Can make **{can_make}**)\n"
        embed.add_field(name=f"Potential {item_name} Manufacturers", value=text, inline=False)
    else:
        embed.add_field(name="Status", value=f"❌ No one has enough {input_item}.", inline=False)

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="status", description="Show the main dashboard for a project")
@app_commands.autocomplete(project_name=project_autocomplete)
async def status(interaction: discord.Interaction, project_name: str):
    await interaction.response.defer()
    embed = await build_dashboard_embed(project_name)
    if embed:
        await interaction.followup.send(embed=embed)
    else:
        await interaction.followup.send(f"❌ Project **{project_name}** not found or empty.")

# --- HELP COMMAND ---

# --- HELP COMMAND ---

@bot.tree.command(name="help", description="Show guide on how to use this bot")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(title="📦 Logistics Bot Guide", description="Here are the available commands:", color=discord.Color.teal())
    
    embed.add_field(name="👤 For Members", value="""
    `/update_stock` - Paste your full inventory list.
    `/deposit_item` - Add items (e.g., +50 Scrap).
    `/withdraw_item` - Remove items (e.g., -10 Iron).
    `/my_stock` - View your personal stash.
    `/my_stock_export` - Get a copy-paste list of your stash.
    """, inline=False)
    
    embed.add_field(name="👮 For Officers", value="""
    `/status` - Check project progress.
    `/locate` - Find who has a specific item.
    `/production` - Check crafting potential (e.g. Quantanium -> Polaris Bits).
    """, inline=False)
    
    embed.add_field(name="🛠️ For Admins & Project Managers", value="""
    `/project_create` - Start a new project.
    `/project_add_item` - Add single requirement.
    `/project_item_export` - Copy full project requirements.
    `/project_item_bulk_edit` - Mass edit requirements.
    `/dashboard_set` - Create the Live Dashboard.
    `/wipe_all_user_stock` - ⚠️ Delete all user inventory.
    `/admin_deposit` - Give items to a user.
    `/admin_withdraw` - Take items from a user.
    """, inline=False)
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

# --- DASHBOARD ENGINE ---

async def build_dashboard_embed(project_name):
    async with pool.acquire() as conn:
        # 1. Fetch all requirements for this project
        reqs = await conn.fetch("""
            SELECT pr.item_name, pr.target_amount 
            FROM project_requirements pr
            JOIN projects p ON pr.project_id = p.id
            WHERE p.name = $1
        """, project_name)
        
        if not reqs: return None

        # 2. OPTIMIZATION: Create a lookup map { "MG Scripts": 50, ... }
        requirements_map = {row['item_name']: row['target_amount'] for row in reqs}

        embed = discord.Embed(title=f"🚀 Project Status: {project_name}", color=discord.Color.blue())
        
        # Track the project bottleneck (Lowest number of sets we can make)
        # Start with None (infinity)
        min_project_sets = None

        for req in reqs:
            item = req['item_name']
            target = req['target_amount']
            
            # Get Direct Stock (Finished items)
            direct = await conn.fetchval("SELECT COALESCE(SUM(quantity), 0) FROM user_inventory WHERE item_name = $1", item)
            
            # Get Potential Stock (Calculated from Surplus Ingredients)
            recipe = await conn.fetchrow("SELECT input_item_name, quantity_required FROM recipes WHERE output_item_name = $1", item)
            potential = 0
            input_item_name = None
            
            if recipe:
                input_item_name = recipe['input_item_name']
                ratio = recipe['quantity_required']
                
                # A. How much of the raw material do we have TOTAL?
                raw_total = await conn.fetchval("SELECT COALESCE(SUM(quantity), 0) FROM user_inventory WHERE item_name = $1", input_item_name)
                
                # B. Does the project ITSELF need this raw material directly?
                raw_needed_directly = requirements_map.get(input_item_name, 0)
                
                # C. Calculate Surplus
                surplus_raw = max(0, raw_total - raw_needed_directly)
                
                # D. Calculate potential from surplus only
                potential = surplus_raw // ratio
            
            # --- Visuals ---
            total_ready = direct + potential
            percent = min(100, int((total_ready / target) * 100))

            # --- Calculate Sets for this Item ---
            # e.g., if we have 500 Scrap and need 50, we have 10 sets of Scrap.
            if target > 0:
                current_item_sets = total_ready // target
                if min_project_sets is None or current_item_sets < min_project_sets:
                    min_project_sets = current_item_sets
            
            bar_len = 12
            filled_direct = min(bar_len, int((direct / target) * bar_len))
            remaining_space = bar_len - filled_direct
            filled_potential = min(remaining_space, int((potential / target) * bar_len))
            empty = bar_len - filled_direct - filled_potential
            
            bar = "▓" * filled_direct + "▒" * filled_potential + "░" * empty
            
            status_text = f"`{bar}` **{percent}%**\n"
            status_text += f"• **Ready:** {direct} / {target}\n"
            
            if potential > 0:
                status_text += f"• **Potential:** +{potential} (Craftable from {surplus_raw} excess {input_item_name})\n"
            elif recipe and potential == 0:
                 raw_total_debug = await conn.fetchval("SELECT COALESCE(SUM(quantity), 0) FROM user_inventory WHERE item_name = $1", input_item_name)
                 if raw_total_debug > 0:
                     status_text += f"• *Raw materials reserved for other requirements*\n"

            embed.add_field(name=item, value=status_text, inline=False)
            
        # Add the Sets Summary to the Description
        if min_project_sets is not None:
            embed.description = f"📦 **Available Sets:** You can complete this project **{min_project_sets}** times with current stock."
            
        embed.set_footer(text="Use /help to see all commands • ▓ = Ready, ▒ = Craftable")
        return embed

# --- ERROR HANDLER ---

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.CheckFailure):
        await interaction.response.send_message("⛔ **Access Denied:** You need the 'Logistics Officer' role to use this.", ephemeral=True)
    else:
        print(f"Command Error: {error}")
        if not interaction.response.is_done():
            await interaction.response.send_message("❌ An internal error occurred.", ephemeral=True)

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')
    await init_db_pool() # Initialize DB Pool here
    print('Database Pool Established')
    bot.tree.copy_global_to(guild=MY_GUILD)
    await bot.tree.sync(guild=MY_GUILD)
    print(f"Commands synced to Guild ID: {MY_GUILD.id}")

bot.run(DISCORD_TOKEN)