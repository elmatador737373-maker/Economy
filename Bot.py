import discord
from discord import app_commands, Interaction
from discord.ext import commands
from discord.ui import View, Select
import sqlite3
import random
import os
import threading
from flask import Flask

# ================= CONFIGURAZIONE INIZIALE =================
TOKEN = os.environ.get("TOKEN")
intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Connessione DB (check_same_thread=False è vitale per Flask + Discord)
conn = sqlite3.connect("economia.db", check_same_thread=False)
cursor = conn.cursor()

def init_db():
    cursor.execute("CREATE TABLE IF NOT EXISTS users (user_id TEXT PRIMARY KEY, wallet INTEGER DEFAULT 500, bank INTEGER DEFAULT 0)")
    cursor.execute("CREATE TABLE IF NOT EXISTS items (name TEXT PRIMARY KEY, description TEXT, price INTEGER, role_required TEXT)")
    cursor.execute("CREATE TABLE IF NOT EXISTS inventory (user_id TEXT, item_name TEXT, quantity INTEGER)")
    cursor.execute("CREATE TABLE IF NOT EXISTS depositi (role_id TEXT PRIMARY KEY, money INTEGER DEFAULT 0)")
    cursor.execute("CREATE TABLE IF NOT EXISTS depositi_items (role_id TEXT, item_name TEXT, quantity INTEGER)")
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_user_item ON inventory (user_id, item_name)")
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_role_item ON depositi_items (role_id, item_name)")
    conn.commit()

init_db()

def get_user_data(user_id):
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (str(user_id),))
    user = cursor.fetchone()
    if not user:
        cursor.execute("INSERT INTO users (user_id, wallet, bank) VALUES (?, ?, ?)", (str(user_id), 500, 0))
        conn.commit()
        return (str(user_id), 500, 0)
    return user

# ================= COMANDO AGGIUNGI SOLDI (ADMIN) =================

@bot.tree.command(name="aggiungisoldi", description="ADMIN - Aggiungi soldi al portafoglio di un utente")
@app_commands.describe(utente="L'utente a cui regalare i soldi", importo="Quantità da aggiungere")
async def aggiungisoldi(interaction: Interaction, utente: discord.Member, importo: int):
    # Diciamo a Discord di attendere (evita l'errore "L'applicazione non risponde")
    await interaction.response.defer(ephemeral=True)

    # Controllo permessi Admin
    if not interaction.user.guild_permissions.administrator:
        return await interaction.followup.send("❌ Non hai i permessi necessari per usare questo comando.")
    
    if importo <= 0:
        return await interaction.followup.send("⚠️ Inserisci un importo maggiore di zero.")

    # Assicuriamoci che l'utente esista nel database
    get_user_data(utente.id)

    # Esecuzione dell'aggiunta nel database
    try:
        cursor.execute("UPDATE users SET wallet = wallet + ? WHERE user_id = ?", (importo, str(utente.id)))
        conn.commit()
        
        # Recuperiamo il nuovo saldo per conferma
        cursor.execute("SELECT wallet FROM users WHERE user_id = ?", (str(utente.id),))
        nuovo_saldo = cursor.fetchone()[0]

        await interaction.followup.send(f"✅ Accreditati **{importo}$** a {utente.mention}.\n💰 Nuovo saldo portafoglio: **{nuovo_saldo}$**")
    except Exception as e:
        await interaction.followup.send(f"❌ Errore durante l'operazione: {e}")


# ================= COMANDI ADMIN (SHOP & GESTIONE) =================

@bot.tree.command(name="crea_item_shop", description="ADMIN - Aggiungi un oggetto al negozio")
async def crea_item_shop(interaction: Interaction, nome: str, descrizione: str, prezzo: int, ruolo_richiesto: discord.Role = None):
    await interaction.response.defer(ephemeral=True)
    if not interaction.user.guild_permissions.administrator:
        return await interaction.followup.send("❌ Solo gli admin possono farlo.")

    r_id = str(ruolo_richiesto.id) if ruolo_richiesto else "None"
    try:
        cursor.execute("INSERT INTO items (name, description, price, role_required) VALUES (?, ?, ?, ?)", (nome, descrizione, prezzo, r_id))
        conn.commit()
        await interaction.followup.send(f"✅ Creato: **{nome}** ({prezzo}$)")
    except:
        await interaction.followup.send("⚠️ Errore: l'item esiste già.")

@bot.tree.command(name="elimina_item_shop", description="ADMIN - Rimuovi un oggetto dal negozio")
async def elimina_item_shop(interaction: Interaction, nome: str):
    await interaction.response.defer(ephemeral=True)
    if not interaction.user.guild_permissions.administrator:
        return await interaction.followup.send("❌ Permessi insufficienti.")
    cursor.execute("DELETE FROM items WHERE name = ?", (nome,))
    conn.commit()
    await interaction.followup.send(f"🗑️ Item **{nome}** rimosso.")

@bot.tree.command(name="rimuovisoldi", description="ADMIN - Togli soldi a un utente")
async def rimuovisoldi(interaction: Interaction, utente: discord.Member, importo: int):
    await interaction.response.defer(ephemeral=True)
    if not interaction.user.guild_permissions.administrator:
        return await interaction.followup.send("❌ Non sei admin.")
    cursor.execute("UPDATE users SET wallet = MAX(0, wallet - ?) WHERE user_id = ?", (importo, str(utente.id)))
    conn.commit()
    await interaction.followup.send(f"✅ Rimossi {importo}$ a {utente.mention}.")

