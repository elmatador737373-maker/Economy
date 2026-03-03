import discord
from discord import app_commands, Interaction
from discord.ext import commands
from discord.ui import Select, View
import sqlite3
import random
import threading
from flask import Flask
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

cursor.execute("""
CREATE TABLE IF NOT EXISTS depositi_items (
    role_id TEXT,
    item_name TEXT,
    quantity INTEGER
)
""")

conn.commit()

# ================= FLASK PING =================
app = Flask("")

@app.route("/")
def home():
    return "Bot attivo!"

def run_flask():
    app.run(host="0.0.0.0", port=10000)

threading.Thread(target=run_flask).start()
# ================= RIMUOVI SOLDI / ITEM (ADMIN) =================
@bot.tree.command(name="rimuovi", description="ADMIN - Rimuovi soldi o item dall'utente")
@app_commands.describe(utente="Utente da modificare")
async def rimuovi(interaction: Interaction, utente: discord.Member):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("Non sei admin.", ephemeral=True)
        return

    tipo_options = [
        app_commands.Choice(name="💵 Soldi", value="soldi"),
        app_commands.Choice(name="🎒 Item", value="item")
    ]

    class TipoSelect(Select):
        def __init__(self):
            super().__init__(placeholder="Cosa vuoi rimuovere?", min_values=1, max_values=1, options=tipo_options)

        async def callback(self2, tipo_interaction: Interaction):
            if self2.values[0] == "soldi":
                # Menu per scegliere portafoglio o banca
                soldi_options = [
                    app_commands.Choice(name="Portafoglio", value="wallet"),
                    app_commands.Choice(name="Banca", value="bank")
                ]
                class WalletSelect(Select):
                    def __init__(self):
                        super().__init__(placeholder="Scegli dove togliere i soldi", min_values=1, max_values=1, options=soldi_options)
                    async def callback(self3, money_interaction: Interaction):
                        tipo_soldi = self3.values[0]
                        user = get_user(utente.id)
                        max_soldi = user[1] if tipo_soldi=="wallet" else user[2]
                        # Seleziona quantità da rimuovere
                        await money_interaction.response.send_modal(RemoveMoneyModal(utente, tipo_soldi, max_soldi))
                view_money = View()
                view_money.add_item(WalletSelect())
                await tipo_interaction.response.send_message("Scegli dove togliere i soldi:", view=view_money, ephemeral=True)

            elif self2.values[0] == "item":
                cursor.execute("SELECT item_name, quantity FROM inventory WHERE user_id = ?", (str(utente.id),))
                items = cursor.fetchall()
                if not items:
                    await tipo_interaction.response.send_message("L'utente non ha item.", ephemeral=True)
                    return
                item_options = [app_commands.Choice(name=f"{i[0]} x{i[1]}", value=i[0]) for i in items]
                class ItemSelect(Select):
                    def __init__(self):
                        super().__init__(placeholder="Seleziona l'item da rimuovere", min_values=1, max_values=1, options=item_options)
                    async def callback(self3, item_interaction: Interaction):
                        nome_item = self3.values[0]
                        cursor.execute("DELETE FROM inventory WHERE user_id = ? AND item_name = ?", (str(utente.id), nome_item))
                        conn.commit()
                        await item_interaction.response.send_message(f"Hai rimosso **{nome_item}** dall'inventario di {utente.mention}.", ephemeral=True)
                view_item = View()
                view_item.add_item(ItemSelect())
                await tipo_interaction.response.send_message("Seleziona l'item da rimuovere:", view=view_item, ephemeral=True)

    class RemoveMoneyModal(discord.ui.Modal, title="Rimuovi soldi"):
        def __init__(self, utente, tipo_soldi, max_soldi):
            super().__init__()
            self.utente = utente
            self.tipo_soldi = tipo_soldi
            self.add_item(discord.ui.TextInput(label=f"Quanti soldi rimuovere? (Max {max_soldi})", placeholder="Inserisci un numero", min_length=1, max_length=10))

        async def on_submit(self, modal_interaction: Interaction):
            try:
                importo = int(self.children[0].value)
                if importo <= 0:
                    await modal_interaction.response.send_message("Importo non valido.", ephemeral=True)
                    return
                user = get_user(self.utente.id)
                if self.tipo_soldi == "wallet":
                    if user[1] < importo:
                        await modal_interaction.response.send_message("L'utente non ha abbastanza soldi nel portafoglio.", ephemeral=True)
                        return
                    cursor.execute("UPDATE users SET wallet = wallet - ? WHERE user_id = ?", (importo, str(self.utente.id)))
                else:
                    if user[2] < importo:
                        await modal_interaction.response.send_message("L'utente non ha abbastanza soldi in banca.", ephemeral=True)
                        return
                    cursor.execute("UPDATE users SET bank = bank - ? WHERE user_id = ?", (importo, str(self.utente.id)))
                conn.commit()
                await modal_interaction.response.send_message(f"Hai rimosso {importo}$ da {self.utente.mention}.", ephemeral=True)
            except ValueError:
                await modal_interaction.response.send_message("Devi inserire un numero valido.", ephemeral=True)

    view = View()
    view.add_item(TipoSelect())
    await interaction.response.send_message(f"Seleziona cosa rimuovere dall'utente {utente.mention}:", view=view, ephemeral=True)
    
