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
@bot.tree.command(name="deposito", description="Apri il deposito del tuo ruolo")
async def deposito(interaction: Interaction):
    await interaction.response.defer(ephemeral=True)

    # Controllo ruoli: trova i ruoli che hanno un deposito
    cursor.execute("SELECT role_id FROM depositi")
    deposit_roles = [int(r[0]) for r in cursor.fetchall()]
    user_roles = [r.id for r in interaction.user.roles]
    ruoli_possibili = [r for r in user_roles if r in deposit_roles]

    if not ruoli_possibili:
        await interaction.followup.send("Non hai il ruolo richiesto per accedere a nessun deposito.", ephemeral=True)
        return

    # Se ha più ruoli con deposito, menu per scegliere
    options_ruoli = [discord.SelectOption(label=f"<@&{r}>", value=str(r)) for r in ruoli_possibili]

    class RoleSelect(Select):
        def __init__(self):
            super().__init__(placeholder="Seleziona il ruolo del deposito", min_values=1, max_values=1, options=options_ruoli)

        async def callback(self, role_inter: Interaction):
            role_id = int(self.values[0])

            # Menu scelta soldi o item
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
                    else:  # item
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
                                # Modalità scelta: preleva o deposita item
                                modal = Modal(title="Gestione item deposito")
                                quantity_input = TextInput(label="Quantità da prelevare", style=discord.TextStyle.short, placeholder="Inserisci quantità")
                                modal.add_item(quantity_input)

                                async def modal_callback(modal_inter: Interaction):
                                    try:
                                        qty = int(quantity_input.value)
                                    except:
                                        await modal_inter.response.send_message("Quantità non valida.", ephemeral=True)
                                        return
                                    if qty <= 0:
                                        await modal_inter.response.send_message("Quantità non valida.", ephemeral=True)
                                        return
                                    cursor.execute("SELECT quantity FROM inventory WHERE user_id = ? AND item_name = ?", (f"deposit_{role_id}", nome_item))
                                    current = cursor.fetchone()[0]
                                    if qty > current:
                                        await modal_inter.response.send_message("Non ci sono abbastanza item nel deposito.", ephemeral=True)
                                        return
                                    # Rimuove dal deposito e aggiunge all'inventario dell'utente
                                    cursor.execute("UPDATE inventory SET quantity = quantity - ? WHERE user_id = ? AND item_name = ?", (qty, f"deposit_{role_id}", nome_item))
                                    cursor.execute("DELETE FROM inventory WHERE user_id = ? AND item_name = ? AND quantity <= 0", (f"deposit_{role_id}", nome_item))
                                    cursor.execute("SELECT quantity FROM inventory WHERE user_id = ? AND item_name = ?", (str(interaction.user.id), nome_item))
                                    res = cursor.fetchone()
                                    if res:
                                        cursor.execute("UPDATE inventory SET quantity = quantity + ? WHERE user_id = ? AND item_name = ?", (qty, str(interaction.user.id), nome_item))
                                    else:
                                        cursor.execute("INSERT INTO inventory (user_id, item_name, quantity) VALUES (?, ?, ?)", (str(interaction.user.id), nome_item, qty))
                                    conn.commit()
                                    await modal_inter.response.send_message(f"Hai prelevato {qty} {nome_item} dal deposito.", ephemeral=True)

                                modal.on_submit = modal_callback
                                await item_inter.response.send_modal(modal)

                        view_item = View()
                        view_item.add_item(ItemSelect())
                        await choice_inter.response.send_message("Scegli l'item da prelevare dal deposito:", view=view_item, ephemeral=True)

            view_choice = View()
            view_choice.add_item(ChoiceSelect())
            await role_inter.response.send_message("Cosa vuoi fare?", view=view_choice, ephemeral=True)

    view_role = View()
    view_role.add_item(RoleSelect())
    await interaction.followup.send("Seleziona il ruolo del deposito:", view=view_role, ephemeral=True)
# ================= SHOP =================
@bot.tree.command(name="negozio", description="Visualizza gli oggetti acquistabili")
async def negozio(interaction: Interaction):
    await interaction.response.defer(ephemeral=True)
    cursor.execute("SELECT name, description, price, role_required FROM items")
    items = cursor.fetchall()
    if not items:
        await interaction.followup.send("Nessun oggetto disponibile.", ephemeral=True)
        return
    desc = ""
    for item in items:
        role_mention = f"<@&{item[3]}>" if item[3] else "Nessuno"
        desc += f"**{item[0]}** - {item[2]}$ - Ruolo richiesto: {role_mention}\n{item[1]}\n\n"
    embed = discord.Embed(title="🛒 Negozio", description=desc, color=discord.Color.green())
    await interaction.followup.send(embed=embed, ephemeral=True)

# ====== COMPRA ITEM ======
@bot.tree.command(name="compra", description="Compra un item dallo shop")
async def compra(interaction: Interaction):
    await interaction.response.defer(ephemeral=True)
    cursor.execute("SELECT name, price, role_required FROM items")
    items = cursor.fetchall()
    if not items:
        await interaction.followup.send("Nessun item disponibile.", ephemeral=True)
        return

    options = []
    for item in items:
        # Se c'è un ruolo richiesto, controlla se l'utente ce l'ha
        if item[2] and not discord.utils.get(interaction.user.roles, id=int(item[2])):
            continue
        options.append(discord.SelectOption(label=f"{item[0]} - {item[1]}$", value=item[0]))

    if not options:
        await interaction.followup.send("Non hai il ruolo richiesto per comprare nessun item.", ephemeral=True)
        return

    class CompraSelect(Select):
        def __init__(self):
            super().__init__(placeholder="Seleziona l'item da comprare", min_values=1, max_values=1, options=options)

        async def callback(self, select_interaction: Interaction):
            nome_item = self.values[0]
            cursor.execute("SELECT price FROM items WHERE name = ?", (nome_item,))
            prezzo = cursor.fetchone()[0]
            user = get_user(interaction.user.id)
            if user[1] < prezzo:
                await select_interaction.response.send_message("Non hai abbastanza soldi.", ephemeral=True)
                return
            cursor.execute("UPDATE users SET wallet = wallet - ? WHERE user_id = ?", (prezzo, str(interaction.user.id)))
            cursor.execute("SELECT quantity FROM inventory WHERE user_id = ? AND item_name = ?", (str(interaction.user.id), nome_item))
            result = cursor.fetchone()
            if result:
                cursor.execute("UPDATE inventory SET quantity = quantity + 1 WHERE user_id = ? AND item_name = ?", (str(interaction.user.id), nome_item))
            else:
                cursor.execute("INSERT INTO inventory (user_id, item_name, quantity) VALUES (?, ?, ?)", (str(interaction.user.id), nome_item, 1))
            conn.commit()
            await select_interaction.response.send_message(f"Hai comprato **{nome_item}** per {prezzo}$!", ephemeral=True)

    view = View()
    view.add_item(CompraSelect())
    await interaction.followup.send("Scegli un item da comprare:", view=view, ephemeral=True)

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
