import discord
from discord import app_commands
import os
from dotenv import load_dotenv

load_dotenv()
OFFICER_ROLE_ID = int(os.getenv("OFFICER_ROLE_ID", 0))

# --- PERMISSIONS ---
def is_officer():
    def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user.guild_permissions.administrator:
            return True
        return any(role.id == OFFICER_ROLE_ID for role in interaction.user.roles)
    return app_commands.check(predicate)

# --- AUTOCOMPLETE HELPERS ---
async def item_autocomplete(interaction: discord.Interaction, current: str):
    # interaction.client refers to the 'bot' instance
    records = await interaction.client.db.item_autocomplete(current)
    return [app_commands.Choice(name=r['name'], value=r['name']) for r in records]

async def project_autocomplete(interaction: discord.Interaction, current: str):
    records = await interaction.client.db.project_autocomplete(current)
    return [app_commands.Choice(name=r['name'], value=r['name']) for r in records]

# --- DASHBOARD LOGIC ---
async def build_dashboard_embed(bot, project_name):
    # Retrieve data using the Database Manager
    reqs = await bot.db.get_project_requirements(project_name)
    if not reqs: return None

    requirements_map = {row['item_name']: row['target_amount'] for row in reqs}
    embed = discord.Embed(title=f"🚀 Project Status: {project_name}", color=discord.Color.blue())
    min_project_sets = None

    for req in reqs:
        item = req['item_name']
        target = req['target_amount']
        
        direct = await bot.db.get_global_total(item)
        recipe = await bot.db.get_recipe(item)
        
        potential = 0
        input_item_name = None
        surplus_raw = 0
        
        if recipe:
            input_item_name = recipe['input_item_name']
            ratio = recipe['quantity_required']
            raw_total = await bot.db.get_global_total(input_item_name)
            raw_needed_directly = requirements_map.get(input_item_name, 0)
            surplus_raw = max(0, raw_total - raw_needed_directly)
            potential = surplus_raw // ratio
        
        total_ready = direct + potential
        percent = min(100, int((total_ready / target) * 100))

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
        
        status_text = f"`{bar}` **{percent}%**\n• **Ready:** {direct} / {target}\n"
        if potential > 0:
            status_text += f"• **Potential:** +{potential} (from {surplus_raw} excess {input_item_name})\n"
        elif recipe:
             raw_total_debug = await bot.db.get_global_total(input_item_name)
             if raw_total_debug > 0: status_text += f"• *Raw materials reserved*\n"

        embed.add_field(name=item, value=status_text, inline=False)
        
    if min_project_sets is not None:
        embed.description = f"📦 **Available Sets:** {min_project_sets} completions available."
    embed.set_footer(text="Updates live • ▓ = Ready, ▒ = Craftable")
    return embed

async def update_dashboard_message(interaction_or_guild):
    # Handle both interaction objects and guild objects
    guild = interaction_or_guild.guild if isinstance(interaction_or_guild, discord.Interaction) else interaction_or_guild
    # We need the bot instance. If it's a guild, we assume the bot is passed or accessible differently.
    # Hack: getting bot from guild.me or the interaction client
    bot = interaction_or_guild.client if isinstance(interaction_or_guild, discord.Interaction) else interaction_or_guild.me._state._get_client()

    config = await bot.db.get_dashboard_config(guild.id)
    if not config: return

    channel = guild.get_channel(config['dashboard_channel_id'])
    if not channel: return
    try:
        message = await channel.fetch_message(config['dashboard_message_id'])
        new_embed = await build_dashboard_embed(bot, config['project_name'])
        if new_embed: await message.edit(embed=new_embed)
    except discord.NotFound:
        pass