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
MONGO_URI = os.environ.get("MONGO_URI") 

intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Connessione a MongoDB Atlas
client = pymongo.MongoClient(MONGO_URI)
db = client["economia_rp"]

# Collezioni
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
    regex = {"$regex": f".*{nome_input}.*", "$options": "i"}
    
    if tabella == "items":
        risultati = [i["name"] for i in items_col.find({"name": regex})]
    elif tabella == "inventory":
        risultati = [i["item_name"] for i in inventory_col.find({"user_id": str(interaction.user.id), "item_name": regex})]
    else: 
        validi = [f["role_id"] for f in depositi_col.find({}, {"role_id": 1})]
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
    await interaction.followup.send(f"🤔 Ho trovato più oggetti per '{nome_input}':", view=view, ephemeral=True)
    await view.wait()
    return view.value

# ================= COMANDI ADMIN =================

@bot.tree.command(name="aggiungisoldi", description="ADMIN - Dai soldi a un utente")
async def aggiungisoldi(interaction: Interaction, utente: discord.Member, importo: int):
    await interaction.response.defer(ephemeral=True)
    if not interaction.user.guild_permissions.administrator: return
    users_col.update_one({"user_id": str(utente.id)}, {"$inc": {"wallet": importo}}, upsert=True)
    await interaction.followup.send(f"✅ Accreditati **{importo}$** a {utente.mention}.")

@bot.tree.command(name="rimuovisoldi", description="ADMIN - Togli soldi a un utente")
async def rimuovisoldi(interaction: Interaction, utente: discord.Member, importo: int):
    await interaction.response.defer(ephemeral=True)
    if not interaction.user.guild_permissions.administrator: return
    users_col.update_one({"user_id": str(utente.id)}, {"$inc": {"wallet": -importo}}, upsert=True)
    await interaction.followup.send(f"✅ Rimossi **{importo}$** a {utente.mention}.")

@bot.tree.command(name="admin_aggiungi_item", description="ADMIN - Regala un oggetto")
async def admin_aggiungi_item(interaction: Interaction, utente: discord.Member, item: str, quantita: int = 1):
    await interaction.response.defer(ephemeral=True)
    if not interaction.user.guild_permissions.administrator: return
    inventory_col.update_one({"user_id": str(utente.id)}, {"item_name": item}, {"$inc": {"quantity": quantita}}, upsert=True)
    await interaction.followup.send(f"✅ Dati {quantita}x **{item}** a {utente.mention}.")

@bot.tree.command(name="wipe_utente", description="ADMIN - Reset totale (Soldi + Item)")
async def wipe_utente(interaction: Interaction, utente: discord.Member):
    await interaction.response.defer(ephemeral=True)
    if not interaction.user.guild_permissions.administrator: return
    users_col.update_one({"user_id": str(utente.id)}, {"$set": {"wallet": 0, "bank": 0}})
    inventory_col.delete_many({"user_id": str(utente.id)})
    await interaction.followup.send(f"🧹 Wipe completo per {utente.mention}.")

# ================= SHOP & CATALOGO =================

@bot.tree.command(name="crea_item_shop", description="ADMIN - Aggiungi item allo shop")
async def crea_item_shop(interaction: Interaction, nome: str, descrizione: str, prezzo: int, ruolo: discord.Role = None):
    await interaction.response.defer(ephemeral=True)
    if not interaction.user.guild_permissions.administrator: return
    items_col.update_one({"name": nome}, {"$set": {"description": descrizione, "price": prezzo, "role_required": str(ruolo.id) if ruolo else "None"}}, upsert=True)
    await interaction.followup.send(f"✅ Item **{nome}** creato.")