# ================= FUNZIONI =================
def get_user(user_id):
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (str(user_id),))
    user = cursor.fetchone()
    if not user:
        cursor.execute("INSERT INTO users (user_id) VALUES (?)", (str(user_id),))
        conn.commit()
        return (user_id, 500, 0)
    return user

# ================= COMANDI =================
# Inventario
@bot.tree.command(name="inventario", description="Visualizza il tuo inventario e i tuoi soldi")
async def inventario(interaction: Interaction):
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

# Dai soldi
@bot.tree.command(name="daisoldi", description="Dai soldi a un altro player")
@app_commands.describe(utente="Utente che riceve", importo="Quantità di soldi")
async def daisolidi(interaction: Interaction, utente: discord.Member, importo: int):
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

# Preleva soldi banca
@bot.tree.command(name="preleva", description="Preleva soldi dalla banca")
@app_commands.describe(importo="Quantità da prelevare")
async def preleva(interaction: Interaction, importo: int):
    user = get_user(interaction.user.id)
    if user[2] < importo:
        await interaction.response.send_message("Non hai abbastanza soldi in banca.", ephemeral=True)
        return
    cursor.execute("UPDATE users SET bank = bank - ?, wallet = wallet + ? WHERE user_id = ?", (importo, importo, str(interaction.user.id)))
    conn.commit()
    await interaction.response.send_message(f"Hai prelevato {importo}$ dalla banca.")

# Deposita soldi banca
@bot.tree.command(name="deposita", description="Deposita soldi in banca")
@app_commands.describe(importo="Quantità da depositare")
async def deposita(interaction: Interaction, importo: int):
    user = get_user(interaction.user.id)
    if user[1] < importo:
        await interaction.response.send_message("Non hai abbastanza soldi.", ephemeral=True)
        return
    cursor.execute("UPDATE users SET wallet = wallet - ?, bank = bank + ? WHERE user_id = ?", (importo, importo, str(interaction.user.id)))
    conn.commit()
    await interaction.response.send_message(f"Hai depositato {importo}$ in banca.")

# Shop
@bot.tree.command(name="negozio", description="Visualizza gli oggetti acquistabili")
async def negozio(interaction: Interaction):
    cursor.execute("SELECT name, description, price FROM items")
    items = cursor.fetchall()
    desc = ""
    for item in items:
        desc += f"**{item[0]}** - {item[2]}$\n{item[1]}\n\n"
    if desc == "":
        desc = "Nessun oggetto disponibile."
    embed = discord.Embed(title="🛒 Negozio", description=desc, color=discord.Color.green())
    await interaction.response.send_message(embed=embed)

# Compra item
@bot.tree.command(name="compra", description="Acquista un oggetto dal negozio")
@app_commands.describe(nome="Nome dell'oggetto da comprare")
async def compra(interaction: Interaction, nome: str):
    user = get_user(interaction.user.id)
    cursor.execute("SELECT price, role_required FROM items WHERE name = ?", (nome,))
    item = cursor.fetchone()
    if not item:
        await interaction.response.send_message("Oggetto non trovato nello shop.", ephemeral=True)
        return
    prezzo, ruolo_req = item
    if ruolo_req and not any(str(role.id) == ruolo_req for role in interaction.user.roles):
        await interaction.response.send_message("Non hai il ruolo richiesto per acquistare questo item.", ephemeral=True)
        return
    if user[1] < prezzo:
        await interaction.response.send_message("Non hai abbastanza soldi.", ephemeral=True)
        return
    cursor.execute("UPDATE users SET wallet = wallet - ? WHERE user_id = ?", (prezzo, str(interaction.user.id)))
    cursor.execute("SELECT quantity FROM inventory WHERE user_id = ? AND item_name = ?", (str(interaction.user.id), nome))
    inv_item = cursor.fetchone()
    if inv_item:
        cursor.execute("UPDATE inventory SET quantity = quantity + 1 WHERE user_id = ? AND item_name = ?", (str(interaction.user.id), nome))
    else:
        cursor.execute("INSERT INTO inventory (user_id, item_name, quantity) VALUES (?, ?, 1)", (str(interaction.user.id), nome))
    conn.commit()
    await interaction.response.send_message(f"Hai acquistato **{nome}** per {prezzo}$!")

# Cerca oggetti casuali
@bot.tree.command(name="cerca", description="Cerca oggetti nella spazzatura con probabilità")
async def cerca(interaction: Interaction):
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

