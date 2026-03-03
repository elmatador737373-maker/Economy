import discord
from discord import app_commands, Interaction
from discord.ext import commands
import psycopg2
from psycopg2.extras import RealDictCursor
import random
import os
import threading
import asyncio
from flask import Flask

# ================= CONFIGURAZIONE =================
TOKEN = os.environ.get("TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL")

intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Funzione per connettersi a Supabase
def get_db_connection():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    # Tabelle PostgreSQL
    cur.execute("CREATE TABLE IF NOT EXISTS users (user_id TEXT PRIMARY KEY, wallet INTEGER DEFAULT 500, bank INTEGER DEFAULT 0)")
    cur.execute("CREATE TABLE IF NOT EXISTS items (name TEXT PRIMARY KEY, description TEXT, price INTEGER, role_required TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS inventory (user_id TEXT, item_name TEXT, quantity INTEGER, PRIMARY KEY (user_id, item_name))")
    cur.execute("CREATE TABLE IF NOT EXISTS depositi (role_id TEXT PRIMARY KEY, money INTEGER DEFAULT 0)")
    cur.execute("CREATE TABLE IF NOT EXISTS depositi_items (role_id TEXT, item_name TEXT, quantity INTEGER, PRIMARY KEY (role_id, item_name))")
    conn.commit()
    cur.close()
    conn.close()

init_db()