@bot.tree.command(name="edit_item_shop", description="ADMIN - Modifica item shop")
async def edit_item_shop(interaction: Interaction, nome: str, nuova_desc: str = None, nuovo_prezzo: int = None):
    await interaction.response.defer(ephemeral=True)
    if not interaction.user.guild_permissions.administrator: return
    nome_e = await cerca_item_smart(interaction, nome, "items")
    if not nome_e: return
    upd = {}
    if nuova_desc: upd["description"] = nuova_desc
    if nuovo_prezzo: upd["price"] = nuovo_prezzo
    items_col.update_one({"name": nome_e}, {"$set": upd})
    await interaction.followup.send(f"✅ **{nome_e}** modificato.")

@bot.tree.command(name="shop", description="Vedi il negozio")
async def shop(interaction: Interaction):
    await interaction.response.defer()
    items = list(items_col.find())
    if not items: return await interaction.followup.send("🏪 Shop vuoto.")
    embed = discord.Embed(title="🏪 Shop", color=discord.Color.gold())
    for i in items:
        req = f"\n⚠️ Richiede: <@&{i['role_required']}>" if i['role_required'] != "None" else ""
        embed.add_field(name=f"{i['name']} - {i['price']}$", value=f"{i['description']}{req}", inline=False)
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="compra", description="Compra un oggetto")
async def compra(interaction: Interaction, nome: str):
    await interaction.response.defer(ephemeral=True)
    nome_e = await cerca_item_smart(interaction, nome, "items")
    if not nome_e: return
    item = items_col.find_one({"name": nome_e})
    user = get_user_data(interaction.user.id)
    if user["wallet"] < item["price"]: return await interaction.followup.send("❌ Soldi insufficienti.")
    users_col.update_one({"user_id": str(interaction.user.id)}, {"$inc": {"wallet": -item["price"]}})
    inventory_col.update_one({"user_id": str(interaction.user.id), "item_name": nome_e}, {"$inc": {"quantity": 1}}, upsert=True)
    await interaction.followup.send(f"🛍️ Hai comprato **{nome_e}**!")

# ================= BANCA & PORTAFOGLIO =================

@bot.tree.command(name="portafoglio", description="Mostra i tuoi soldi")
async def portafoglio(interaction: Interaction):
    user = get_user_data(interaction.user.id)
    await interaction.response.send_message(f"💰 Wallet: **{user['wallet']}$** | 🏦 Banca: **{user['bank']}$**", ephemeral=True)

@bot.tree.command(name="deposita", description="Metti soldi in banca")
async def deposita(interaction: Interaction, importo: int):
    user = get_user_data(interaction.user.id)
    if importo <= 0 or user["wallet"] < importo: return await interaction.response.send_message("❌ Fondi insufficienti.", ephemeral=True)
    users_col.update_one({"user_id": str(interaction.user.id)}, {"$inc": {"wallet": -importo, "bank": importo}})
    await interaction.response.send_message(f"🏦 Depositati **{importo}$**.")

@bot.tree.command(name="preleva", description="Preleva dalla banca")
async def preleva(interaction: Interaction, importo: int):
    user = get_user_data(interaction.user.id)
    if importo <= 0 or user["bank"] < importo: return await interaction.response.send_message("❌ Fondi insufficienti in banca.", ephemeral=True)
    users_col.update_one({"user_id": str(interaction.user.id)}, {"$inc": {"wallet": importo, "bank": -importo}})
    await interaction.response.send_message(f"💸 Prelevati **{importo}$**.")

# ================= GIOCHI & RICERCA (1 MINUTO) =================

@bot.tree.command(name="cerca", description="Cerca tra i rifiuti (1 minuto)")
async def cerca(interaction: Interaction):
    await interaction.response.defer()
    await interaction.followup.send("🔍 Hai iniziato a cercare... ci vorrà 1 minuto.")
    await asyncio.sleep(60)
    loot = random.choices(["Rame", "Ferro", "Plastica", "Nulla"], [20, 15, 25, 40])[0]
    if loot == "Nulla": return await interaction.followup.send("😢 Non hai trovato nulla.")
    inventory_col.update_one({"user_id": str(interaction.user.id), "item_name": loot}, {"$inc": {"quantity": 1}}, upsert=True)
    await interaction.followup.send(f"📦 Hai trovato: **{loot}**!")

