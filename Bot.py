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

@bot.tree.command(name="cerca", description="Cerca oggetti nella spazzatura con probabilità")
async def cerca(interaction: discord.Interaction):
    import random

    user_id = str(interaction.user.id)

    # Lista loot con probabilità (in percentuale)
    loot = [
        ("Rame", 10),       # bassa probabilità
        ("Ferro", 30),      # media probabilità
        ("Plastica", 30),   # media probabilità
        ("Nulla", 30)       # non trovare nulla
    ]

    roll = random.randint(1, 100)
    current = 0
    trovato = "Nulla"

    for item, chance in loot:
        current += chance
        if roll <= current:
            trovato = item
            break

    if trovato == "Nulla":
        await interaction.response.send_message("Non hai trovato nulla.")
        return

    # Aggiungi l'item all'inventario
    cursor.execute("SELECT quantity FROM inventory WHERE user_id = ? AND item_name = ?", (user_id, trovato))
    res = cursor.fetchone()
    if res:
        cursor.execute("UPDATE inventory SET quantity = quantity + 1 WHERE user_id = ? AND item_name = ?", (user_id, trovato))
    else:
        cursor.execute("INSERT INTO inventory (user_id, item_name, quantity) VALUES (?, ?, ?)", (user_id, trovato, 1))
    conn.commit()

    await interaction.response.send_message(f"Hai trovato: {trovato}!")
conn.commit()
@bot.tree.command(name="aggiungisoldi", description="ADMIN - Aggiungi soldi a un utente")
@app_commands.describe(utente="Utente da premiare", importo="Quantità di soldi")
async def aggiungisoldi(interaction: discord.Interaction, utente: discord.Member, importo: int):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("Non sei admin.", ephemeral=True)
        return
    cursor.execute("UPDATE users SET wallet = wallet + ? WHERE user_id = ?", (importo, str(utente.id)))
    conn.commit()
    await interaction.response.send_message(f"Aggiunti {importo}$ a {utente.mention}")
    @bot.tree.command(name="rimuovisoldi", description="ADMIN - Rimuovi soldi a un utente")
@app_commands.describe(utente="Utente target", importo="Quantità di soldi")
async def rimuovisoldi(interaction: discord.Interaction, utente: discord.Member, importo: int):
    # Controllo permessi admin
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("Non sei admin.", ephemeral=True)
        return

    # Aggiorna il wallet dell'utente
    cursor.execute(
        "UPDATE users SET wallet = wallet - ? WHERE user_id = ?",
        (importo, str(utente.id))
    )
    conn.commit()

    # Messaggio di conferma
    await interaction.response.send_message(f"Rimossi {importo}$ a {utente.mention}", ephemeral=True)
    @bot.tree.command(name="aggiungiitem", description="ADMIN - Aggiungi item a un utente")
@app_commands.describe(utente="Utente target", item="Nome item", quantita="Quantità")
async def aggiungiitem(interaction: discord.Interaction, utente: discord.Member, item: str, quantita: int):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("Non sei admin.", ephemeral=True)
        return
    cursor.execute("SELECT quantity FROM inventory WHERE user_id = ? AND item_name = ?", (str(utente.id), item))
    res = cursor.fetchone()
    if res:
        cursor.execute("UPDATE inventory SET quantity = quantity + ? WHERE user_id = ? AND item_name = ?", (quantita, str(utente.id), item))
    else:
        cursor.execute("INSERT INTO inventory (user_id, item_name, quantity) VALUES (?, ?, ?)", (str(utente.id), item, quantita))
    conn.commit()
    await interaction.response.send_message(f"Aggiunti {quantita}x {item} a {utente.mention}")
    @bot.tree.command(name="rimuoviitem", description="ADMIN - Rimuovi item da un utente")
@app_commands.describe(utente="Utente target", item="Nome item", quantita="Quantità")
async def rimuoviitem(interaction: discord.Interaction, utente: discord.Member, item: str, quantita: int):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("Non sei admin.", ephemeral=True)
        return
    cursor.execute("SELECT quantity FROM inventory WHERE user_id = ? AND item_name = ?", (str(utente.id), item))
    res = cursor.fetchone()
    if not res:
        await interaction.response.send_message(f"{utente.mention} non possiede {item}.", ephemeral=True)
        return
    nuova_qta = res[0] - quantita
    if nuova_qta > 0:
        cursor.execute("UPDATE inventory SET quantity = ? WHERE user_id = ? AND item_name = ?", (nuova_qta, str(utente.id), item))
    else:
        cursor.execute("DELETE FROM inventory WHERE user_id = ? AND item_name = ?", (str(utente.id), item))
    conn.commit()
    await interaction.response.send_message(f"Rimossi {quantita}x {item} a {utente.mention}")
    @bot.tree.command(name="depositacassa", description="Deposita soldi nel deposito del tuo ruolo")
@app_commands.describe(importo="Quantità di soldi da depositare")
async def depositasoldi(interaction: Interaction, importo: int):
    user = get_user(interaction.user.id)
    if user[1] < importo:
        await interaction.response.send_message("Non hai abbastanza soldi.", ephemeral=True)
        return
