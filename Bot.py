import discord
from discord import app_commands, Interaction
from discord.ext import commands
from discord.ui import View, Select
import sqlite3
import os
import threading
from flask import Flask

# Configurazione Iniziale
TOKEN = os.environ.get("TOKEN")
intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ================= DATABASE =================
conn = sqlite3.connect("economia.db", check_same_thread=False)
cursor = conn.cursor()

def init_db():
    cursor.execute("CREATE TABLE IF NOT EXISTS users (user_id TEXT PRIMARY KEY, wallet INTEGER DEFAULT 500, bank INTEGER DEFAULT 0)")
    cursor.execute("CREATE TABLE IF NOT EXISTS inventory (user_id TEXT, item_name TEXT, quantity INTEGER)")
    cursor.execute("CREATE TABLE IF NOT EXISTS depositi (role_id TEXT PRIMARY KEY, money INTEGER DEFAULT 0)")
    cursor.execute("CREATE TABLE IF NOT EXISTS depositi_items (role_id TEXT, item_name TEXT, quantity INTEGER)")
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
# ================= COMANDI NEGOZIO UTENTE =================

@bot.tree.command(name="shop", description="Visualizza gli articoli disponibili nel negozio")
async def shop(interaction: Interaction):
    # Defer pubblico perché lo shop deve essere visibile a tutti
    await interaction.response.defer(ephemeral=False)

    cursor.execute("SELECT name, description, price, role_required FROM items")
    articoli = cursor.fetchall()

    if not articoli:
        return await interaction.followup.send("🛒 Il negozio è attualmente vuoto.")

    embed = discord.Embed(title="🏪 Negozio del Server", color=discord.Color.green())
    for nome, desc, prezzo, ruolo_id in articoli:
        req_text = f"Richiede: <@&{ruolo_id}>" if ruolo_id != "None" else "Nessun requisito"
        embed.add_field(
            name=f"{nome} — {prezzo}$", 
            value=f"*{desc}*\n{req_text}", 
            inline=False
        )
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="compra", description="Acquista un oggetto dal negozio")
async def compra(interaction: Interaction, nome: str):
    # Defer privato per non intasare la chat con i tentativi di acquisto
    await interaction.response.defer(ephemeral=True)

    user_id = str(interaction.user.id)
    user_data = get_user_data(user_id) # Recupera wallet e bank
    wallet = user_data[1]

    # Cerca l'item nel database
    cursor.execute("SELECT name, price, role_required FROM items WHERE name = ?", (nome,))
    item = cursor.fetchone()

    if not item:
        return await interaction.followup.send("⚠️ Questo oggetto non esiste nel negozio.")

    nome_item, prezzo, ruolo_id = item

    # 1. Controllo disponibilità economica
    if wallet < prezzo:
        return await interaction.followup.send(f"⚠️ Non hai abbastanza soldi! Ti mancano {prezzo - wallet}$.")

    # 2. Controllo requisiti di ruolo
    if ruolo_id != "None":
        role = interaction.guild

# ================= GESTIONE SHOP (ADMIN) =================

@bot.tree.command(name="crea_item_shop", description="ADMIN - Aggiungi un oggetto al negozio")
@app_commands.describe(nome="Nome dell'oggetto", descrizione="Descrizione", prezzo="Prezzo in $", ruolo_richiesto="Ruolo necessario (opzionale)")
async def crea_item_shop(interaction: Interaction, nome: str, descrizione: str, prezzo: int, ruolo_richiesto: discord.Role = None):
    # Usiamo defer per evitare il timeout dei 3 secondi
    await interaction.response.defer(ephemeral=True)

    if not interaction.user.guild_permissions.administrator:
        return await interaction.followup.send("❌ Permessi insufficienti.")

    id_ruolo = str(ruolo_richiesto.id) if ruolo_richiesto else "None"
    
    try:
        cursor.execute("INSERT INTO items (name, description, price, role_required) VALUES (?, ?, ?, ?)", 
                       (nome, descrizione, prezzo, id_ruolo))
        conn.commit()
        await interaction.followup.send(f"✅ Item **{nome}** aggiunto al negozio per {prezzo}$.")
    except sqlite3.IntegrityError:
        await interaction.followup.send("⚠️ Un oggetto con questo nome esiste già nel negozio.")