def get_user_data(user_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM users WHERE user_id = %s", (str(user_id),))
    user = cur.fetchone()
    if not user:
        cur.execute("INSERT INTO users (user_id, wallet, bank) VALUES (%s, 500, 0) RETURNING *", (str(user_id),))
        user = cur.fetchone()
        conn.commit()
    cur.close()
    conn.close()
    return user

# ================= MOTORE DI RICERCA INTELLIGENTE =================

async def cerca_item_smart(interaction: Interaction, nome_input: str, tabella="items"):
    conn = get_db_connection()
    cur = conn.cursor()
    
    if tabella == "items":
        cur.execute("SELECT name FROM items WHERE name ILIKE %s", (f"%{nome_input}%",))
    elif tabella == "inventory":
        cur.execute("SELECT item_name FROM inventory WHERE user_id = %s AND item_name ILIKE %s", (str(interaction.user.id), f"%{nome_input}%"))
    else: 
        cur.execute("SELECT role_id FROM depositi")
        validi = [r[0] for r in cur.fetchall()]
        my_role = next((str(r.id) for r in interaction.user.roles if str(r.id) in validi), None)
        if not my_role: return "NO_ROLE"
        cur.execute("SELECT item_name FROM depositi_items WHERE role_id = %s AND item_name ILIKE %s", (my_role, f"%{nome_input}%"))

    risultati = list(set([r[0] for r in cur.fetchall()]))
    cur.close()
    conn.close()

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
    await interaction.followup.send(f"🤔 Più risultati per '{nome_input}':", view=view, ephemeral=True)
    await view.wait()
    return view.value
@bot.tree.command(name="crea_item_shop", description="ADMIN - Aggiungi un nuovo oggetto allo shop")
async def crea_item_shop(interaction: discord.Interaction, nome: str, descrizione: str, prezzo: int, ruolo: discord.Role = None):
    await interaction.response.defer(ephemeral=True)
    
    # Controllo permessi
    if not interaction.user.guild_permissions.administrator:
        return await interaction.followup.send("❌ Solo un Amministratore può aggiungere oggetti allo shop.")

    ruolo_id = str(ruolo.id) if ruolo else "None"
    
    conn = get_db_connection()
    if not conn:
        return await interaction.followup.send("❌ Errore di connessione al database.")
    
    try:
        cur = conn.cursor()
        # Utilizziamo ON CONFLICT per aggiornare l'oggetto se esiste già con lo stesso nome
        cur.execute("""
            INSERT INTO items (name, description, price, role_required) 
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (name) 
            DO UPDATE SET description = EXCLUDED.description, price = EXCLUDED.price, role_required = EXCLUDED.role_required
        """, (nome, descrizione, prezzo, ruolo_id))
        
        conn.commit()
        cur.close()
        conn.close()
        
        embed = discord.Embed(title="✅ Oggetto Creato", color=discord.Color.green())
        embed.add_field(name="Nome", value=nome)
        embed.add_field(name="Prezzo", value=f"{prezzo}$")
        embed.add_field(name="Requisito", value=ruolo.mention if ruolo else "Nessuno")
        
        await interaction.followup.send(embed=embed)
    except Exception as e:
        if conn: conn.close()
        await interaction.followup.send(f"❌ Errore durante la creazione: {e}")
@bot.tree.command(name="deposito_fazione", description="Scegli quale deposito fazione aprire")
async def deposito_fazione(interaction: Interaction):
    await interaction.response.defer(ephemeral=True)

    conn = get_db_connection()
    if not conn:
        return await interaction.followup.send("❌ Errore database.")
    
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT role_id FROM depositi")
    fazioni_registrate = [row['role_id'] for row in cur.fetchall()]

    # Trova tutti i ruoli dell'utente che sono registrati come fazioni
    miei_ruoli_fazione = [r for r in interaction.user.roles if str(r.id) in fazioni_registrate]

    if not miei_ruoli_fazione:
        cur.close()
        conn.close()
        return await interaction.followup.send("❌ Non appartieni a nessuna fazione registrata.")

    # Funzione interna per mostrare il deposito scelto
    async def mostra_deposito(inter: Interaction, role_id: str):
        conn_int = get_db_connection()
        cur_int = conn_int.cursor(cursor_factory=RealDictCursor)
        
        cur_int.execute("SELECT money FROM depositi WHERE role_id = %s", (role_id,))
        f_info = cur_int.fetchone()
        cur_int.execute("SELECT item_name, quantity FROM depositi_items WHERE role_id = %s", (role_id,))
        f_items = cur_int.fetchall()
        
        role_obj = inter.guild.get_role(int(role_id))
        embed = discord.Embed(title=f"🏦 Deposito: {role_obj.name}", color=discord.Color.blue())
        embed.add_field(name="💰 Soldi", value=f"**{f_info['money']}$**", inline=False)
        
        lista = "\n".join([f"📦 **{i['item_name']}** x{i['quantity']}" for i in f_items]) if f_items else "*Vuoto*"
        embed.add_field(name="📦 Inventario", value=lista, inline=False)
        
        await inter.followup.send(embed=embed, ephemeral=True)
        cur_int.close()
        conn_int.close()

    # CASO 1: L'utente ha una sola fazione
    if len(miei_ruoli_fazione) == 1:
        cur.close()
        conn.close()
        await mostra_deposito(interaction, str(miei_ruoli_fazione[0].id))

    # CASO 2: L'utente ha più fazioni (Mostra Menu)
    else:
        class FazioneSelect(discord.ui.Select):
            def __init__(self, opzioni):
                super().__init__(placeholder="Seleziona la fazione...", options=opzioni)
            async def callback(self, inter: Interaction):
                await inter.response.defer(ephemeral=True)
                await mostra_deposito(inter, self.values[0])

        view = discord.ui.View()
        options = [discord.SelectOption(label=r.name, value=str(r.id)) for r in miei_ruoli_fazione]
        view.add_item(FazioneSelect(options))
        
        cur.close()
        conn.close()
        await interaction.followup.send("🤔 Fai parte di più fazioni. Quale deposito vuoi aprire?", view=view, ephemeral=True)


# ================= GESTIONE CATALOGO SHOP (ADMIN) =================

@bot.tree.command(name="edit_item_shop", description="ADMIN - Modifica oggetto shop")
async def edit_item_shop(interaction: Interaction, nome: str, nuova_descrizione: str = None, nuovo_prezzo: int = None, nuovo_ruolo: discord.Role = None):
    await interaction.response.defer(ephemeral=True)
    if not interaction.user.guild_permissions.administrator: return await interaction.followup.send("❌ No Admin.")

    nome_esatto = await cerca_item_smart(interaction, nome, "items")
    if not nome_esatto: return

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM items WHERE name = %s", (nome_esatto,))
    curr = cur.fetchone()

    desc = nuova_descrizione or curr['description']
    price = nuovo_prezzo if nuovo_prezzo is not None else curr['price']
    role = str(nuovo_ruolo.id) if nuovo_ruolo else curr['role_required']

    cur.execute("UPDATE items SET description = %s, price = %s, role_required = %s WHERE name = %s", (desc, price, role, nome_esatto))
    conn.commit()
    cur.close()
    conn.close()
    await interaction.followup.send(f"✅ **{nome_esatto}** aggiornato!")

@bot.tree.command(name="elimina_item_shop", description="ADMIN - Rimuovi oggetto shop")
async def elimina_item_shop(interaction: Interaction, nome: str):
    await interaction.response.defer(ephemeral=True)
    if not interaction.user.guild_permissions.administrator: return
    nome_esatto = await cerca_item_smart(interaction, nome, "items")
    if not nome_esatto: return
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM items WHERE name = %s", (nome_esatto,))
    conn.commit()
    cur.close()
    conn.close()
    await interaction.followup.send(f"🗑️ Rimosso **{nome_esatto}**.")

# ================= BANCA =================

@bot.tree.command(name="deposita", description="Portafoglio -> Banca")
async def deposita(interaction: Interaction, importo: int):
    await interaction.response.defer(ephemeral=True)
    user = get_user_data(interaction.user.id)
    if importo <= 0 or user['wallet'] < importo: return await interaction.followup.send("❌ Fondi insufficienti.")
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE users SET wallet = wallet - %s, bank = bank + %s WHERE user_id = %s", (importo, importo, str(interaction.user.id)))
    conn.commit()
    cur.close()
    conn.close()
    await interaction.followup.send(f"🏦 Depositati **{importo}$**.")

@bot.tree.command(name="preleva", description="Banca -> Portafoglio")
async def preleva(interaction: Interaction, importo: int):
    await interaction.response.defer(ephemeral=True)
    user = get_user_data(interaction.user.id)
    if importo <= 0 or user['bank'] < importo: return await interaction.followup.send("❌ Fondi insufficienti in banca.")
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE users SET wallet = wallet + %s, bank = bank - %s WHERE user_id = %s", (importo, importo, str(interaction.user.id)))
    conn.commit()
    cur.close()
    conn.close()
    await interaction.followup.send(f"💸 Prelevati **{importo}$**.")

# ================= FAZIONI =================

@bot.tree.command(name="deposita_item_fazione", description="Sposta un oggetto nel deposito fazione")
# ================= COMANDI FAZIONE CON SELEZIONE MULTIPLA =================

@bot.tree.command(name="deposita_soldi_fazione", description="Deposita soldi in una delle tue fazioni")
async def deposita_soldi_fazione(interaction: Interaction, importo: int):
    await interaction.response.defer(ephemeral=True)
    miei_ruoli = await get_miei_ruoli_fazione(interaction)
    
    if not miei_ruoli: 
        return await interaction.followup.send("❌ Non appartieni a nessuna fazione registrata.")
    
    user = get_user_data(interaction.user.id)
    if importo <= 0 or user['wallet'] < importo: 
        return await interaction.followup.send("❌ Fondi insufficienti nel portafoglio.")

    async def procedi_deposito(inter: Interaction, role_id: str):
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("UPDATE users SET wallet = wallet - %s WHERE user_id = %s", (importo, str(inter.user.id)))
        cur.execute("UPDATE depositi SET money = money + %s WHERE role_id = %s", (importo, role_id))
        conn.commit()
        cur.close()
        conn.close()
        await inter.followup.send(f"✅ Depositati **{importo}$** nella fazione.")

    if len(miei_ruoli) == 1:
        await procedi_deposito(interaction, str(miei_ruoli[0].id))
    else:
        view = discord.ui.View()
        options = [discord.SelectOption(label=r.name, value=str(r.id)) for r in miei_ruoli]
        select = discord.ui.Select(placeholder="Scegli la fazione...", options=options)
        async def callback(inter: Interaction):
            await inter.response.defer(ephemeral=True)
            await procedi_deposito(inter, select.values[0])
        select.callback = callback
        view.add_item(select)
        await interaction.followup.send("💰 In quale fazione vuoi depositare i soldi?", view=view)

@bot.tree.command(name="preleva_soldi_fazione", description="Preleva soldi da una delle tue fazioni")
async def preleva_soldi_fazione(interaction: Interaction, importo: int):
    await interaction.response.defer(ephemeral=True)
    miei_ruoli = await get_miei_ruoli_fazione(interaction)
    
    if not miei_ruoli: 
        return await interaction.followup.send("❌ Non appartieni a nessuna fazione registrata.")

    async def procedi_prelievo(inter: Interaction, role_id: str):
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT money FROM depositi WHERE role_id = %s", (role_id,))
        res = cur.fetchone()
        if not res or res['money'] < importo: 
            cur.close()
            conn.close()
            return await inter.followup.send("❌ La fazione non ha abbastanza fondi.")
        
        cur.execute("UPDATE depositi SET money = money - %s WHERE role_id = %s", (importo, role_id))
        cur.execute("UPDATE users SET wallet = wallet + %s WHERE user_id = %s", (importo, str(inter.user.id)))
        conn.commit()
        cur.close()
        conn.close()
        await inter.followup.send(f"💸 Prelevati **{importo}$** dalla fazione.")

    if len(miei_ruoli) == 1:
        await procedi_prelievo(interaction, str(miei_ruoli[0].id))
    else:
        view = discord.ui.View()
        options = [discord.SelectOption(label=r.name, value=str(r.id)) for r in miei_ruoli]
        select = discord.ui.Select(placeholder="Scegli la fazione...", options=options)
        async def callback(inter: Interaction):
            await inter.response.defer(ephemeral=True)
            await procedi_prelievo(inter, select.values[0])
        select.callback = callback
        view.add_item(select)
        await interaction.followup.send("💸 Da quale fazione vuoi prelevare i soldi?", view=view)

@bot.tree.command(name="deposita_item_fazione", description="Metti un oggetto in un deposito fazione")
async def deposita_item_fazione(interaction: Interaction, nome: str, quantita: int = 1):
    await interaction.response.defer(ephemeral=True)
    nome_e = await cerca_item_smart(interaction, nome, "inventory")
    if not nome_e: return
    
    miei_ruoli = await get_miei_ruoli_fazione(interaction)
    if not miei_ruoli: 
        return await interaction.followup.send("❌ Non appartieni a nessuna fazione registrata.")

    async def procedi_dep_item(inter: Interaction, role_id: str):
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("UPDATE inventory SET quantity = quantity - %s WHERE user_id = %s AND item_name = %s", (quantita, str(inter.user.id), nome_e))
        cur.execute("""
            INSERT INTO depositi_items (role_id, item_name, quantity) 
            VALUES (%s, %s, %s) 
            ON CONFLICT (role_id, item_name) 
            DO UPDATE SET quantity = depositi_items.quantity + %s
        """, (role_id, nome_e, quantita, quantita))
        cur.execute("DELETE FROM inventory WHERE quantity <= 0")
        conn.commit()
        cur.close()
        conn.close()
        await inter.followup.send(f"✅ Depositati {quantita}x **{nome_e}** nel magazzino.")

    if len(miei_ruoli) == 1:
        await procedi_dep_item(interaction, str(miei_ruoli[0].id))
    else:
        view = discord.ui.View()
        options = [discord.SelectOption(label=r.name, value=str(r.id)) for r in miei_ruoli]
        select = discord.ui.Select(placeholder="Scegli la fazione...", options=options)
        async def callback(inter: Interaction):
            await inter.response.defer(ephemeral=True)
            await procedi_dep_item(inter, select.values[0])
        select.callback = callback
        view.add_item(select)
        await interaction.followup.send(f"📦 In quale magazzino vuoi depositare {nome_e}?", view=view)

@bot.tree.command(name="preleva_item_fazione", description="Preleva un oggetto da un deposito fazione")
async def preleva_item_fazione(interaction: Interaction, nome: str, quantita: int = 1):
    await interaction.response.defer(ephemeral=True)
    miei_ruoli = await get_miei_ruoli_fazione(interaction)
    if not miei_ruoli: 
        return await interaction.followup.send("❌ Non appartieni a nessuna fazione registrata.")

    async def procedi_prel_item(inter: Interaction, role_id: str):
        # Cerchiamo l'oggetto specificamente nel magazzino della fazione scelta
        nome_e = await cerca_item_smart(inter, nome, f"fazione_{role_id}")
        if not nome_e: return
        
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT quantity FROM depositi_items WHERE role_id = %s AND item_name = %s", (role_id, nome_e))
        res = cur.fetchone()
        if not res or res[0] < quantita:
            cur.close()
            conn.close()
            return await inter.followup.send(f"❌ La fazione non ha abbastanza {nome_e}.")
        
        cur.execute("UPDATE depositi_items SET quantity = quantity - %s WHERE role_id = %s AND item_name = %s", (quantita, role_id, nome_e))
        cur.execute("""
            INSERT INTO inventory (user_id, item_name, quantity) 
            VALUES (%s, %s, %s) 
            ON CONFLICT (user_id, item_name) 
            DO UPDATE SET quantity = inventory.quantity + %s
        """, (str(inter.user.id), nome_e, quantita, quantita))
        cur.execute("DELETE FROM depositi_items WHERE quantity <= 0")
        conn.commit()
        cur.close()
        conn.close()
        await inter.followup.send(f"📦 Prelevati {quantita}x **{nome_e}** dal magazzino.")

    if len(miei_ruoli) == 1:
        await procedi_prel_item(interaction, str(miei_ruoli[0].id))
    else:
        view = discord.ui.View()
        options = [discord.SelectOption(label=r.name, value=str(r.id)) for r in miei_ruoli]
        select = discord.ui.Select(placeholder="Scegli la fazione...", options=options)
        async def callback(inter: Interaction):
            await inter.response.defer(ephemeral=True)
            await procedi_prel_item(inter, select.values[0])
        select.callback = callback
        view.add_item(select)
        await interaction.followup.send(f"📦 Da quale magazzino vuoi prelevare {nome}?", view=view)


# ================= SHOP =================

@bot.tree.command(name="shop", description="Vedi lo shop")
async def shop(interaction: Interaction):
    await interaction.response.defer()
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM items")
    rows = cur.fetchall()
    if not rows: return await interaction.followup.send("🏪 Vuoto.")
    embed = discord.Embed(title="🏪 Shop", color=discord.Color.gold())
    for r in rows:
        req = f"\n⚠️ Requisito: <@&{r['role_required']}>" if r['role_required'] != "None" else ""
        embed.add_field(name=f"{r['name']} — {r['price']}$", value=f"{r['description']}{req}", inline=False)
    await interaction.followup.send(embed=embed)
    cur.close()
    conn.close()

@bot.tree.command(name="compra", description="Compra item")
async def compra(interaction: Interaction, nome: str):
    await interaction.response.defer(ephemeral=True)
    nome_e = await cerca_item_smart(interaction, nome, "items")
    if not nome_e: return
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM items WHERE name = %s", (nome_e,))
    it = cur.fetchone()
    user = get_user_data(interaction.user.id)

    if user['wallet'] < it['price']: return await interaction.followup.send("❌ Soldi insufficienti.")
    if it['role_required'] != "None" and not any(str(r.id) == it['role_required'] for r in interaction.user.roles):
        return await interaction.followup.send("⚠️ Ruolo mancante.")

    cur.execute("UPDATE users SET wallet = wallet - %s WHERE user_id = %s", (it['price'], str(interaction.user.id)))
    cur.execute("INSERT INTO inventory (user_id, item_name, quantity) VALUES (%s, %s, 1) ON CONFLICT (user_id, item_name) DO UPDATE SET quantity = inventory.quantity + 1", (str(interaction.user.id), nome_e))
    conn.commit()
    cur.close()
    conn.close()
    await interaction.followup.send(f"🛍️ Comprato **{nome_e}**!")

# ================= GIOCHI / CERCA =================

@bot.tree.command(name="cerca", description="Cerca tra i rifiuti (1 min)")
async def cerca(interaction: Interaction):
    await interaction.response.defer()
    await interaction.followup.send("🔍 Cerchi... ci vorrà 1 minuto.")
    await asyncio.sleep(60)
    loot = random.choices(["Rame", "Ferro", "Plastica", "Nulla"], weights=[20, 15, 25, 40])[0]
    if loot != "Nulla":
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("INSERT INTO inventory (user_id, item_name, quantity) VALUES (%s, %s, 1) ON CONFLICT (user_id, item_name) DO UPDATE SET quantity = inventory.quantity + 1", (str(interaction.user.id), loot))
        conn.commit()
        cur.close()
        conn.close()
        await interaction.followup.send(f"📦 Trovato: **{loot}**!")
    else:
        await interaction.followup.send("😢 Nulla di utile.")

@bot.tree.command(name="roulette", description="Scommetti colore")
@app_commands.choices(colore=[app_commands.Choice(name="Rosso (x2)", value="rosso"), app_commands.Choice(name="Nero (x2)", value="nero"), app_commands.Choice(name="Verde (x14)", value="verde")])
async def roulette(interaction: Interaction, scommessa: int, colore: str):
    await interaction.response.defer()
    user = get_user_data(interaction.user.id)
    if scommessa <= 0 or user['wallet'] < scommessa: return await interaction.followup.send("❌ Fondi insufficienti.")
    
    num = random.randint(0, 36)
    res_col = "verde" if num == 0 else ("rosso" if num in [1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36] else "nero")
    conn = get_db_connection()
    cur = conn.cursor()

    if colore == res_col:
        molt = 14 if res_col == "verde" else 2
        vincita = scommessa * (molt - 1)
        cur.execute("UPDATE users SET wallet = wallet + %s WHERE user_id = %s", (vincita, str(interaction.user.id)))
        msg = f"🎉 VINTO! Uscito {num} ({res_col}). Guadagno: **{vincita}$**"
    else:
        cur.execute("UPDATE users SET wallet = wallet - %s WHERE user_id = %s", (scommessa, str(interaction.user.id)))
        msg = f"💀 PERSO! Uscito {num} ({res_col}). Persi: **{scommessa}$**"
    
    conn.commit()
    cur.close()
    conn.close()
    await interaction.followup.send(msg)

# ================= INFO UTENTE =================

@bot.tree.command(name="portafoglio", description="Vedi i soldi")
async def portafoglio(interaction: Interaction):
    u = get_user_data(interaction.user.id)
    await interaction.response.send_message(f"💰 Wallet: **{u['wallet']}$** | 🏦 Banca: **{u['bank']}$**", ephemeral=True)

@bot.tree.command(name="inventario", description="Vedi gli item")
async def inventario(interaction: Interaction):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM inventory WHERE user_id = %s", (str(interaction.user.id),))
    rows = cur.fetchall()
    if not rows: return await interaction.response.send_message("🎒 Vuoto.", ephemeral=True)
    lista = "\n".join([f"📦 **{r['item_name']}** x{r['quantity']}" for r in rows])
    await interaction.response.send_message(embed=discord.Embed(title="Inventario", description=lista), ephemeral=True)
    cur.close()
    conn.close()

# ================= ADMIN TOOLS =================

@bot.tree.command(name="aggiungisoldi", description="ADMIN - Dai soldi")
async def aggiungisoldi(interaction: Interaction, utente: discord.Member, importo: int):
    if not interaction.user.guild_permissions.administrator: return
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO users (user_id, wallet) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET wallet = users.wallet + %s", (str(utente.id), importo, importo))
    conn.commit()
    cur.close()
    conn.close()
    await interaction.response.send_message(f"✅ Dati {importo}$ a {utente.mention}")

@bot.tree.command(name="wipe_utente", description="ADMIN - Reset")
async def wipe_utente(interaction: Interaction, utente: discord.Member):
    if not interaction.user.guild_permissions.administrator: return
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE users SET wallet = 0, bank = 0 WHERE user_id = %s", (str(utente.id),))
    cur.execute("DELETE FROM inventory WHERE user_id = %s", (str(utente.id),))
    conn.commit()
    cur.close()
    conn.close()
    await interaction.response.send_message(f"🧹 Reset per {utente.mention}")

@bot.tree.command(name="registra_fazione", description="ADMIN - Nuova Fazione")
async def registra_fazione(interaction: Interaction, ruolo: discord.Role):
    if not interaction.user.guild_permissions.administrator: return
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO depositi (role_id, money) VALUES (%s, 0) ON CONFLICT DO NOTHING", (str(ruolo.id),))
    conn.commit()
    cur.close()
    conn.close()
    await interaction.response.send_message(f"🏢 Fazione {ruolo.name} registrata.")

# ================= WEB SERVER & START =================
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"✅ {bot.user} Online su Supabase!")

app = Flask("")
@app.route("/")
def home(): return "Online"
def run(): app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
threading.Thread(target=run).start()
bot.run(TOKEN)
