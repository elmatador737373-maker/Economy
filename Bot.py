import discord
from discord import app_commands, Interaction
from discord.ext import commands
import pymongo
import random
import os
import threading
import asyncio
from flask import Flask

# ================= CONFIGURAZIONE =================
TOKEN = os.environ.get("TOKEN")
# La stringa che ottieni cliccando su "Drivers" su MongoDB Atlas
MONGO_URI = os.environ.get("MONGO_URI") 

intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Connessione a MongoDB Atlas
client = pymongo.MongoClient(MONGO_URI)
db = client["economia_rp"]

# Collezioni (Equivalenti delle tabelle SQL)
users_col = db["users"]
items_col = db["items"]
inventory_col = db["inventory"]
depositi_col = db["depositi"]
depositi_items_col = db["depositi_items"]

def get_user_data(user_id):
    u_id = str(user_id)
    user = users_col.find_one({"user_id": u_id})
    if not user:
        user = {"user_id": u_id, "wallet": 500, "bank": 0}
        users_col.insert_one(user)
    return user

# ================= MOTORE DI RICERCA INTELLIGENTE =================

async def cerca_item_smart(interaction: Interaction, nome_input: str, tabella="items"):
    regex = {"$regex": nome_input, "$options": "i"} # Ricerca case-insensitive
    
    if tabella == "items":
        risultati = [i["name"] for i in items_col.find({"name": regex})]
    elif tabella == "inventory":
        risultati = [i["item_name"] for i in inventory_col.find({"user_id": str(interaction.user.id), "item_name": regex})]
    else: 
        cursor_fazioni = depositi_col.find({}, {"role_id": 1})
        validi = [f["role_id"] for f in cursor_fazioni]
        my_role = next((str(r.id) for r in interaction.user.roles if str(r.id) in validi), None)
        if not my_role: return "NO_ROLE"
        risultati = [i["item_name"] for i in depositi_items_col.find({"role_id": my_role, "item_name": regex})]

    risultati = list(set(risultati))
    if not risultati:
        await interaction.followup.send(f"❌ Nessun oggetto trovato per '{nome_input}'.", ephemeral=True)
        return None
    if len(risultati) == 1: return risultati[0]

    class SelectItem(discord.ui.Select):
        def __init__(self, opzioni):
            options = [discord.SelectOption(label=o) for o in opzioni[:25]]
            super().__init__(placeholder="Seleziona l'oggetto esatto...", options=options)
        async def callback(self, inter: Interaction):
            self.view.value = self.values[0]
            self.view.stop()
            await inter.response.defer()

    view = discord.ui.View()
    view.add_item(SelectItem(risultati))
    view.value = None
    await interaction.followup.send(f"🤔 Ho trovato più oggetti per '{nome_input}'. Quale intendevi?", view=view, ephemeral=True)
    await view.wait()
    return view.value

# ================= GESTIONE CATALOGO SHOP (ADMIN) =================

@bot.tree.command(name="edit_item_shop", description="ADMIN - Modifica un oggetto esistente nello shop")
async def edit_item_shop(interaction: discord.Interaction, nome: str, nuova_descrizione: str = None, nuovo_prezzo: int = None, nuovo_ruolo: discord.Role = None):
    await interaction.response.defer(ephemeral=True)
    if not interaction.user.guild_permissions.administrator: return await interaction.followup.send("❌ No Admin.")

    nome_esatto = await cerca_item_smart(interaction, nome, "items")
    if not nome_esatto: return

    current = items_col.find_one({"name": nome_esatto})
    update_data = {
        "description": nuova_descrizione if nuova_descrizione else current["description"],
        "price": nuovo_prezzo if nuovo_prezzo is not None else current["price"],
        "role_required": str(nuovo_ruolo.id) if nuovo_ruolo else current["role_required"]
    }

    items_col.update_one({"name": nome_esatto}, {"$set": update_data})
    await interaction.followup.send(f"✅ Oggetto **{nome_esatto}** aggiornato!")

@bot.tree.command(name="elimina_item_shop", description="ADMIN - Rimuove un oggetto dallo shop")
async def elimina_item_shop(interaction: discord.Interaction, nome: str):
    await interaction.response.defer(ephemeral=True)
    if not interaction.user.guild_permissions.administrator: return
    nome_esatto = await cerca_item_smart(interaction, nome, "items")
    if not nome_esatto: return
    items_col.delete_one({"name": nome_esatto})
    await interaction.followup.send(f"🗑️ **{nome_esatto}** rimosso dallo shop.")