@bot.tree.command(name="elimina_item_shop", description="ADMIN - Rimuovi un oggetto dal negozio")
async def elimina_item_shop(interaction: Interaction, nome: str):
    await interaction.response.defer(ephemeral=True)

    if not interaction.user.guild_permissions.administrator:
        return await interaction.followup.send("❌ Permessi insufficienti.")

    cursor.execute("DELETE FROM items WHERE name = ?", (nome,))
    conn.commit()
    await interaction.followup.send(f"🗑️ Item **{nome}** rimosso dal negozio.")



# ================= COMANDI ADMIN =================

@bot.tree.command(name="aggiungisoldi", description="ADMIN - Aggiungi soldi a un utente")
async def aggiungisoldi(interaction: Interaction, utente: discord.Member, importo: int):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("Non sei admin.", ephemeral=True)
    
    get_user_data(utente.id) # Assicura che l'utente esista nel DB
    cursor.execute("UPDATE users SET wallet = wallet + ? WHERE user_id = ?", (importo, str(utente.id)))
    conn.commit()
    await interaction.response.send_message(f"Aggiunti {importo}$ a {utente.mention}")

@bot.tree.command(name="aggiungiitem", description="ADMIN - Aggiungi item a un utente")
async def aggiungiitem(interaction: Interaction, utente: discord.Member, item: str, quantita: int):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("Non sei admin.", ephemeral=True)
    
    cursor.execute("SELECT quantity FROM inventory WHERE user_id = ? AND item_name = ?", (str(utente.id), item))
    res = cursor.fetchone()
    if res:
        cursor.execute("UPDATE inventory SET quantity = quantity + ? WHERE user_id = ? AND item_name = ?", (quantita, str(utente.id), item))
    else:
        cursor.execute("INSERT INTO inventory (user_id, item_name, quantity) VALUES (?, ?, ?)", (str(utente.id), item, quantita))
    conn.commit()
    await interaction.response.send_message(f"Aggiunti {quantita}x {item} a {utente.mention}")

# ================= COMANDI ECONOMIA =================

@bot.tree.command(name="cerca", description="Cerca oggetti nella spazzatura")
async def cerca(interaction: Interaction):
    import random
    user_id = str(interaction.user.id)
    loot_pool = [("Rame", 10), ("Ferro", 30), ("Plastica", 30), ("Nulla", 30)]
    
    roll = random.randint(1, 100)
    current = 0
    trovato = "Nulla"

    for item, chance in loot_pool:
        current += chance
        if roll <= current:
            trovato = item
            break

    if trovato == "Nulla":
        return await interaction.response.send_message("Non hai trovato nulla.")

    cursor.execute("SELECT quantity FROM inventory WHERE user_id = ? AND item_name = ?", (user_id, trovato))
    if cursor.fetchone():
        cursor.execute("UPDATE inventory SET quantity = quantity + 1 WHERE user_id = ? AND item_name = ?", (user_id, trovato))
    else:
        cursor.execute("INSERT INTO inventory (user_id, item_name, quantity) VALUES (?, ?, 1)", (user_id, trovato))
    conn.commit()
    await interaction.response.send_message(f"Hai trovato: {trovato}!")

@bot.tree.command(name="inventario", description="Visualizza il tuo inventario")
async def inventario(interaction: Interaction):
    user = get_user_data(interaction.user.id)
    cursor.execute("SELECT item_name, quantity FROM inventory WHERE user_id = ?", (str(interaction.user.id),))
    items = cursor.fetchall()
    
    desc = "\n".join([f"**{i[0]}**: x{i[1]}" for i in items]) if items else "Vuoto"
    embed = discord.Embed(title=f"Inventario di {interaction.user.display_name}", color=discord.Color.blue())
    embed.add_field(name="💰 Portafoglio", value=f"{user[1]}$", inline=True)
    embed.add_field(name="🏦 Banca", value=f"{user[2]}$", inline=True)
    embed.add_field(name="📦 Oggetti", value=desc, inline=False)
    await interaction.response.send_message(embed=embed)

