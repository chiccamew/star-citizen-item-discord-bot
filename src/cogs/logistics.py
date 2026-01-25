import discord
from discord.ext import commands
from discord import app_commands
from src.utils import item_autocomplete, project_autocomplete, build_dashboard_embed

class Logistics(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="status", description="Show the main dashboard for a project")
    @app_commands.autocomplete(project_name=project_autocomplete)
    async def status(self, interaction: discord.Interaction, project_name: str):
        await interaction.response.defer()
        embed = await build_dashboard_embed(self.bot, project_name)
        if embed: 
            await interaction.followup.send(embed=embed)
        else: 
            await interaction.followup.send(f"❌ Project **{project_name}** not found or empty.")

    @app_commands.command(name="locate", description="Find who is holding a specific item")
    @app_commands.autocomplete(item_name=item_autocomplete)
    async def locate(self, interaction: discord.Interaction, item_name: str):
        # 1. Get Top Holders from DB
        rows = await self.bot.db.get_top_holders(item_name)
        total = await self.bot.db.get_global_total(item_name)
        
        if not rows: 
            await interaction.response.send_message(f"❌ No one has **{item_name}**.", ephemeral=True)
            return

        embed = discord.Embed(title=f"🔎 Stock Locator: {item_name}", description=f"**Global Total:** {total}", color=discord.Color.gold())
        
        list_text = ""
        for r in rows:
            user_id = r['user_id']
            qty = r['quantity']
            
            # Resolve User Name
            member = interaction.guild.get_member(user_id)
            if member is None:
                try: member = await interaction.guild.fetch_member(user_id)
                except discord.NotFound: member = None
            
            name = member.display_name if member else f"Unknown User ({user_id})"
            list_text += f"• **{name}**: {qty}\n"
        
        embed.add_field(name="Top Holders", value=list_text or "None")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="production", description="Check chain of production for a crafted item")
    @app_commands.autocomplete(item_name=item_autocomplete)
    async def production(self, interaction: discord.Interaction, item_name: str):
        # 1. Get Recipe info
        recipe = await self.bot.db.get_recipe(item_name)
        if not recipe:
            await interaction.response.send_message(f"⚠️ **{item_name}** has no recipe registered.", ephemeral=True)
            return

        input_item = recipe['input_item_name']
        ratio = recipe['quantity_required']
        
        # 2. Get holders of the raw material
        # We fetch the top holders of the input item
        holders = await self.bot.db.get_top_holders(input_item, limit=10)
        
        embed = discord.Embed(title=f"🏭 Production Chain: {item_name}", color=discord.Color.orange())
        embed.add_field(name="Recipe", value=f"Requires **{ratio}x {input_item}**", inline=False)
        
        # 3. Filter for people who have enough to make at least 1
        capable_holders = [h for h in holders if h['quantity'] >= ratio]
        
        if capable_holders:
            text = ""
            for r in capable_holders:
                member = interaction.guild.get_member(r['user_id'])
                if not member:
                    try: member = await interaction.guild.fetch_member(r['user_id'])
                    except: pass
                
                name = member.display_name if member else "Unknown"
                can_make = r['quantity'] // ratio
                text += f"• **{name}**: Has {r['quantity']} {input_item} (Can make **{can_make}**)\n"
            
            embed.add_field(name=f"Potential {item_name} Manufacturers", value=text, inline=False)
        else:
            embed.add_field(name="Status", value=f"❌ No one has enough {input_item} (Need {ratio}).", inline=False)

        await interaction.response.send_message(embed=embed)

async def setup(bot):
    await bot.add_cog(Logistics(bot))