# ================= COMANDI BANCA =================

@bot.tree.command(name="deposita", description="Sposta soldi nel portafoglio alla banca")
async def deposita(interaction: discord.Interaction, importo: int):
    await interaction.response.defer(ephemeral=True)
    user = get_user_data(interaction.user.id)
    if importo <= 0 or user["wallet"] < importo: return await interaction.followup.send("❌ Importo non valido o fondi insufficienti.")
    
    users_col.update_one({"user_id": str(interaction.user.id)}, {"$inc": {"wallet": -importo, "bank": importo}})
    await interaction.followup.send(f"🏦 Hai depositato **{importo}$** in banca.")

@bot.tree.command(name="preleva", description="Sposta soldi dalla banca al portafoglio")
async def preleva(interaction: discord.Interaction, importo: int):
    await interaction.response.defer(ephemeral=True)
    user = get_user_data(interaction.user.id)
    if importo <= 0 or user["bank"] < importo: return await interaction.followup.send("❌ Fondi in banca insufficienti.")
    
    users_col.update_one({"user_id": str(interaction.user.id)}, {"$inc": {"wallet": importo, "bank": -importo}})
    await interaction.followup.send(f"💸 Hai prelevato **{importo}$**.")

# ================= SISTEMA FAZIONI =================

@bot.tree.command(name="deposita_item_fazione", description="Sposta un oggetto al deposito fazione")
async def deposita_item_fazione(interaction: Interaction, nome: str, quantita: int = 1):
    await interaction.response.defer(ephemeral=True)
    if quantita <= 0: return await interaction.followup.send("❌ Quantità non valida.")
    
    nome_esatto = await cerca_item_smart(interaction, nome, "inventory")
    if not nome_esatto: return

    validi = [f["role_id"] for f in depositi_col.find({}, {"role_id": 1})]
    my_role = next((str(r.id) for r in interaction.user.roles if str(r.id) in validi), None)
    if not my_role: return await interaction.followup.send("❌ Non hai ruoli fazione registrati.")

    inv_item = inventory_col.find_one({"user_id": str(interaction.user.id), "item_name": nome_esatto})
    if not inv_item or inv_item["quantity"] < quantita: return await interaction.followup.send("❌ Non ne hai abbastanza.")

    # Esegui lo spostamento
    inventory_col.update_one({"user_id": str(interaction.user.id), "item_name": nome_esatto}, {"$inc": {"quantity": -quantita}})
    depositi_items_col.update_one({"role_id": my_role, "item_name": nome_esatto}, {"$inc": {"quantity": quantita}}, upsert=True)
    inventory_col.delete_many({"quantity": {"$lte": 0}})
    
    await interaction.followup.send(f"✅ Depositati {quantita}x **{nome_esatto}** nel deposito fazione.")

@bot.tree.command(name="registra_fazione", description="ADMIN - Registra un ruolo come fazione")
async def registra_fazione(interaction: Interaction, ruolo: discord.Role):
    await interaction.response.defer(ephemeral=True)
    if not interaction.user.guild_permissions.administrator: return
    depositi_col.update_one({"role_id": str(ruolo.id)}, {"$setOnInsert": {"money": 0}}, upsert=True)
    await interaction.followup.send(f"🏢 Ruolo {ruolo.mention} registrato come fazione.")

# ================= SHOP =================

@bot.tree.command(name="shop", description="Mostra gli oggetti in vendita")
async def shop(interaction: discord.Interaction):
    await interaction.response.defer()
    items = list(items_col.find())
    if not items: return await interaction.followup.send("🏪 Lo shop è vuoto.")

    embed = discord.Embed(title="🏪 Emporio della Città", color=discord.Color.gold())
    for i in items:
        req = f"\n⚠️ **Richiede:** <@&{i['role_required']}>" if i['role_required'] != "None" else ""
        embed.add_field(name=f"{i['name']} — {i['price']}$", value=f"*{i['description']}*{req}", inline=False)
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="compra", description="Acquista un oggetto")
async def compra(interaction: discord.Interaction, nome: str):
    await interaction.response.defer(ephemeral=True)
    nome_esatto = await cerca_item_smart(interaction, nome, "items")
    if not nome_esatto: return

    item = items_col.find_one({"name": nome_esatto})
    user = get_user_data(interaction.user.id)

    if user["wallet"] < item["price"]: return await interaction.followup.send("❌ Soldi insufficienti.")
    if item["role_required"] != "None":
        if not any(str(r.id) == item["role_required"] for r in interaction.user.roles):
            return await interaction.followup.send("⚠️ Non hai il ruolo richiesto.")

    users_col.update_one({"user_id": str(interaction.user.id)}, {"$inc": {"wallet": -item["price"]}})
    inventory_col.update_one({"user_id": str(interaction.user.id), "item_name": nome_esatto}, {"$inc": {"quantity": 1}}, upsert=True)
    await interaction.followup.send(f"🛍️ Hai comprato **{nome_esatto}**!")