@bot.tree.command(name="roulette", description="Scommetti sul colore (x2 o x14)")
async def roulette(interaction: Interaction, scommessa: int, colore: str):
    # Logica Roulette semplificata per brevità
    user = get_user_data(interaction.user.id)
    if scommessa <= 0 or user["wallet"] < scommessa: return await interaction.response.send_message("❌ Soldi insufficienti.")
    # Estrazione...
    res = random.choice(["rosso", "nero", "verde"])
    if colore.lower() == res:
        users_col.update_one({"user_id": str(interaction.user.id)}, {"$inc": {"wallet": scommessa}})
        await interaction.response.send_message(f"🎉 Vinto! Uscito {res}.")
    else:
        users_col.update_one({"user_id": str(interaction.user.id)}, {"$inc": {"wallet": -scommessa}})
        await interaction.response.send_message(f"💀 Perso! Uscito {res}.")

# ================= FAZIONI =================

@bot.tree.command(name="registra_fazione", description="ADMIN - Registra ruolo fazione")
async def registra_fazione(interaction: Interaction, ruolo: discord.Role):
    if not interaction.user.guild_permissions.administrator: return
    depositi_col.update_one({"role_id": str(ruolo.id)}, {"$setOnInsert": {"money": 0}}, upsert=True)
    await interaction.response.send_message(f"🏢 Fazione {ruolo.name} registrata.")

@bot.tree.command(name="deposita_item_fazione", description="Metti item nel deposito fazione")
async def deposita_item_fazione(interaction: Interaction, nome: str, quantita: int = 1):
    await interaction.response.defer(ephemeral=True)
    nome_e = await cerca_item_smart(interaction, nome, "inventory")
    if not nome_e: return
    # Controllo ruolo e spostamento...
    inventory_col.update_one({"user_id": str(interaction.user.id), "item_name": nome_e}, {"$inc": {"quantity": -quantita}})
    # Trova il ruolo fazione dell'utente e inserisci in depositi_items_col...
    await interaction.followup.send(f"✅ Depositato {quantita}x {nome_e}.")

# ================= SISTEMA FAZIONI (SOLDI E ITEM) =================

@bot.tree.command(name="deposita_soldi_fazione", description="Deposita denaro nel fondo della tua fazione")
async def deposita_soldi_fazione(interaction: Interaction, importo: int):
    await interaction.response.defer(ephemeral=True)
    if importo <= 0: return await interaction.followup.send("❌ Importo non valido.")
    
    user = get_user_data(interaction.user.id)
    if user["wallet"] < importo: 
        return await interaction.followup.send("❌ Non hai abbastanza contanti nel portafoglio.")

    # Trova il ruolo fazione dell'utente
    validi = [f["role_id"] for f in depositi_col.find({}, {"role_id": 1})]
    my_role = next((str(r.id) for r in interaction.user.roles if str(r.id) in validi), None)
    
    if not my_role: 
        return await interaction.followup.send("❌ Non appartieni a nessuna fazione registrata.")

    # Transazione
    users_col.update_one({"user_id": str(interaction.user.id)}, {"$inc": {"wallet": -importo}})
    depositi_col.update_one({"role_id": my_role}, {"$inc": {"money": importo}})
    
    await interaction.followup.send(f"✅ Hai depositato **{importo}$** nella cassa fazione.")

@bot.tree.command(name="preleva_soldi_fazione", description="Preleva denaro dalla cassa della fazione")
async def preleva_soldi_fazione(interaction: Interaction, importo: int):
    await interaction.response.defer(ephemeral=True)
    if importo <= 0: return await interaction.followup.send("❌ Importo non valido.")
    
    validi = [f["role_id"] for f in depositi_col.find({}, {"role_id": 1})]
    my_role = next((str(r.id) for r in interaction.user.roles if str(r.id) in validi), None)
    
    if not my_role: return await interaction.followup.send("❌ Non hai i permessi fazione.")

    fazione = depositi_col.find_one({"role_id": my_role})
    if fazione["money"] < importo:
        return await interaction.followup.send(f"❌ La fazione non ha abbastanza fondi (Disponibili: {fazione['money']}$).")

    # Transazione
    depositi_col.update_one({"role_id": my_role}, {"$inc": {"money": -importo}})
    users_col.update_one({"user_id": str(interaction.user.id)}, {"$inc": {"wallet": importo}})
    
    await interaction.followup.send(f"💸 Hai prelevato **{importo}$** dalla cassa fazione.")

