import discord
from discord.ext import commands
from discord import app_commands
from src.utils import item_autocomplete, update_dashboard_message
from src.ui.modals import InventoryModal

class Members(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # --- HELP COMMAND ---
    @app_commands.command(name="help", description="Show guide on how to use this bot")
    async def help_command(self, interaction: discord.Interaction):
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
        `/production` - Check crafting potential.
        """, inline=False)
        
        embed.add_field(name="🛠️ For Admins & Project Managers", value="""
        `/project_create` - Start a new project.
        `/project_add_item` - Add single requirement.
        `/project_item_export` - Copy full project requirements.
        `/project_item_bulk_edit` - Mass edit requirements.
        `/recipe_add` - Define crafting recipes.
        `/dashboard_set` - Create the Live Dashboard.
        `/wipe_all_user_stock` - ⚠️ Delete all user inventory.
        `/admin_deposit` - Give items to a user.
        `/admin_withdraw` - Take items from a user.
        """, inline=False)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # --- USER TOOLS ---
    @app_commands.command(name="update_stock", description="Open the bulk inventory update form")
    async def update_stock(self, interaction: discord.Interaction):
        await interaction.response.send_modal(InventoryModal())

    @app_commands.command(name="my_stock", description="View your personal inventory")
    async def my_stock(self, interaction: discord.Interaction):
        rows = await self.bot.db.get_user_inventory(interaction.user.id)
        if not rows: 
            await interaction.response.send_message("You have no items registered. Use `/update_stock`!", ephemeral=True)
            return
        
        text = "**🎒 Your Ledger:**\n" + "\n".join([f"• {r['item_name']}: {r['quantity']}" for r in rows])
        await interaction.response.send_message(text, ephemeral=True)

    @app_commands.command(name="my_stock_export", description="Get your current inventory in copy-paste format")
    async def my_stock_export(self, interaction: discord.Interaction):
        rows = await self.bot.db.get_user_inventory(interaction.user.id)
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

    @app_commands.command(name="deposit_item", description="Add items to your current stash (e.g. +50 Scrap)")
    @app_commands.autocomplete(item_name=item_autocomplete)
    async def deposit_item(self, interaction: discord.Interaction, item_name: str, amount: int):
        if amount <= 0: 
            await interaction.response.send_message("❌ Amount must be positive.", ephemeral=True)
            return
        
        # Update user stock
        await self.bot.db.update_user_stock(interaction.user.id, item_name, amount)
        
        # We need the new totals for the message
        # Use simple helper or manual fetch if needed. Here we just grab the global.
        global_total = await self.bot.db.get_global_total(item_name)
        
        # Note: We don't display the user's new total here to save a DB call, 
        # but you can add 'get_user_stock' to database.py if you really need it.
        
        await interaction.response.send_message(
            f"📦 **{interaction.user.display_name}** deposited **{amount}** {item_name}.\n"
            f"🌍 **Global Stock:** {global_total}"
        )
        await update_dashboard_message(interaction)

    @app_commands.command(name="withdraw_item", description="Remove items from your stash (e.g. -50 Scrap)")
    @app_commands.autocomplete(item_name=item_autocomplete)
    async def withdraw_item(self, interaction: discord.Interaction, item_name: str, amount: int):
        if amount <= 0: 
            await interaction.response.send_message("❌ Amount must be positive.", ephemeral=True)
            return

        try:
            new_bal, global_total = await self.bot.db.withdraw_user_stock(interaction.user.id, item_name, amount)
            await interaction.response.send_message(
                f"📉 **{interaction.user.display_name}** withdrew **{amount}** {item_name}.\n"
                f"👤 **Your Remaining:** {new_bal}\n"
                f"🌍 **Global Stock:** {global_total}"
            )
            await update_dashboard_message(interaction)
        except ValueError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)

    @app_commands.command(name="modify_item_qty", description="Set your EXACT stock (Overwrite old value)")
    @app_commands.autocomplete(item_name=item_autocomplete)
    async def modify_item_qty(self, interaction: discord.Interaction, item_name: str, quantity: int):
        if quantity < 0:
            await interaction.response.send_message("❌ Quantity cannot be negative.", ephemeral=True)
            return

        await self.bot.db.set_user_stock(interaction.user.id, item_name, quantity)
        global_total = await self.bot.db.get_global_total(item_name)

        await interaction.response.send_message(
            f"✏️ **{interaction.user.display_name}** updated **{item_name}** to **{quantity}**.\n"
            f"🌍 **Global Stock:** {global_total}"
        )
        await update_dashboard_message(interaction)

async def setup(bot):
    await bot.add_cog(Members(bot))