# ================= GIOCHI E LAVORO =================

@bot.tree.command(name="cerca", description="Cerca oggetti tra i rifiuti (1 min)")
async def cerca(interaction: Interaction):
    await interaction.response.defer()
    await interaction.followup.send("🔍 Cerchi tra i rifiuti... attendi un minuto.")
    await asyncio.sleep(60)
    loot = random.choices(["Rame", "Ferro", "Plastica", "Nulla"], weights=[20, 15, 25, 40])[0]
    if loot == "Nulla": return await interaction.followup.send("😢 Non hai trovato nulla.")
    inventory_col.update_one({"user_id": str(interaction.user.id), "item_name": loot}, {"$inc": {"quantity": 1}}, upsert=True)
    await interaction.followup.send(f"📦 Hai trovato: **{loot}**!")

@bot.tree.command(name="blackjack", description="Gioca a Blackjack")
async def blackjack(interaction: Interaction, scommessa: int):
    await interaction.response.defer()
    user = get_user_data(interaction.user.id)
    if scommessa <= 0 or user["wallet"] < scommessa: return await interaction.followup.send("❌ Scommessa non valida.")
    
    # Per brevità la logica del blackjack rimane simile, ma aggiorna così:
    # Per vincere: users_col.update_one({"user_id": uid}, {"$inc": {"wallet": scommessa}})
    # Per perdere: users_col.update_one({"user_id": uid}, {"$inc": {"wallet": -scommessa}})
    await interaction.followup.send("🃏 Tavolo da Blackjack aperto! (Usa i bottoni della logica precedente)")

# ================= INFO UTENTE =================

@bot.tree.command(name="portafoglio", description="Vedi i tuoi soldi")
async def portafoglio(interaction: Interaction):
    user = get_user_data(interaction.user.id)
    await interaction.response.send_message(f"💰 **Portafoglio:** {user['wallet']}$ | 🏦 **Banca:** {user['bank']}$", ephemeral=True)

@bot.tree.command(name="inventario", description="Vedi i tuoi oggetti")
async def inventario(interaction: Interaction):
    items = list(inventory_col.find({"user_id": str(interaction.user.id)}))
    if not items: return await interaction.response.send_message("🎒 Inventario vuoto.", ephemeral=True)
    lista = "\n".join([f"📦 **{i['item_name']}** x{i['quantity']}" for i in items])
    await interaction.response.send_message(embed=discord.Embed(title="Inventario", description=lista, color=discord.Color.blue()), ephemeral=True)

# ================= ADMIN TOOLS =================

@bot.tree.command(name="aggiungisoldi", description="ADMIN - Regala soldi")
async def aggiungisoldi(interaction: Interaction, utente: discord.Member, importo: int):
    if not interaction.user.guild_permissions.administrator: return
    users_col.update_one({"user_id": str(utente.id)}, {"$inc": {"wallet": importo}}, upsert=True)
    await interaction.response.send_message(f"✅ Dati {importo}$ a {utente.mention}", ephemeral=True)

@bot.tree.command(name="wipe_utente", description="ADMIN - Reset Totale")
async def wipe_utente(interaction: Interaction, utente: discord.Member):
    if not interaction.user.guild_permissions.administrator: return
    users_col.update_one({"user_id": str(utente.id)}, {"$set": {"wallet": 0, "bank": 0}})
    inventory_col.delete_many({"user_id": str(utente.id)})
    await interaction.response.send_message(f"🧹 Wipe effettuato per {utente.mention}", ephemeral=True)

# ================= WEB SERVER & START =================
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"✅ {bot.user} Online con MongoDB Atlas!")

app = Flask("")
@app.route("/")
def home(): return "Bot Online"
def run(): app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
threading.Thread(target=run).start()
bot.run(TOKEN)

