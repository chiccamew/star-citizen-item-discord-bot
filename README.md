# Star Citizen Logistics Bot 🚀

A specialized Discord bot designed for Star Citizen organizations to manage large-scale resource collection missions (like the Idris Acquisition).

Unlike standard MMO guild banks, this bot manages a **Distributed Warehouse**: it tracks items held across individual member inventories and aggregates them into a live, org-wide dashboard.

## 🌟 Key Features

* **Live Dashboard:** A pinned message that updates in real-time as members contribute, showing progress bars for every required item.
* **Distributed Inventory:** Tracks "Who has what." Members keep their own items; the bot just maintains the ledger.
* **Recipe Logic:** Distinguishes between "Direct Stock" (finished items) and "Potential Stock" (raw materials that can be crafted).
* **Bulk Updates:** Allows members to paste inventory lists directly from game data or spreadsheets.
* **Locator:** Helps officers find exactly which player is holding specific items when it's time to gather.

---

## 📖 User Guide

### For Organization Members
* **`/update_stock`** 📝
  Opens a form to bulk-paste your inventory.
  * *Format:* `Item Name: Quantity` (e.g., `Scrap: 500`).
* **`/deposit_item [item] [amount]`** ➕
  Quickly add items after a single mining/salvaging run.
* **`/withdraw_item [item] [amount]`** ➖
  Remove items (e.g., if you sold them or got pirated).
* **`/my_stock`** 🎒
  View your current personal balance recorded in the system.

### For Logistics Officers
* **`/status [project]`** 📊
  View the current progress of a specific project (e.g., "Operation Idris").
* **`/locate [item]`** 🔎
  Find which members are holding a specific item. Shows the top 10 holders.
* **`/production [item]`** 🏭
  Checks if you have enough raw materials to craft a missing item.
  * *Example:* You need "Polaris Bits." The bot checks who has "Quantanium."

### For Admins
* **`/project_create [name]`**
  Initialize a new goal (e.g., "Operation Idris").
* **`/project_add_item [project] [item] [amount]`**
  Add a requirement to the project.
* **`/recipe_add [output] [input] [ratio]`**
  Define crafting rules (e.g., 24 Quantanium → 1 Polaris Bit).
* **`/dashboard_set [project]`** 📌
  Creates (or moves) the **Live Dashboard** to the current channel and pins it.

---

## 🛠️ Developer Setup Guide

### Prerequisites
1. **Python 3.9+** installed on your Windows machine.
2. A **Supabase** account (Free tier is sufficient).
3. A **Discord Developer** Application & Bot Token.

### Step 1: Database Setup (Supabase)
1. Create a new project on [Supabase.com](https://supabase.com/).
2. Go to the **SQL Editor** in the sidebar.
3. Open the file `database-table.sql` included in this project.
4. Copy the content of that file and paste it into the SQL Editor, then click **Run**.
5. Go to **Project Settings -> Database** and copy your **Connection String (URI)**.
   * *Note:* It will look like `postgresql://postgres.[ref]:[password]@aws-0-us-east-1.pooler.supabase.com:5432/postgres`.

### Step 2: Discord Bot Setup
1. Go to the [Discord Developer Portal](https://discord.com/developers/applications).
2. Create an Application -> **Bot**.
3. **Enable Privileged Intents:**
   * ✅ Message Content Intent
   * ✅ Server Members Intent
4. **Copy Token:** Click "Reset Token" and save it.
5. **Invite Bot:** Go to OAuth2 -> URL Generator. Select `bot` and `applications.commands`. Copy the link and invite it to your server.

### Step 3: Local Installation (Windows)

1. **Clone/Download** this repository to a folder (e.g., `C:\Projects\SCBot`).
2. Open your terminal (Command Prompt or PowerShell) in that folder.
3. **Create a Virtual Environment:**
   ```powershell
   python -m venv venv
4. Activate the Environment:
    ```powershell
   .\venv\Scripts\Activate.ps1
    
(If you get a permission error, run Set-ExecutionPolicy Unrestricted -Scope Process first).

5. Install Dependencies:
    ```powershell
    pip install -r requirements.txt

### Step 4: Configuration

Create a file named `.env` in the root folder and fill in your details:

    ```powershell
    DISCORD_TOKEN=your_discord_bot_token_here
    DATABASE_URL=postgresql://postgres.yourproject:password@aws-0-us-east-1.pooler.supabase.com:5432/postgres
    WAREHOUSE_CHANNEL_ID=123456789012345678
    GUILD_ID=123456789012345678

* Tip: You can get IDs in Discord by enabling Developer Mode (User Settings -> Advanced) and right-clicking the Channel/Server name -> Copy ID.

### Step 5: Run the Bot

With your virtual environment active, run:
    ```powershell
    python main.py

If successful, you will see:

Logged in as SCLogistic#1234 Database Pool Established Commands synced to Guild ID: ...

---

## 🚑 Troubleshooting

* **Error:** `prepared statement "..." already exists`

    * Cause: Supabase uses PgBouncer in transaction mode, which doesn't support prepared statements.

    * Fix: Ensure your asyncpg.create_pool call includes statement_cache_size=0. (This is included in the current main.py).

* **Error:** `Unknown interaction`

    * Cause: The database query took longer than 3 seconds, causing Discord to time out.

    * Fix: The code uses await interaction.response.defer() to handle long queries. Ensure you aren't removing these lines when modifying commands.

* **Autocomplete not working?**

    * Make sure there is data in the items table.

    * Try typing at least one letter.

    * If the database connection is slow, the first attempt might fail. The bot uses a Connection Pool to keep this fast.