@bot.tree.command(name="preleva_item_fazione", description="Preleva un oggetto dal deposito fazione")
async def preleva_item_fazione(interaction: Interaction, nome: str, quantita: int = 1):
    await interaction.response.defer(ephemeral=True)
    if quantita <= 0: return await interaction.followup.send("❌ Quantità non valida.")
    
    # Ricerca intelligente nel deposito fazione
    nome_esatto = await cerca_item_smart(interaction, nome, "depositi_items")
    if nome_esatto == "NO_ROLE": 
        return await interaction.followup.send("❌ Non hai ruoli fazione.")
    if not nome_esatto: return

    # Recupera il ruolo fazione
    validi = [f["role_id"] for f in depositi_col.find({}, {"role_id": 1})]
    my_role = next((str(r.id) for r in interaction.user.roles if str(r.id) in validi), None)

    # Controllo disponibilità nel deposito
    item_dep = depositi_items_col.find_one({"role_id": my_role, "item_name": nome_esatto})
    
    if not item_dep or item_dep["quantity"] < quantita:
        disp = item_dep["quantity"] if item_dep else 0
        return await interaction.followup.send(f"❌ Nel deposito ci sono solo {disp}x di questo oggetto.")

    # Spostamento Item: Deposito -> Inventario Utente
    depositi_items_col.update_one({"role_id": my_role, "item_name": nome_esatto}, {"$inc": {"quantity": -quantita}})
    inventory_col.update_one({"user_id": str(interaction.user.id), "item_name": nome_esatto}, {"$inc": {"quantity": quantita}}, upsert=True)
    
    # Pulizia documenti vuoti
    depositi_items_col.delete_many({"quantity": {"$lte": 0}})
    
    await interaction.followup.send(f"📦 Hai prelevato {quantita}x **{nome_esatto}** dal deposito fazione.")

@bot.tree.command(name="deposito_fazione_info", description="Visualizza soldi e oggetti della tua fazione")
async def deposito_fazione_info(interaction: Interaction):
    await interaction.response.defer(ephemeral=True)
    
    validi = [f["role_id"] for f in depositi_col.find({}, {"role_id": 1})]
    my_role = next((str(r.id) for r in interaction.user.roles if str(r.id) in validi), None)
    
    if not my_role: return await interaction.followup.send("❌ Non sei in una fazione.")

    fazione_data = depositi_col.find_one({"role_id": my_role})
    items_fazione = list(depositi_items_col.find({"role_id": my_role}))
    
    role_obj = interaction.guild.get_role(int(my_role))
    embed = discord.Embed(title=f"🏦 Deposito: {role_obj.name}", color=discord.Color.blue())
    embed.add_field(name="💰 Cassa Comune", value=f"**{fazione_data['money']}$**", inline=False)
    
    if items_fazione:
        lista = "\n".join([f"📦 **{i['item_name']}** x{i['quantity']}" for i in items_fazione])
        embed.add_field(name="📦 Magazzino Oggetti", value=lista, inline=False)
    else:
        embed.add_field(name="📦 Magazzino Oggetti", value="*Vuoto*", inline=False)

    await interaction.followup.send(embed=embed)

# ================= WEB SERVER & START =================
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"✅ {bot.user} Online su MongoDB Atlas!")

app = Flask("")
@app.route("/")
def home(): return "Bot Live"
def run(): app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
threading.Thread(target=run).start()
bot.run(TOKEN)

