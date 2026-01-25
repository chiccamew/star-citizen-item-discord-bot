import discord
from discord.ext import commands
from discord import app_commands
from src.utils import is_officer, project_autocomplete, item_autocomplete, build_dashboard_embed, update_dashboard_message
from src.ui.modals import ProjectRequirementModal, WipeConfirmModal

# --- DEPENDENT AUTOCOMPLETE FUNCTION ---
async def admin_item_autocomplete(interaction: discord.Interaction, current: str):
    """
    If 'target_user' is selected, show ONLY their items.
    Otherwise, show ALL items.
    """
    # 1. Check if the user filled in the 'target_user' field
    target_user = interaction.namespace.target_user
    
    user_id = None
    if target_user:
        # Discord usually returns an Object or Member, usually having an .id attribute
        if hasattr(target_user, 'id'):
            user_id = target_user.id
        elif isinstance(target_user, int):
            user_id = target_user

    # 2. Decide which DB query to run
    if user_id:
        # Specific User Search
        records = await interaction.client.db.get_user_items_autocomplete(user_id, current)
    else:
        # Global Search (Default)
        records = await interaction.client.db.item_autocomplete(current)
    
    return [app_commands.Choice(name=r['name'], value=r['name']) for r in records]


class Admin(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="project_create", description="Start a new collection project")
    @is_officer()
    async def project_create(self, interaction: discord.Interaction, name: str):
        try:
            await self.bot.db.create_project(name)
            await interaction.response.send_message(f"✅ Project **{name}** created.", ephemeral=True)
        except: 
            await interaction.response.send_message("❌ Project already exists.", ephemeral=True)

    @app_commands.command(name="project_add_item", description="Add a requirement to a project")
    @app_commands.autocomplete(item_name=item_autocomplete, project_name=project_autocomplete)
    @is_officer()
    async def project_add_item(self, interaction: discord.Interaction, project_name: str, item_name: str, amount: int):
        try:
            await self.bot.db.add_project_requirement(project_name, item_name, amount)
            await interaction.response.send_message(f"✅ Added **{amount}x {item_name}** to {project_name}.", ephemeral=True)
        except ValueError:
            await interaction.response.send_message(f"❌ Project **{project_name}** not found.", ephemeral=True)

    @app_commands.command(name="project_item_export", description="Get a copy-paste list of current project requirements")
    @app_commands.autocomplete(project_name=project_autocomplete)
    @is_officer()
    async def project_item_export(self, interaction: discord.Interaction, project_name: str):
        rows = await self.bot.db.get_project_requirements(project_name)

        if not rows:
            await interaction.response.send_message(f"⚠️ Project **{project_name}** has no requirements yet.", ephemeral=True)
            return

        export_text = ""
        for row in rows:
            export_text += f"{row['item_name']}: {row['target_amount']}\n"
        
        await interaction.response.send_message(
            f"📋 **Export for {project_name}:**\nCopy the block below used in `/project_item_bulk_edit`", 
            ephemeral=True
        )
        await interaction.followup.send(f"```{export_text}```", ephemeral=True)

    @app_commands.command(name="project_item_bulk_edit", description="Bulk update/overwrite project requirements")
    @is_officer()
    @app_commands.autocomplete(project_name=project_autocomplete)
    async def project_item_bulk_edit(self, interaction: discord.Interaction, project_name: str):
        await interaction.response.send_modal(ProjectRequirementModal(project_name))

    @app_commands.command(name="recipe_add", description="Define how an item is crafted")
    @app_commands.autocomplete(output_item=item_autocomplete, input_item=item_autocomplete)
    @is_officer() 
    async def recipe_add(self, interaction: discord.Interaction, output_item: str, input_item: str, ratio: int):
        await self.bot.db.add_recipe(output_item, input_item, ratio)
        await interaction.response.send_message(f"✅ Recipe Saved: **{ratio} {input_item}** = 1 **{output_item}**", ephemeral=True)

    @app_commands.command(name="dashboard_set", description="Create/Reset the Live Dashboard")
    @is_officer()
    @app_commands.autocomplete(project_name=project_autocomplete)
    async def dashboard_set(self, interaction: discord.Interaction, project_name: str):
        await interaction.response.defer(ephemeral=True)
        embed = await build_dashboard_embed(self.bot, project_name)
        if not embed: return await interaction.followup.send("❌ Empty project.")
        
        msg = await interaction.channel.send(embed=embed)
        try: await msg.pin()
        except: pass
        
        await self.bot.db.set_dashboard_config(interaction.guild.id, interaction.channel.id, msg.id, project_name)
        await interaction.followup.send(f"✅ Dashboard set to **{project_name}**.")

    @app_commands.command(name="admin_deposit", description="Give items TO another user")
    @app_commands.describe(target_user="Who gets the items?", item_name="Which item?", amount="How many?")
    @app_commands.autocomplete(item_name=item_autocomplete)
    @is_officer()
    async def admin_deposit(self, interaction: discord.Interaction, target_user: discord.Member, item_name: str, amount: int):
        if amount <= 0: return await interaction.response.send_message("❌ Positive amounts only.", ephemeral=True)

        await self.bot.db.update_user_stock(target_user.id, item_name, amount)
        
        item_id = await self.bot.db.get_item_id_by_name(item_name)
        async with self.bot.db.pool.acquire() as conn:
             new_personal = await conn.fetchval("SELECT quantity FROM user_inventory WHERE user_id = $1 AND item_id = $2", target_user.id, item_id)
        
        global_total = await self.bot.db.get_global_total(item_name)

        await interaction.response.send_message(
            f"👮 **Admin Action:** Deposited **{amount}** {item_name} into {target_user.mention}'s stash.\n"
            f"👤 **Their Total:** {new_personal}\n"
            f"🌍 **Global Stock:** {global_total}"
        )
        await update_dashboard_message(interaction)

    @app_commands.command(name="admin_withdraw", description="Remove items FROM another user")
    @app_commands.describe(target_user="Who loses the items?", item_name="Which item?", amount="How many?")
    # 🔴 CHANGED: Now uses dependent autocomplete
    @app_commands.autocomplete(item_name=admin_item_autocomplete) 
    @is_officer()
    async def admin_withdraw(self, interaction: discord.Interaction, target_user: discord.Member, item_name: str, amount: int):
        if amount <= 0: return await interaction.response.send_message("❌ Positive amounts only.", ephemeral=True)

        try:
            new_bal, global_total = await self.bot.db.withdraw_user_stock(target_user.id, item_name, amount)
            await interaction.response.send_message(
                f"👮 **Admin Action:** Withdrew **{amount}** {item_name} from {target_user.mention}.\n"
                f"👤 **Their Remaining:** {new_bal}\n"
                f"🌍 **Global Stock:** {global_total}"
            )
            await update_dashboard_message(interaction)
        except ValueError as e:
            await interaction.response.send_message(f"❌ {e}", ephemeral=True)

    @app_commands.command(name="wipe_all_user_stock", description="⚠️ NUCLEAR: Delete ALL user inventory data")
    @is_officer()
    async def wipe_all(self, interaction: discord.Interaction):
        await interaction.response.send_modal(WipeConfirmModal())

async def setup(bot):
    await bot.add_cog(Admin(bot))