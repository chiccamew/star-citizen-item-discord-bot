import discord
from discord import app_commands, ui
from discord.ext import commands
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()

# --- CONFIGURATION ---
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL") # Connection string from Supabase
DASHBOARD_MESSAGE_ID = None # Stored in DB usually, but simplified here

# ⚠️ CRITICAL: Wrap these in int() because .env values are always text
try:
    WAREHOUSE_CHANNEL_ID = int(os.getenv("WAREHOUSE_CHANNEL_ID"))
    GUILD_ID = int(os.getenv("GUILD_ID"))
except (TypeError, ValueError):
    print("❌ ERROR: WAREHOUSE_CHANNEL_ID or GUILD_ID is missing or not a number in .env")
    exit(1)

MY_GUILD = discord.Object(id=GUILD_ID)

# --- SETUP ---
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# --- DATABASE HANDLER ---
async def get_db():
    return await asyncpg.connect(DATABASE_URL)

# --- LOGIC: CALCULATE STOCKS ---
async def get_project_status(project_name):
    """
    Calculates Direct Stock (Finished items) AND Potential Stock (Raw materials).
    """
    conn = await get_db()
    
    # 1. Get Requirements
    rows = await conn.fetch("""
        SELECT pr.item_name, pr.target_amount, 
               COALESCE(SUM(ui.quantity), 0) as direct_stock
        FROM project_requirements pr
        JOIN projects p ON pr.project_id = p.id
        LEFT JOIN user_inventory ui ON pr.item_name = ui.item_name
        WHERE p.name = $1
        GROUP BY pr.item_name, pr.target_amount
    """, project_name)
    
    status_report = []
    
    for row in rows:
        item = row['item_name']
        target = row['target_amount']
        direct = row['direct_stock']
        
        # 2. Check for "Potential" stock (Recipe logic)
        # Does this item have a recipe?
        recipe = await conn.fetchrow("""
            SELECT input_item_name, quantity_required 
            FROM recipes WHERE output_item_name = $1
        """, item)
        
        potential = 0
        if recipe:
            input_item = recipe['input_item_name']
            ratio = recipe['quantity_required']
            
            # Count total raw materials held by users
            raw_total = await conn.fetchval("""
                SELECT COALESCE(SUM(quantity), 0) FROM user_inventory 
                WHERE item_name = $1
            """, input_item)
            
            # Calculate how many we *could* make
            potential = int(raw_total // ratio)

        status_report.append({
            "item": item,
            "target": target,
            "direct": direct,
            "potential": potential
        })
        
    await conn.close()
    return status_report

# --- UI: THE BULK UPDATE MODAL ---
class InventoryModal(ui.Modal, title="Update Inventory"):
    inventory_input = ui.TextInput(
        label="Paste Inventory (Format: Item: Qty)",
        style=discord.TextStyle.paragraph,
        placeholder="Scrap: 500\nGold: 10\nQuantanium: 50",
        required=True,
        max_length=2000
    )

    async def on_submit(self, interaction: discord.Interaction):
        # Parse the text
        data = self.inventory_input.value
        lines = data.split('\n')
        
        conn = await get_db()
        user_id = interaction.user.id
        
        processed_items = []
        
        for line in lines:
            if ":" in line:
                item_name, qty_str = line.split(":", 1)
                item_name = item_name.strip()
                try:
                    qty = int(qty_str.strip())
                    
                    # Upsert (Insert or Update)
                    await conn.execute("""
                        INSERT INTO user_inventory (user_id, item_name, quantity)
                        VALUES ($1, $2, $3)
                        ON CONFLICT (user_id, item_name) 
                        DO UPDATE SET quantity = $3, last_updated = NOW()
                    """, user_id, item_name, qty)
                    
                    processed_items.append(f"{item_name}: {qty}")
                except ValueError:
                    continue # Skip bad lines

        await conn.close()
        
        # Trigger Dashboard Update
        await update_dashboard_message(interaction.guild)
        
        await interaction.response.send_message(
            f"✅ Updated {len(processed_items)} items in your ledger.", ephemeral=True
        )

# --- COMMANDS ---

@bot.tree.command(name="update_stock", description="Bulk update your inventory")
async def update_stock(interaction: discord.Interaction):
    await interaction.response.send_modal(InventoryModal())

@bot.tree.command(name="locate", description="Find who has a specific item")
async def locate(interaction: discord.Interaction, item_name: str):
    conn = await get_db()
    rows = await conn.fetch("""
        SELECT user_id, quantity FROM user_inventory 
        WHERE item_name = $1 AND quantity > 0
        ORDER BY quantity DESC LIMIT 5
    """, item_name)
    
    if not rows:
        await interaction.response.send_message(f"No {item_name} found in org.", ephemeral=True)
        return

    text = f"**📦 Stock Locator: {item_name}**\n"
    for row in rows:
        member = interaction.guild.get_member(row['user_id'])
        name = member.display_name if member else "Unknown"
        text += f"• **{name}**: {row['quantity']}\n"
        
    await conn.close()
    await interaction.response.send_message(text, ephemeral=True)

# --- DASHBOARD LOGIC ---
async def update_dashboard_message(guild):
    channel = guild.get_channel(WAREHOUSE_CHANNEL_ID)
    if not channel: return

    report = await get_project_status("Operation Idris")
    
    # Build the visual embed
    embed = discord.Embed(title="🚀 Operation Idris Progress", color=discord.Color.blue())
    
    for data in report:
        item = data['item']
        total_needed = data['target']
        direct = data['direct']
        potential = data['potential']
        total_ready = direct + potential
        
        percent = min(100, int((total_ready / total_needed) * 100))
        bar_length = 15
        filled = int((percent / 100) * bar_length)
        bar = "▓" * filled + "░" * (bar_length - filled)
        
        status_text = (
            f"`{bar}` **{percent}%**\n"
            f"• In Stock: **{direct}**\n"
        )
        
        if potential > 0:
            status_text += f"• Potential: **{potential}** (from raw mats)\n"
            
        status_text += f"• Goal: {total_needed}"
        
        embed.add_field(name=f"**{item}**", value=status_text, inline=False)
        
    embed.set_footer(text="Last Updated: Just now • Use /update_stock to contribute")

    # In a real bot, you fetch the existing message ID from DB to edit it.
    # For now, we just send a new one for testing.
    await channel.send(embed=embed)

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')
    # This copies the global commands to your specific server immediately
    bot.tree.copy_global_to(guild=MY_GUILD)
    await bot.tree.sync(guild=MY_GUILD)
    
    print(f"Commands synced to Guild ID: {MY_GUILD.id}")

bot.run(DISCORD_TOKEN)