# ================= GESTIONE CASSA DI RUOLO =================

@bot.tree.command(name="deposita_cassa", description="Deposita soldi nella cassa del tuo ruolo")
async def depositasoldi(interaction: Interaction, importo: int):
    user = get_user_data(interaction.user.id)
    if user[1] < importo:
        return await interaction.response.send_message("Non hai abbastanza soldi nel portafoglio.", ephemeral=True)

    # Controlla se l'utente ha un ruolo con deposito
    user_role_ids = [str(r.id) for r in interaction.user.roles]
    cursor.execute("SELECT role_id FROM depositi")
    available_deposits = [row[0] for row in cursor.fetchall()]
    
    target_role = next((r for r in user_role_ids if r in available_deposits), None)
    if not target_role:
        return await interaction.response.send_message("Non hai un ruolo associato a un deposito.", ephemeral=True)

    cursor.execute("UPDATE users SET wallet = wallet - ? WHERE user_id = ?", (importo, str(interaction.user.id)))
    cursor.execute("UPDATE depositi SET money = money + ? WHERE role_id = ?", (importo, target_role))
    conn.commit()
    await interaction.response.send_message(f"Hai depositato {importo}$ nella cassa di fazione.")

@bot.tree.command(name="creadeposito", description="ADMIN - Crea un deposito per un ruolo")
async def creadeposito(interaction: Interaction, ruolo: discord.Role):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("Non sei admin.", ephemeral=True)

    try:
        cursor.execute("INSERT INTO depositi (role_id, money) VALUES (?, ?)", (str(ruolo.id), 0))
        conn.commit()
        await interaction.response.send_message(f"Deposito creato per {ruolo.mention}")
    except sqlite3.IntegrityError:
        await interaction.response.send_message("Questo ruolo ha già un deposito.")

# ================= COMANDO RIMUOVI SOLDI (ADMIN) =================

@bot.tree.command(name="rimuovisoldi", description="ADMIN - Rimuovi soldi dal portafoglio di un utente")
@app_commands.describe(utente="L'utente a cui togliere i soldi", importo="Quantità da rimuovere")
async def rimuovisoldi(interaction: Interaction, utente: discord.Member, importo: int):
    # Controllo permessi Admin
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ Non hai i permessi necessari per usare questo comando.", ephemeral=True)
    
    if importo <= 0:
        return await interaction.response.send_message("⚠️ Inserisci un importo maggiore di zero.", ephemeral=True)

    # Assicuriamoci che l'utente sia presente nel database
    user = get_user_data(utente.id)
    current_wallet = user[1]

    # Controllo se l'utente ha abbastanza soldi (opzionale)
    if current_wallet < importo:
        # Se preferisci che i soldi vadano in negativo, commenta le due righe sotto
        return await interaction.response.send_message(f"⚠️ {utente.mention} ha solo {current_wallet}$ nel portafoglio. Non puoi rimuoverne {importo}$.", ephemeral=True)

    # Esecuzione della rimozione
    cursor.execute("UPDATE users SET wallet = wallet - ? WHERE user_id = ?", (importo, str(utente.id)))
    conn.commit()

    await interaction.response.send_message(f"✅ Rimossi {importo}$ dal portafoglio di {utente.mention}. Nuovo saldo: {current_wallet - importo}$.")


# ================= READY & FLASK =================

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Bot connesso come {bot.user}")

app = Flask("")
@app.route('/')
def main(): return "Bot is Online!"

def run():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

def keep_alive():
    t = threading.Thread(target=run)
    t.start()

if __name__ == "__main__":
    keep_alive()
    bot.run(TOKEN)
