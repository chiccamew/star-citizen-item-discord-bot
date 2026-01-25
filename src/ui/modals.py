import discord
from discord import ui
from src.utils import update_dashboard_message

class InventoryModal(ui.Modal, title="Update Inventory"):
    inventory_input = ui.TextInput(label="Paste (Item: Qty)", style=discord.TextStyle.paragraph, placeholder="Scrap: 500\nGold: 10", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        lines = self.inventory_input.value.split('\n')
        updated_count = 0
        errors = []

        for line in lines:
            if ":" in line:
                try:
                    name, qty = line.split(":", 1)
                    await interaction.client.db.update_user_stock(interaction.user.id, name.strip(), int(qty.strip().replace(',', '')))
                    updated_count += 1
                except Exception as e:
                    errors.append(f"Error '{line}': {e}")
        
        msg = f"✅ Updated {updated_count} items."
        if errors: msg += "\n⚠️ " + "\n".join(errors[:3])
        await interaction.followup.send(msg)
        await update_dashboard_message(interaction)

class ProjectRequirementModal(ui.Modal, title="Bulk Edit Requirements"):
    def __init__(self, project_name):
        super().__init__()
        self.project_name = project_name
        
    requirements_input = ui.TextInput(label="Paste (Item: Qty)", style=discord.TextStyle.paragraph, placeholder="Scrap: 5000", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        lines = self.requirements_input.value.split('\n')
        count = 0
        for line in lines:
            if ":" in line:
                try:
                    name, qty = line.split(":", 1)
                    await interaction.client.db.add_project_requirement(self.project_name, name.strip(), int(qty.strip().replace(',', '')))
                    count += 1
                except: pass
        await interaction.followup.send(f"✅ Updated {count} requirements for {self.project_name}.")
        await update_dashboard_message(interaction)

class WipeConfirmModal(ui.Modal, title="⚠️ CONFIRM WIPE"):
    confirmation = ui.TextInput(label="Type 'DELETE EVERYTHING'", placeholder="DELETE EVERYTHING", required=True)

    async def on_submit(self, interaction: discord.Interaction):
        if self.confirmation.value != "DELETE EVERYTHING":
            return await interaction.response.send_message("❌ Cancelled.", ephemeral=True)
        
        await interaction.response.defer(ephemeral=True)
        await interaction.client.db.wipe_all_inventory()
        await interaction.followup.send("💥 **System Wiped.**")
        await update_dashboard_message(interaction)