@bot.tree.command(name="prelevacassa", description="Preleva soldi dal deposito del tuo ruolo")
@app_commands.describe(importo="Quantità di soldi da prelevare")
async def prelevasoldi(interaction: Interaction, importo: int):
    # Trova deposito dell'utente
    ruoli_user = [r.id for r in interaction.user.roles]
    cursor.execute("SELECT role_id, money FROM depositi")
    depositi = cursor.fetchall()
    deposito_possibile = next((d for d in depositi if int(d[0]) in ruoli_user), None)
    if not deposito_possibile:
        await interaction.response.send_message("Non hai accesso a nessun deposito.", ephemeral=True)
        return

    role_id, soldi = deposito_possibile
    if soldi < importo:
        await interaction.response.send_message("Il deposito non ha abbastanza soldi.", ephemeral=True)
        return

    cursor.execute("UPDATE depositi SET money = money - ? WHERE role_id = ?", (importo, role_id))
    cursor.execute("UPDATE users SET wallet = wallet + ? WHERE user_id = ?", (importo, str(interaction.user.id)))
    conn.commit()
    await interaction.response.send_message(f"Hai prelevato {importo}$ dal deposito del ruolo.", ephemeral=True)
    # Trova deposito dell'utente
    ruoli_user = [r.id for r in interaction.user.roles]
    cursor.execute("SELECT role_id, money FROM depositi")
    depositi = cursor.fetchall()
    deposito_possibile = next((d for d in depositi if int(d[0]) in ruoli_user), None)
    if not deposito_possibile:
        await interaction.response.send_message("Non hai accesso a nessun deposito.", ephemeral=True)
        return

    role_id, soldi = deposito_possibile
    cursor.execute("UPDATE users SET wallet = wallet - ? WHERE user_id = ?", (importo, str(interaction.user.id)))
    cursor.execute("UPDATE depositi SET money = money + ? WHERE role_id = ?", (importo, role_id))
    conn.commit()
    await interaction.response.send_message(f"Hai depositato {importo}$ nel deposito del ruolo.", ephemeral=True)
@bot.tree.command(name="depositaitemdep", description="Deposita un item nel deposito del tuo ruolo")
@app_commands.describe(item="Nome item", quantita="Quantità da depositare")
async def depositaitem(inter: Interaction, item: str, quantita: int):
    user_id = str(inter.user.id)
    cursor.execute("SELECT quantity FROM inventory WHERE user_id = ? AND item_name = ?", (user_id, item))
    res = cursor.fetchone()
    if not res or res[0] < quantita:
        await interaction.response.send_message("Non hai abbastanza di questo item.", ephemeral=True)
        return
@bot.tree.command(name="prelevaitemdep", description="Preleva un item dal deposito del tuo ruolo")
@app_commands.describe(item="Nome item", quantita="Quantità da prelevare")
async def prelevaitem(inter: Interaction, item: str, quantita: int):
    table_name = f"deposit_items_{inter.user.guild.id}_{inter.user.id}"
    cursor.execute(f"SELECT quantity FROM {table_name} WHERE item_name = ?", (item,))
    res = cursor.fetchone()
    if not res or res[0] < quantita:
        await interaction.response.send_message("Non ci sono abbastanza item nel deposito.", ephemeral=True)
        return

    # Riduci dal deposito
    nuova_qta = res[0] - quantita
    if nuova_qta > 0:
        cursor.execute(f"UPDATE {table_name} SET quantity = ? WHERE item_name = ?", (nuova_qta, item))
    else:
        cursor.execute(f"DELETE FROM {table_name} WHERE item_name = ?", (item,))

    # Aggiungi all'inventario utente
    cursor.execute("SELECT quantity FROM inventory WHERE user_id = ? AND item_name = ?", (str(inter.user.id), item))
    res_inv = cursor.fetchone()
    if res_inv:
        cursor.execute("UPDATE inventory SET quantity = quantity + ? WHERE user_id = ? AND item_name = ?", (quantita, str(inter.user.id), item))
    else:
        cursor.execute("INSERT INTO inventory (user_id, item_name, quantity) VALUES (?, ?, ?)", (str(inter.user.id), item, quantita))
    conn.commit()
    await interaction.response.send_message(f"Hai prelevato {quantita}x {item} dal deposito.", ephemeral=True)
    # Riduci dall'inventario
    nuova_qta = res[0] - quantita
    if nuova_qta > 0:
        cursor.execute("UPDATE inventory SET quantity = ? WHERE user_id = ? AND item_name = ?", (nuova_qta, user_id, item))
    else:
        cursor.execute("DELETE FROM inventory WHERE user_id = ? AND item_name = ?", (user_id, item))

    # Aggiungi al deposito
    table_name = f"deposit_items_{inter.user.guild.id}_{inter.user.id}"  # tabella unica per deposito utente/ruolo
    cursor.execute(f"CREATE TABLE IF NOT EXISTS {table_name} (item_name TEXT PRIMARY KEY, quantity INTEGER)")
    cursor.execute(f"INSERT INTO {table_name} (item_name, quantity) VALUES (?, ?) ON CONFLICT(item_name) DO UPDATE SET quantity = quantity + ?",
                   (item, quantita, quantita))
    conn.commit()
    await interaction.response.send_message(f"Hai depositato {quantita}x {item} nel deposito.", ephemeral=True)
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

# import os
from flask import Flask
import threading

# ---------- Flask ----------
app = Flask("Horizon Economy Bot")

@app.route("/")
def home():
    return "Bot online e funzionante!"

# Funzione per far partire Flask in un thread separato
def run_flask():
    port = int(os.environ.get("PORT", 5000))  # prende la porta da Render, default 5000
    app.run(host="0.0.0.0", port=port)

# Avvia Flask in background così Discord non viene bloccato
threading.Thread(target=run_flask).start()
bot.run(TOKEN)
