import discord
from discord import app_commands
from discord.ext import commands
import sqlite3
import random
import asyncio
from flask import Flask
from threading import Thread
import os

# ================= FLASK SERVER PER PING =================
app = Flask('')

@app.route('/')
def home():
    return "Bot online!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

Thread(target=run_flask).start()

# ================= TOKEN =================
TOKEN = os.environ.get("TOKEN")  # prende il token dall'env di Render

# ================= BOT =================
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

cursor.execute("""
CREATE TABLE IF NOT EXISTS depositi_items (
    role_id TEXT,
    item_name TEXT,
    quantity INTEGER
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

def role_has_deposito(user_roles, role_required):
    for role in user_roles:
        if str(role.id) == str(role_required):
            return True
    return False

# ================= COMANDI =================
# INVENTARIO
@bot.tree.command(name="inventario", description="Visualizza il tuo inventario e i tuoi soldi")
async def inventario(interaction: discord.Interaction):
    user = get_user(interaction.user.id)

    cursor.execute("SELECT item_name, quantity FROM inventory WHERE user_id = ?", (str(interaction.user.id),))
    items = cursor.fetchall()

    desc = ""
    for item in items:
        desc += f"{item[0]} x{item[1]}\n"

    if desc == "":
        desc = "Inventario vuoto."

    embed = discord.Embed(title="🎒 Inventario", description=desc, color=discord.Color.blue())
    embed.add_field(name="💵 Portafoglio", value=f"{user[1]}$")
    embed.add_field(name="🏦 Banca", value=f"{user[2]}$")
    await interaction.response.send_message(embed=embed)

# DAI SOLDI
@bot.tree.command(name="daisoldi", description="Dai soldi a un altro player")
@app_commands.describe(utente="Utente che riceve", importo="Quantità di soldi")
async def daisolidi(interaction: discord.Interaction, utente: discord.Member, importo: int):
    if importo <= 0:
        await interaction.response.send_message("Importo non valido.", ephemeral=True)
        return

    user = get_user(interaction.user.id)
    target = get_user(utente.id)

    if user[1] < importo:
        await interaction.response.send_message("Non hai abbastanza soldi.", ephemeral=True)
        return

    cursor.execute("UPDATE users SET wallet = wallet - ? WHERE user_id = ?", (importo, str(interaction.user.id)))
    cursor.execute("UPDATE users SET wallet = wallet + ? WHERE user_id = ?", (importo, str(utente.id)))
    conn.commit()

    await interaction.response.send_message(f"Hai dato {importo}$ a {utente.mention}")

# PRELEVA
@bot.tree.command(name="preleva", description="Preleva soldi dalla banca")
@app_commands.describe(importo="Quantità da prelevare")
async def preleva(interaction: discord.Interaction, importo: int):
    user = get_user(interaction.user.id)

    if user[2] < importo:
        await interaction.response.send_message("Non hai abbastanza soldi in banca.", ephemeral=True)
        return

    cursor.execute("UPDATE users SET bank = bank - ?, wallet = wallet + ? WHERE user_id = ?",
                   (importo, importo, str(interaction.user.id)))
    conn.commit()
    await interaction.response.send_message(f"Hai prelevato {importo}$ dalla banca.")

# DEPOSITA
@bot.tree.command(name="deposita", description="Deposita soldi in banca")
@app_commands.describe(importo="Quantità da depositare")
async def deposita(interaction: discord.Interaction, importo: int):
    user = get_user(interaction.user.id)

    if user[1] < importo:
        await interaction.response.send_message("Non hai abbastanza soldi.", ephemeral=True)
        return

    cursor.execute("UPDATE users SET wallet = wallet - ?, bank = bank + ? WHERE user_id = ?",
                   (importo, importo, str(interaction.user.id)))
    conn.commit()
    await interaction.response.send_message(f"Hai depositato {importo}$ in banca.")

# CREA ITEM (ADMIN)
@bot.tree.command(name="creaitem", description="ADMIN - Crea un nuovo oggetto nel negozio")
@app_commands.describe(nome="Nome oggetto", descrizione="Descrizione", prezzo="Prezzo", ruolo="ID ruolo richiesto (opzionale)")
async def creaitem(interaction: discord.Interaction, nome: str, descrizione: str, prezzo: int, ruolo: str = None):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("Non sei admin.", ephemeral=True)
        return

    cursor.execute("INSERT OR REPLACE INTO items VALUES (?, ?, ?, ?)",
                   (nome, descrizione, prezzo, ruolo))
    conn.commit()
    await interaction.response.send_message(f"Oggetto {nome} creato con successo.")

# NEGOZIO
@bot.tree.command(name="negozio", description="Visualizza gli oggetti acquistabili")
async def negozio(interaction: discord.Interaction):
    cursor.execute("SELECT name, description, price FROM items")
    items = cursor.fetchall()

    desc = ""
    for item in items:
        desc += f"**{item[0]}** - {item[2]}$\n{item[1]}\n\n"

    if desc == "":
        desc = "Nessun oggetto disponibile."

    embed = discord.Embed(title="🛒 Negozio", description=desc, color=discord.Color.green())
    await interaction.response.send_message(embed=embed)

# CERCA
@bot.tree.command(name="cerca", description="Cerca oggetti nella spazzatura con probabilità")
async def cerca(interaction: discord.Interaction):
    loot = [("Rame", 30), ("Ferro", 25), ("Plastica", 20), ("Nulla", 25)]
    roll = random.randint(1, 100)
    current = 0

    for item, chance in loot:
        current += chance
        if roll <= current:
            trovato = item
            break

    if trovato == "Nulla":
        await interaction.response.send_message("Non hai trovato nulla.")
        return

    cursor.execute("INSERT INTO inventory VALUES (?, ?, 1)", (str(interaction.user.id), trovato))
    conn.commit()
    await interaction.response.send_message(f"Hai trovato: {trovato}!")

# ================= DEPOSITO RUOLO =================
@bot.tree.command(name="deposito", description="Apri il deposito del tuo ruolo")
async def deposito(interaction: discord.Interaction):
    roles_user = interaction.user.roles
    # Trova quale deposito può usare
    cursor.execute("SELECT role_id FROM depositi")
    depositi = cursor.fetchall()
    accessibile = None
    for r in depositi:
        if role_has_deposito(roles_user, r[0]):
            accessibile = r[0]
            break

    if not accessibile:
        await interaction.response.send_message("Non hai il ruolo richiesto per accedere a nessun deposito.", ephemeral=True)
        return

    # Visualizza soldi e item del deposito
    cursor.execute("SELECT money FROM depositi WHERE role_id = ?", (accessibile,))
    soldi = cursor.fetchone()[0]

    cursor.execute("SELECT item_name, quantity FROM depositi_items WHERE role_id = ?", (accessibile,))
    items = cursor.fetchall()
    desc = ""
    for item in items:
        desc += f"{item[0]} x{item[1]}\n"
    if desc == "":
        desc = "Nessun item nel deposito."

    embed = discord.Embed(title=f"Deposito ruolo", description=desc, color=discord.Color.purple())
    embed.add_field(name="💵 Fondo cassa", value=f"{soldi}$")
    await interaction.response.send_message(embed=embed)

# ================= READY =================
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Bot online come {bot.user}")

bot.run(TOKEN)
