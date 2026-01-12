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
except (TypeError, ValueError):
    print("❌ ERROR: WAREHOUSE_CHANNEL_ID or GUILD_ID is missing in .env")
    exit(1)

MY_GUILD = discord.Object(id=GUILD_ID)

# --- SETUP ---
intents = discord.Intents.default()
intents.message_content = True 
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# --- DATABASE HELPERS ---
async def get_db():
    return await asyncpg.connect(DATABASE_URL)

async def item_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    """Suggests items from the database as you type."""
    conn = await get_db()
    rows = await conn.fetch("SELECT name FROM items WHERE name ILIKE $1 LIMIT 25", f"%{current}%")
    await conn.close()
    return [app_commands.Choice(name=row['name'], value=row['name']) for row in rows]

async def project_autocomplete(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    conn = await get_db()
    rows = await conn.fetch("SELECT name FROM projects WHERE name ILIKE $1 LIMIT 25", f"%{current}%")
    await conn.close()
    return [app_commands.Choice(name=row['name'], value=row['name']) for row in rows]

# --- MODAL: BULK UPDATE ---
class InventoryModal(ui.Modal, title="Update Inventory"):
    inventory_input = ui.TextInput(
        label="Paste Inventory (Format: Item: Qty)",
        style=discord.TextStyle.paragraph,
        placeholder="Scrap: 500\nGold: 10\nQuantanium: 50",
        required=True,
        max_length=3000
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True) # Give bot time to think
        
        data = self.inventory_input.value
        lines = data.split('\n')
        user_id = interaction.user.id
        conn = await get_db()
        
        updated_count = 0
        errors = []

        for line in lines:
            if ":" in line:
                try:
                    name_part, qty_part = line.split(":", 1)
                    item_name = name_part.strip()
                    qty = int(qty_part.strip().replace(',', '')) # Handle "1,000"

                    # 1. Ensure item exists
                    await conn.execute("INSERT INTO items (name) VALUES ($1) ON CONFLICT DO NOTHING", item_name)

                    # 2. Update User Stock
                    await conn.execute("""
                        INSERT INTO user_inventory (user_id, item_name, quantity)
                        VALUES ($1, $2, $3)
                        ON CONFLICT (user_id, item_name) 
                        DO UPDATE SET quantity = $3, last_updated = NOW()
                    """, user_id, item_name, qty)
                    updated_count += 1
                except Exception as e:
                    errors.append(f"Failed line '{line}': {e}")
        
        await conn.close()
        
        msg = f"✅ **Success:** Updated {updated_count} items in your ledger."
        if errors:
            msg += "\n⚠️ **Errors:**\n" + "\n".join(errors[:5])
            
        await interaction.followup.send(msg, ephemeral=True)
        
        # Auto-refresh the main project dashboard if it exists
        await update_dashboard_message(interaction.guild, "Operation Idris")

# --- COMMANDS: SETUP & ADMIN ---

@bot.tree.command(name="project_create", description="Start a new collection project")
@app_commands.describe(name="Name of the project (e.g. Operation Idris)")
async def project_create(interaction: discord.Interaction, name: str):
    conn = await get_db()
    try:
        await conn.execute("INSERT INTO projects (name) VALUES ($1)", name)
        await interaction.response.send_message(f"✅ Project **{name}** created.", ephemeral=True)
    except asyncpg.UniqueViolationError:
        await interaction.response.send_message(f"❌ Project **{name}** already exists.", ephemeral=True)
    finally:
        await conn.close()

@bot.tree.command(name="project_add_item", description="Add a requirement to a project")
@app_commands.autocomplete(item_name=item_autocomplete, project_name=project_autocomplete)
async def project_add_item(interaction: discord.Interaction, project_name: str, item_name: str, amount: int):
    conn = await get_db()
    
    # 1. Get the Project ID first (Crucial Fix)
    project_row = await conn.fetchrow("SELECT id FROM projects WHERE name = $1", project_name)
    
    if not project_row:
        await conn.close()
        await interaction.response.send_message(f"❌ Project **{project_name}** does not exist. Create it first!", ephemeral=True)
        return
        
    project_id = project_row['id']

    # 2. Ensure item exists
    await conn.execute("INSERT INTO items (name) VALUES ($1) ON CONFLICT DO NOTHING", item_name)
    
    # 3. Insert using the ID
    await conn.execute("""
        INSERT INTO project_requirements (project_id, item_name, target_amount)
        VALUES ($1, $2, $3)
        ON CONFLICT (project_id, item_name) DO UPDATE SET target_amount = $3
    """, project_id, item_name, amount)
    
    await conn.close()
    await interaction.response.send_message(f"✅ Added **{amount}x {item_name}** to {project_name}.", ephemeral=True)

@bot.tree.command(name="recipe_add", description="Define how an item is crafted (e.g. 24 Quantanium -> 1 Polaris Bit)")
@app_commands.autocomplete(output_item=item_autocomplete, input_item=item_autocomplete)
async def recipe_add(interaction: discord.Interaction, output_item: str, input_item: str, ratio: int):
    conn = await get_db()
    # Ensure items exist
    await conn.execute("INSERT INTO items (name) VALUES ($1) ON CONFLICT DO NOTHING", output_item)
    await conn.execute("INSERT INTO items (name) VALUES ($1) ON CONFLICT DO NOTHING", input_item)
    
    await conn.execute("""
        INSERT INTO recipes (output_item_name, input_item_name, quantity_required)
        VALUES ($1, $2, $3)
    """, output_item, input_item, ratio)
    
    await conn.close()
    await interaction.response.send_message(f"✅ Recipe Saved: **{ratio} {input_item}** = 1 **{output_item}**", ephemeral=True)

# --- COMMANDS: USER TOOLS ---

@bot.tree.command(name="update_stock", description="Open the bulk inventory update form")
async def update_stock(interaction: discord.Interaction):
    await interaction.response.send_modal(InventoryModal())

@bot.tree.command(name="my_stock", description="View your personal inventory")
async def my_stock(interaction: discord.Interaction):
    conn = await get_db()
    rows = await conn.fetch("SELECT item_name, quantity FROM user_inventory WHERE user_id = $1 AND quantity > 0 ORDER BY item_name", interaction.user.id)
    await conn.close()
    
    if not rows:
        await interaction.response.send_message("You have no items registered. Use `/update_stock`!", ephemeral=True)
        return

    text = "**🎒 Your Ledger:**\n"
    for row in rows:
        text += f"• {row['item_name']}: {row['quantity']}\n"
    await interaction.response.send_message(text, ephemeral=True)

# --- COMMANDS: LOGISTICS & OFFICERS ---

@bot.tree.command(name="locate", description="Find who is holding a specific item")
@app_commands.autocomplete(item_name=item_autocomplete)
async def locate(interaction: discord.Interaction, item_name: str):
    conn = await get_db()
    
    # 1. Get the raw data
    rows = await conn.fetch("""
        SELECT user_id, quantity FROM user_inventory 
        WHERE item_name = $1 AND quantity > 0 
        ORDER BY quantity DESC LIMIT 10
    """, item_name)
    
    total = await conn.fetchval("SELECT SUM(quantity) FROM user_inventory WHERE item_name = $1", item_name) or 0
    await conn.close()

    if not rows:
        await interaction.response.send_message(f"❌ No one has **{item_name}**.", ephemeral=True)
        return

    embed = discord.Embed(title=f"🔎 Stock Locator: {item_name}", description=f"**Global Total:** {total}", color=discord.Color.gold())
    
    list_text = ""
    for row in rows:
        user_id = row['user_id']
        qty = row['quantity']
        
        # 2. Try to get member from cache
        member = interaction.guild.get_member(user_id)
        
        # 3. Fallback: If cache misses (member is None), fetch from API
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
    conn = await get_db()
    
    # 1. Check if it has a recipe
    recipe = await conn.fetchrow("SELECT * FROM recipes WHERE output_item_name = $1", item_name)
    
    if not recipe:
        await conn.close()
        await interaction.response.send_message(f"⚠️ **{item_name}** has no recipe registered.", ephemeral=True)
        return

    input_item = recipe['input_item_name']
    ratio = recipe['quantity_required']
    
    # 2. Who has the raw material?
    holders = await conn.fetch("""
        SELECT user_id, quantity FROM user_inventory 
        WHERE item_name = $1 AND quantity >= $2
        ORDER BY quantity DESC LIMIT 10
    """, input_item, ratio) # Only show people who have enough to make at least 1
    
    await conn.close()
    
    embed = discord.Embed(title=f"🏭 Production Chain: {item_name}", color=discord.Color.orange())
    embed.add_field(name="Recipe", value=f"Requires **{ratio}x {input_item}**", inline=False)
    
    if holders:
        text = ""
        for row in holders:
            member = interaction.guild.get_member(row['user_id'])
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

# --- DASHBOARD ENGINE ---

async def build_dashboard_embed(project_name):
    conn = await get_db()
    
    # FIX: Join 'projects' table to filter by name, but select from 'project_requirements'
    reqs = await conn.fetch("""
        SELECT pr.item_name, pr.target_amount 
        FROM project_requirements pr
        JOIN projects p ON pr.project_id = p.id
        WHERE p.name = $1
    """, project_name)
    
    if not reqs:
        await conn.close()
        return None

    embed = discord.Embed(title=f"🚀 Project Status: {project_name}", color=discord.Color.blue())
    
    for req in reqs:
        item = req['item_name']
        target = req['target_amount']
        
        # 1. Get Direct Stock
        direct = await conn.fetchval("SELECT COALESCE(SUM(quantity), 0) FROM user_inventory WHERE item_name = $1", item)
        
        # 2. Get Potential Stock (if recipe exists)
        recipe = await conn.fetchrow("SELECT input_item_name, quantity_required FROM recipes WHERE output_item_name = $1", item)
        potential = 0
        input_item_name = None
        
        if recipe:
            input_item_name = recipe['input_item_name']
            ratio = recipe['quantity_required']
            raw_total = await conn.fetchval("SELECT COALESCE(SUM(quantity), 0) FROM user_inventory WHERE item_name = $1", input_item_name)
            potential = raw_total // ratio
        
        # Visuals
        total_ready = direct + potential
        percent = min(100, int((total_ready / target) * 100))
        
        # Progress Bar
        bar_len = 12
        filled_direct = min(bar_len, int((direct / target) * bar_len))
        # Don't let potential bar exceed the remaining space
        remaining_space = bar_len - filled_direct
        filled_potential = min(remaining_space, int((potential / target) * bar_len))
        empty = bar_len - filled_direct - filled_potential
        
        bar = "▓" * filled_direct + "▒" * filled_potential + "░" * empty
        
        status_text = f"`{bar}` **{percent}%**\n"
        status_text += f"• **Ready:** {direct} / {target}\n"
        
        if potential > 0:
            status_text += f"• **Potential:** {potential} (from {input_item_name})\n"
            
        embed.add_field(name=item, value=status_text, inline=False)
        
    embed.set_footer(text="Use /update_stock to contribute • ▓ = Ready, ▒ = Craftable")
    await conn.close()
    return embed

async def update_dashboard_message(guild, project_name):
    """Updates the pinned message in the warehouse channel (If we were tracking a specific Message ID)"""
    # For this version, we won't auto-edit a specific message ID unless we store it in DB.
    # But this function is ready to be expanded.
    pass

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')
    bot.tree.copy_global_to(guild=MY_GUILD)
    await bot.tree.sync(guild=MY_GUILD)
    print(f"Commands synced to Guild ID: {MY_GUILD.id}")

bot.run(DISCORD_TOKEN)