# ================= COMANDI ECONOMIA BASE (DAL TUO CODICE) =================

@bot.tree.command(name="cerca", description="Cerca oggetti nella spazzatura")
async def cerca(interaction: Interaction):
    await interaction.response.defer()
    loot_pool = [("Rame", 20), ("Ferro", 30), ("Plastica", 30), ("Nulla", 20)]
    scelta = random.choices([i[0] for i in loot_pool], weights=[i[1] for i in loot_pool])[0]

    if scelta == "Nulla":
        return await interaction.followup.send("Non hai trovato niente oggi.")

    cursor.execute("INSERT INTO inventory (user_id, item_name, quantity) VALUES (?, ?, 1) ON CONFLICT(user_id, item_name) DO UPDATE SET quantity = quantity + 1", (str(interaction.user.id), scelta))
    conn.commit()
    await interaction.followup.send(f"📦 Hai trovato: **{scelta}**!")

@bot.tree.command(name="portafoglio", description="Controlla i tuoi soldi")
async def portafoglio(interaction: Interaction):
    await interaction.response.defer()
    user = get_user_data(interaction.user.id)
    await interaction.followup.send(f"💰 **Portafoglio:** {user[1]}$ | 🏦 **Banca:** {user[2]}$")

# ================= SISTEMA NEGOZIO & ACQUISTO =================

@bot.tree.command(name="shop", description="Mostra il negozio")
async def shop(interaction: Interaction):
    await interaction.response.defer()
    cursor.execute("SELECT name, description, price, role_required FROM items")
    items = cursor.fetchall()
    if not items: return await interaction.followup.send("Negozio vuoto.")
    
    embed = discord.Embed(title="🏪 Shop", color=discord.Color.gold())
    for n, d, p, r in items:
        req = f"<@&{r}>" if r != "None" else "Libero"
        embed.add_field(name=f"{n} - {p}$", value=f"{d}\nRichiede: {req}", inline=False)
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="compra", description="Compra un oggetto")
async def compra(interaction: Interaction, nome: str):
    await interaction.response.defer(ephemeral=True)
    user = get_user_data(interaction.user.id)
    cursor.execute("SELECT name, price, role_required FROM items WHERE name = ?", (nome,))
    item = cursor.fetchone()

    if not item: return await interaction.followup.send("Item non trovato.")
    
    n, p, r = item
    if user[1] < p: return await interaction.followup.send("Non hai abbastanza soldi.")
    if r != "None" and discord.utils.get(interaction.user.roles, id=int(r)) is None:
        return await interaction.followup.send(f"Ti serve il ruolo <@&{r}>.")

    cursor.execute("UPDATE users SET wallet = wallet - ? WHERE user_id = ?", (p, str(interaction.user.id)))
    cursor.execute("INSERT INTO inventory (user_id, item_name, quantity) VALUES (?, ?, 1) ON CONFLICT(user_id, item_name) DO UPDATE SET quantity = quantity + 1", (str(interaction.user.id), n))
    conn.commit()
    await interaction.followup.send(f"🛍️ Hai comprato **{n}**!")

# ================= DEPOSITI DI RUOLO (DAL TUO CODICE) =================

@bot.tree.command(name="deposita_cassa", description="Deposita soldi nella cassa fazione")
async def deposita_cassa(interaction: Interaction, importo: int):
    await interaction.response.defer(ephemeral=True)
    user = get_user_data(interaction.user.id)
    if user[1] < importo: return await interaction.followup.send("Soldi insufficienti.")

    # Trova se l'utente ha un ruolo che ha un deposito
    cursor.execute("SELECT role_id FROM depositi")
    roles_with_dep = [int(r[0]) for r in cursor.fetchall()]
    user_role = next((r.id for r in interaction.user.roles if r.id in roles_with_dep), None)

    if not user_role: return await interaction.followup.send("Non hai ruoli con deposito.")

    cursor.execute("UPDATE users SET wallet = wallet - ? WHERE user_id = ?", (importo, str(interaction.user.id)))
    cursor.execute("UPDATE depositi SET money = money + ? WHERE role_id = ?", (importo, str(user_role)))
    conn.commit()
    await interaction.followup.send(f"✅ Depositati {importo}$ nella cassa fazione.")

@bot.tree.command(name="crea_deposito_fazione", description="ADMIN - Crea deposito per un ruolo")
async def crea_deposito_fazione(interaction: Interaction, ruolo: discord.Role):
    await interaction.response.defer(ephemeral=True)
    if not interaction.user.guild_permissions.administrator: return await interaction.followup.send("No admin.")
    try:
        cursor.execute("INSERT INTO depositi (role_id, money) VALUES (?, 0)", (str(ruolo.id),))
        conn.commit()
        await interaction.followup.send(f"🏦 Deposito creato per {ruolo.mention}")
    except:
        await interaction.followup.send("Esiste già.")

# ================= WEB SERVER & START =================

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"✅ {bot.user} è pronto!")

app = Flask("")
@app.route("/")
def home(): return "Bot Online!"

def run_web():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

if __name__ == "__main__":
    threading.Thread(target=run_web).start()
    bot.run(TOKEN)

