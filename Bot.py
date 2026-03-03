import discord
from discord import app_commands, Interaction
from discord.ext import commands
from discord.ui import View, Select, Modal, TextInput
import sqlite3
import random
import os

TOKEN = os.environ["TOKEN"]

intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ================= DATABASE =================
conn = sqlite3.connect("economia.db")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    wallet INTEGER DEFAULT 500,
    bank INTEGER DEFAULT 0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS items (
    name TEXT PRIMARY KEY,
    description TEXT,
    price INTEGER,
    role_required TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS inventory (
    user_id TEXT,
    item_name TEXT,
    quantity INTEGER
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS depositi (
    role_id TEXT PRIMARY KEY,
    money INTEGER DEFAULT 0
)
""")

conn.commit()

# ================= FUNZIONI =================
def get_user(user_id):
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (str(user_id),))
    user = cursor.fetchone()
    if not user:
        cursor.execute("INSERT INTO users (user_id) VALUES (?)", (str(user_id),))
        conn.commit()
        return (user_id, 500, 0)
    return user

# ================= COMANDI UTENTE =================
@bot.tree.command(name="inventario", description="Visualizza il tuo inventario e i tuoi soldi")
async def inventario(interaction: Interaction):
    await interaction.response.defer(ephemeral=True)
    user = get_user(interaction.user.id)
    cursor.execute("SELECT item_name, quantity FROM inventory WHERE user_id = ?", (str(interaction.user.id),))
    items = cursor.fetchall()
    desc = "\n".join(f"{i[0]} x{i[1]}" for i in items) or "Inventario vuoto."
    embed = discord.Embed(title="🎒 Inventario", description=desc, color=discord.Color.blue())
    embed.add_field(name="💵 Portafoglio", value=f"{user[1]}$")
    embed.add_field(name="🏦 Banca", value=f"{user[2]}$")
    await interaction.followup.send(embed=embed, ephemeral=True)

# ====== DAI SOLDI ======
@bot.tree.command(name="daisoldi", description="Dai soldi a un altro player")
@app_commands.describe(utente="Utente che riceve", importo="Quantità di soldi")
async def daisolidi(interaction: Interaction, utente: discord.Member, importo: int):
    await interaction.response.defer(ephemeral=True)
    if importo <= 0:
        await interaction.followup.send("Importo non valido.", ephemeral=True)
        return
    user = get_user(interaction.user.id)
    target = get_user(utente.id)
    if user[1] < importo:
        await interaction.followup.send("Non hai abbastanza soldi.", ephemeral=True)
        return
    cursor.execute("UPDATE users SET wallet = wallet - ? WHERE user_id = ?", (importo, str(interaction.user.id)))
    cursor.execute("UPDATE users SET wallet = wallet + ? WHERE user_id = ?", (importo, str(utente.id)))
    conn.commit()
    await interaction.followup.send(f"Hai dato {importo}$ a {utente.mention}", ephemeral=True)

# ====== DEPOSITA ======
@bot.tree.command(name="deposita", description="Deposita soldi in banca")
@app_commands.describe(importo="Quantità da depositare")
async def deposita(interaction: Interaction, importo: int):
    await interaction.response.defer(ephemeral=True)
    user = get_user(interaction.user.id)
    if user[1] < importo:
        await interaction.followup.send("Non hai abbastanza soldi.", ephemeral=True)
        return
    cursor.execute("UPDATE users SET wallet = wallet - ?, bank = bank + ? WHERE user_id = ?", (importo, importo, str(interaction.user.id)))
    conn.commit()
    await interaction.followup.send(f"Hai depositato {importo}$ in banca.", ephemeral=True)

# ====== PRELEVA ======
@bot.tree.command(name="preleva", description="Preleva soldi dalla banca")
@app_commands.describe(importo="Quantità da prelevare")
async def preleva(interaction: Interaction, importo: int):
    await interaction.response.defer(ephemeral=True)
    user = get_user(interaction.user.id)
    if user[2] < importo:
        await interaction.followup.send("Non hai abbastanza soldi in banca.", ephemeral=True)
        return
    cursor.execute("UPDATE users SET bank = bank - ?, wallet = wallet + ? WHERE user_id = ?", (importo, importo, str(interaction.user.id)))
    conn.commit()
    await interaction.followup.send(f"Hai prelevato {importo}$ dalla banca.", ephemeral=True)
# ================= DEPOSITO RUOLO =================
@bot.tree.command(name="creadeposito", description="ADMIN - Crea un deposito per un ruolo")
@app_commands.describe(ruolo="Ruolo da associare al deposito")
async def creadeposito(interaction: Interaction, ruolo: discord.Role):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("Non sei admin.", ephemeral=True)
        return

    # Controllo se esiste già
    cursor.execute("SELECT role_id FROM depositi WHERE role_id = ?", (str(ruolo.id),))
    if cursor.fetchone():
        await interaction.response.send_message(f"Il ruolo {ruolo.mention} ha già un deposito.", ephemeral=True)
        return

    # Crea deposito
    cursor.execute("INSERT INTO depositi (role_id, money) VALUES (?, ?)", (str(ruolo.id), 0))
    conn.commit()
    await interaction.response.send_message(f"Deposito creato per il ruolo {ruolo.mention}!", ephemeral=True)
   
@bot.tree.command(name="deposito", description="Apri il deposito del tuo ruolo")
async def deposito(interaction: Interaction):
    await interaction.response.defer(ephemeral=True)

    # Prendi tutti i depositi
    cursor.execute("SELECT role_id FROM depositi")
    deposit_roles = [int(r[0]) for r in cursor.fetchall()]

    # Ruoli dell'utente
    user_roles = [r.id for r in interaction.user.roles]

    # Ruoli disponibili per l'utente
    ruoli_possibili = [r for r in user_roles if r in deposit_roles]
    if not ruoli_possibili:
        await interaction.followup.send("Non hai il ruolo richiesto per nessun deposito.", ephemeral=True)
        return

    # Menu per scegliere il ruolo
    options_ruoli = [discord.SelectOption(label=f"<@&{r}>", value=str(r)) for r in ruoli_possibili]

    class RoleSelect(Select):
        def __init__(self):
            super().__init__(placeholder="Seleziona il ruolo del deposito", min_values=1, max_values=1, options=options_ruoli)

        async def callback(self, role_inter: Interaction):
            role_id = int(self.values[0])

            # Menu soldi o item
            choice_options = [
                discord.SelectOption(label="Soldi", value="soldi"),
                discord.SelectOption(label="Item", value="item")
            ]

            class ChoiceSelect(Select):
                def __init__(self):
                    super().__init__(placeholder="Scegli cosa gestire", min_values=1, max_values=1, options=choice_options)

                async def callback(self, choice_inter: Interaction):
                    scelta = self.values[0]
                    if scelta == "soldi":
                        cursor.execute("SELECT money FROM depositi WHERE role_id = ?", (str(role_id),))
                        money = cursor.fetchone()[0]
                        await choice_inter.response.send_message(f"Fondo cassa: {money}$\nUsa /depositosoldi o /prelevasoldi per gestire i soldi.", ephemeral=True)
                    else:
                        # Mostra gli item depositati
                        cursor.execute("SELECT item_name, quantity FROM inventory WHERE user_id = ?", (f"deposit_{role_id}",))
                        items = cursor.fetchall()
                        if not items:
                            await choice_inter.response.send_message("Nessun item nel deposito.", ephemeral=True)
                            return

                        options_item = [discord.SelectOption(label=f"{i[0]} x{i[1]}", value=i[0]) for i in items]

                        class ItemSelect(Select):
                            def __init__(self):
                                super().__init__(placeholder="Seleziona un item", min_values=1, max_values=1, options=options_item)

                            async def callback(self, item_inter: Interaction):
                                nome_item = self.values[0]
                                await item_inter.response.send_message(f"Per prelevare o depositare {nome_item} userai il modal specifico.", ephemeral=True)
                                # Qui puoi richiamare modal per quantità

                        view_item = View()
                        view_item.add_item(ItemSelect())
                        await choice_inter.response.send_message("Scegli l'item da gestire:", view=view_item, ephemeral=True)

            view_choice = View()
            view_choice.add_item(ChoiceSelect())
            await role_inter.response.send_message("Cosa vuoi fare?", view=view_choice, ephemeral=True)

    view_role = View()
    view_role.add_item(RoleSelect())
    await interaction.followup.send("Seleziona il ruolo del deposito:", view=view_role, ephemeral=True) 
# ================= READY =================
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Bot online come {bot.user}!")

# ================= RUN =================

from flask import Flask
from threading import Thread
import os

# -------------------- Flask Keep-Alive --------------------
app = Flask("")

@app.route("/")
def home():
    return "Bot online e funzionante! 🚀"

def run():
    port = int(os.environ.get("PORT", 10000))  # usa la porta di Render
    app.run(host="0.0.0.0", port=port)

def keep_alive():
    t = Thread(target=run)
    t.start()
    
bot.run(TOKEN)