# ================= CREA ITEM ADMIN (con menu scelta ruolo) =================
@bot.tree.command(name="creaitem", description="ADMIN - Crea un oggetto nello shop")
@app_commands.describe(nome="Nome oggetto", descrizione="Descrizione", prezzo="Prezzo")
async def creaitem(interaction: Interaction, nome: str, descrizione: str, prezzo: int):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("Non sei admin.", ephemeral=True)
        return
    options = [app_commands.Choice(name=role.name, value=str(role.id)) for role in interaction.guild.roles if not role.is_default()]

    class RoleSelect(Select):
        def __init__(self):
            super().__init__(placeholder="Seleziona il ruolo richiesto (opzionale)", min_values=0, max_values=1, options=options)
        async def callback(self, select_interaction: Interaction):
            ruolo_id = self.values[0] if self.values else None
            cursor.execute("INSERT OR REPLACE INTO items VALUES (?, ?, ?, ?)", (nome, descrizione, prezzo, ruolo_id))
            conn.commit()
            await select_interaction.response.send_message(f"Oggetto **{nome}** creato!", ephemeral=True)

    view = View()
    view.add_item(RoleSelect())
    await interaction.response.send_message("Scegli il ruolo richiesto:", view=view, ephemeral=True)

# ================= DEPOSITO RUOLO (menu soldi/item) =================
@bot.tree.command(name="deposito", description="Apri il deposito del tuo ruolo")
async def deposito(interaction: Interaction):
    ruoli_accessibili = [role for role in interaction.user.roles]
    cursor.execute("SELECT role_id FROM depositi")
    depositi = cursor.fetchall()
    options = [app_commands.Choice(name=role.name, value=str(role.id)) for role in ruoli_accessibili if str(role.id) in [r[0] for r in depositi]]
    if not options:
        await interaction.response.send_message("Non hai accesso a nessun deposito.", ephemeral=True)
        return

    class DepositoSelect(Select):
        def __init__(self):
            super().__init__(placeholder="Seleziona il deposito", min_values=1, max_values=1, options=options)
        async def callback(self, select_interaction: Interaction):
            role_id = self.values[0]
            tipo_options = [app_commands.Choice(name="💵 Soldi", value="soldi"), app_commands.Choice(name="🎒 Item", value="item")]
            class TipoSelect(Select):
                def __init__(self):
                    super().__init__(placeholder="Cosa vuoi prelevare?", min_values=1, max_values=1, options=tipo_options)
                async def callback(self2, tipo_interaction: Interaction):
                    tipo = self2.values[0]
                    if tipo == "soldi":
                        cursor.execute("SELECT money FROM depositi WHERE role_id = ?", (role_id,))
                        soldi = cursor.fetchone()[0]
                        if soldi <= 0:
                            await tipo_interaction.response.send_message("Non ci sono soldi nel deposito.", ephemeral=True)
                            return
                        cursor.execute("UPDATE depositi SET money = 0 WHERE role_id = ?", (role_id,))
                        cursor.execute("UPDATE users SET wallet = wallet + ? WHERE user_id = ?", (soldi, str(interaction.user.id)))
                        conn.commit()
                        await tipo_interaction.response.send_message(f"Hai prelevato {soldi}$ dal deposito.", ephemeral=True)
                    elif tipo == "item":
                        cursor.execute("SELECT item_name, quantity FROM depositi_items WHERE role_id = ?", (role_id,))
                        items = cursor.fetchall()
                        if not items:
                            await tipo_interaction.response.send_message("Non ci sono item nel deposito.", ephemeral=True)
                            return
                        item_options = [app_commands.Choice(name=f"{i[0]} x{i[1]}", value=i[0]) for i in items]
                        class ItemSelect(Select):
                            def __init__(self):
                                super().__init__(placeholder="Seleziona l'item da prelevare", min_values=1, max_values=1, options=item_options)
                            async def callback(self3, item_interaction: Interaction):
                                nome_item = self3.values[0]
                                cursor.execute("SELECT quantity FROM depositi_items WHERE role_id = ? AND item_name = ?", (role_id, nome_item))
                                qta = cursor.fetchone()[0]
                                cursor.execute("SELECT quantity FROM inventory WHERE user_id = ? AND item_name = ?", (str(interaction.user.id), nome_item))
                                inv_item = cursor.fetchone()
                                if inv_item:
                                    cursor.execute("UPDATE inventory SET quantity = quantity + ? WHERE user_id = ? AND item_name = ?", (qta, str(interaction.user.id), nome_item))
                                else:
                                    cursor.execute("INSERT INTO inventory (user_id, item_name, quantity) VALUES (?, ?, ?)", (str(interaction.user.id), nome_item, qta))
                                cursor.execute("DELETE FROM depositi_items WHERE role_id = ? AND item_name = ?", (role_id, nome_item))
                                conn.commit()
                                await item_interaction.response.send_message(f"Hai prelevato {qta} x {nome_item} dal deposito.", ephemeral=True)
                        view_item = View()
                        view_item.add_item(ItemSelect())
                        await tipo_interaction.response.send_message("Seleziona l'item:", view=view_item, ephemeral=True)

            view_tipo = View()
            view_tipo.add_item(TipoSelect())
            await select_interaction.response.send_message("Cosa vuoi prelevare?", view=view_tipo, ephemeral=True)

    view = View()
    view.add_item(DepositoSelect())
    await interaction.response.send_message("Seleziona il deposito:", view=view, ephemeral=True)

# ================= READY =================
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Bot online come {bot.user}")

bot.run(TOKEN)
