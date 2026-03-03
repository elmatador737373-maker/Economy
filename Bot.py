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
RUOLO_STAFF_ID = 1465412245264662734

intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ================= DATABASE SETUP =================

def get_db_connection():
    try:
        url = DATABASE_URL.replace("postgres://", "postgresql://")
        conn = psycopg2.connect(url, sslmode='require', connect_timeout=10)
        return conn
    except Exception as e:
        print(f"❌ Errore connessione DB: {e}")
        return None

def init_db():
    conn = get_db_connection()
    if not conn: return
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS users (user_id TEXT PRIMARY KEY, wallet INTEGER DEFAULT 500, bank INTEGER DEFAULT 0)")
    cur.execute("CREATE TABLE IF NOT EXISTS items (name TEXT PRIMARY KEY, description TEXT, price INTEGER, role_required TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS inventory (user_id TEXT, item_name TEXT, quantity INTEGER, PRIMARY KEY (user_id, item_name))")
    cur.execute("CREATE TABLE IF NOT EXISTS depositi (role_id TEXT PRIMARY KEY, money INTEGER DEFAULT 0)")
    cur.execute("CREATE TABLE IF NOT EXISTS depositi_items (role_id TEXT, item_name TEXT, quantity INTEGER, PRIMARY KEY (role_id, item_name))")
    conn.commit()
    cur.close(); conn.close()

init_db()

# ================= HELPER FUNCTIONS =================

def get_user_data(user_id):
    conn = get_db_connection()
    if not conn: return {"wallet": 0, "bank": 0}
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM users WHERE user_id = %s", (str(user_id),))
    user = cur.fetchone()
    if not user:
        cur.execute("INSERT INTO users (user_id, wallet, bank) VALUES (%s, 500, 0) RETURNING *", (str(user_id),))
        user = cur.fetchone()
        conn.commit()
    cur.close(); conn.close()
    return user

def is_staff(interaction: discord.Interaction):
    return any(role.id == RUOLO_STAFF_ID for role in interaction.user.roles)

async def get_miei_ruoli_fazione(interaction: Interaction):
    conn = get_db_connection()
    if not conn: return []
    cur = conn.cursor()
    cur.execute("SELECT role_id FROM depositi")
    registrati = [r[0] for r in cur.fetchall()]
    cur.close(); conn.close()
    return [r for r in interaction.user.roles if str(r.id) in registrati]

async def cerca_item_smart(interaction: Interaction, nome_input: str, modo="items"):
    conn = get_db_connection()
    cur = conn.cursor()
    if modo == "items":
        cur.execute("SELECT name FROM items WHERE name ILIKE %s", (f"%{nome_input}%",))
    elif modo == "inventory":
        cur.execute("SELECT item_name FROM inventory WHERE user_id = %s AND item_name ILIKE %s", (str(interaction.user.id), f"%{nome_input}%"))
    else:
        role_id = modo.replace("fazione_", "")
        cur.execute("SELECT item_name FROM depositi_items WHERE role_id = %s AND item_name ILIKE %s", (role_id, f"%{nome_input}%"))
    
    risultati = list(set([r[0] for r in cur.fetchall()]))
    cur.close(); conn.close()
    
    if not risultati:
        await interaction.followup.send(f"❌ Nessun oggetto trovato per '{nome_input}'.")
        return None
    if len(risultati) == 1: return risultati[0]

    view = discord.ui.View()
    select = discord.ui.Select(options=[discord.SelectOption(label=n) for n in risultati[:25]])
    
    async def callback(i: Interaction):
        for item in view.children: item.disabled = True
        await i.response.edit_message(view=view)
        view.value = select.values[0]; view.stop()
        
    select.callback = callback
    view.add_item(select); view.value = None
    # Questo messaggio di scelta rimane privato per non intasare, ma l'azione finale sarà pubblica
    await interaction.followup.send("🤔 Più risultati, seleziona quello corretto:", view=view, ephemeral=True)
    await view.wait()
    return view.value

# ================= COMANDI ECONOMIA BASE =================

@bot.tree.command(name="portafoglio", description="Vedi i tuoi soldi")
async def portafoglio(interaction: Interaction):
    u = get_user_data(interaction.user.id)
    await interaction.response.send_message(f"💰 **{interaction.user.display_name}** | Wallet: **{u['wallet']}$** | Banca: **{u['bank']}$**")

@bot.tree.command(name="deposita", description="Metti soldi in banca")
async def deposita(interaction: Interaction, importo: int):
    u = get_user_data(interaction.user.id)
    if importo <= 0 or u['wallet'] < importo:
        return await interaction.response.send_message("❌ Importo non valido o contanti insufficienti.")
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("UPDATE users SET wallet = wallet - %s, bank = bank + %s WHERE user_id = %s", (importo, importo, str(interaction.user.id)))
    conn.commit(); cur.close(); conn.close()
    await interaction.response.send_message(f"🏦 **{interaction.user.display_name}** ha depositato **{importo}$** in banca.")

@bot.tree.command(name="preleva", description="Preleva dalla banca")
async def preleva(interaction: Interaction, importo: int):
    u = get_user_data(interaction.user.id)
    if importo <= 0 or u['bank'] < importo:
        return await interaction.response.send_message("❌ Importo non valido o banca vuota.")
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("UPDATE users SET bank = bank - %s, wallet = wallet + %s WHERE user_id = %s", (importo, importo, str(interaction.user.id)))
    conn.commit(); cur.close(); conn.close()
    await interaction.response.send_message(f"💸 **{interaction.user.display_name}** ha prelevato **{importo}$**.")

@bot.tree.command(name="dai_soldi", description="Dai soldi a un altro utente")
async def dai_soldi(interaction: Interaction, utente: discord.Member, importo: int):
    if utente.id == interaction.user.id: return await interaction.response.send_message("❌ Non puoi darti soldi da solo.")
    u = get_user_data(interaction.user.id)
    if importo <= 0 or u['wallet'] < importo: return await interaction.response.send_message("❌ Fondi insufficienti.")
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("UPDATE users SET wallet = wallet - %s WHERE user_id = %s", (importo, str(interaction.user.id)))
    cur.execute("UPDATE users SET wallet = wallet + %s WHERE user_id = %s", (importo, str(utente.id)))
    conn.commit(); cur.close(); conn.close()
    await interaction.response.send_message(f"🤝 **{interaction.user.display_name}** ha dato **{importo}$** a **{utente.mention}**.")

# ================= COMANDI INVENTARIO =================

@bot.tree.command(name="inventario", description="Mostra i tuoi oggetti")
async def inventario(interaction: Interaction):
    await interaction.response.defer()
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT item_name, quantity FROM inventory WHERE user_id = %s", (str(interaction.user.id),))
    items = cur.fetchall()
    cur.close(); conn.close()
    emb = discord.Embed(title=f"🎒 Zaino di {interaction.user.display_name}", color=discord.Color.blue())
    desc = "\n".join([f"📦 **{i['item_name']}** x{i['quantity']}" for i in items]) if items else "*Vuoto.*"
    emb.description = desc
    await interaction.followup.send(embed=emb)

@bot.tree.command(name="dai_item", description="Dai un oggetto a un utente")
async def dai_item(interaction: Interaction, utente: discord.Member, nome: str, quantita: int = 1):
    if utente.id == interaction.user.id: return await interaction.response.send_message("❌ Impossibile.")
    await interaction.response.defer()
    nome_e = await cerca_item_smart(interaction, nome, "inventory")
    if not nome_e: return
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT quantity FROM inventory WHERE user_id = %s AND item_name = %s", (str(interaction.user.id), nome_e))
    res = cur.fetchone()
    if not res or res[0] < quantita: return await interaction.followup.send("❌ Non ne hai abbastanza.")
    cur.execute("UPDATE inventory SET quantity = quantity - %s WHERE user_id = %s AND item_name = %s", (quantita, str(interaction.user.id), nome_e))
    cur.execute("INSERT INTO inventory (user_id, item_name, quantity) VALUES (%s, %s, %s) ON CONFLICT (user_id, item_name) DO UPDATE SET quantity = inventory.quantity + %s", (str(utente.id), nome_e, quantita, quantita))
    cur.execute("DELETE FROM inventory WHERE quantity <= 0")
    conn.commit(); cur.close(); conn.close()
    await interaction.followup.send(f"📦 **{interaction.user.display_name}** ha passato {quantita}x **{nome_e}** a **{utente.mention}**.")

@bot.tree.command(name="usa", description="Usa un oggetto")
async def usa(interaction: Interaction, nome: str):
    await interaction.response.defer()
    nome_e = await cerca_item_smart(interaction, nome, "inventory")
    if not nome_e: return
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("UPDATE inventory SET quantity = quantity - 1 WHERE user_id = %s AND item_name = %s", (str(interaction.user.id), nome_e))
    cur.execute("DELETE FROM inventory WHERE quantity <= 0")
    conn.commit(); cur.close(); conn.close()
    await interaction.followup.send(f"✨ **{interaction.user.display_name}** ha usato **{nome_e}**!")

# ================= COMANDI FAZIONE =================

@bot.tree.command(name="deposito_fazione", description="Visualizza il deposito di fazione")
async def deposito_fazione(interaction: Interaction):
    await interaction.response.defer()
    miei_ruoli = await get_miei_ruoli_fazione(interaction)
    if not miei_ruoli: return await interaction.followup.send("❌ Non sei in una fazione.")

    async def mostra(inter, rid):
        conn = get_db_connection(); cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT money FROM depositi WHERE role_id = %s", (rid,))
        m = cur.fetchone()['money']
        cur.execute("SELECT item_name, quantity FROM depositi_items WHERE role_id = %s", (rid,))
        it = cur.fetchall()
        r_obj = inter.guild.get_role(int(rid))
        emb = discord.Embed(title=f"🏦 Deposito {r_obj.name}", color=discord.Color.dark_blue())
        emb.add_field(name="Soldi", value=f"{m}$", inline=False)
        lista = "\n".join([f"📦 {i['item_name']} x{i['quantity']}" for i in it]) if it else "Vuoto"
        emb.add_field(name="Oggetti", value=lista, inline=False)
        await inter.followup.send(embed=emb); cur.close(); conn.close()

    if len(miei_ruoli) == 1: await mostra(interaction, str(miei_ruoli[0].id))
    else:
        view = discord.ui.View()
        sel = discord.ui.Select(options=[discord.SelectOption(label=r.name, value=str(r.id)) for r in miei_ruoli])
        async def call(i): 
            for it in view.children: it.disabled = True
            await i.response.edit_message(view=view); await mostra(i, sel.values[0])
        sel.callback = call; view.add_item(sel)
        await interaction.followup.send("Quale deposito vuoi aprire?", view=view, ephemeral=True)

@bot.tree.command(name="deposita_soldi_fazione", description="Deposita soldi in fazione")
async def deposita_soldi_fazione(interaction: Interaction, importo: int):
    await interaction.response.defer()
    miei_ruoli = await get_miei_ruoli_fazione(interaction)
    if not miei_ruoli: return await interaction.followup.send("❌ No Fazione.")
    u = get_user_data(interaction.user.id)
    if importo <= 0 or u['wallet'] < importo: return await interaction.followup.send("❌ Fondi insufficienti.")

    async def procedi(inter, rid):
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("UPDATE users SET wallet = wallet - %s WHERE user_id = %s", (importo, str(inter.user.id)))
        cur.execute("UPDATE depositi SET money = money + %s WHERE role_id = %s", (importo, rid))
        conn.commit(); cur.close(); conn.close()
        r_obj = inter.guild.get_role(int(rid))
        await inter.followup.send(f"✅ **{inter.user.display_name}** ha depositato **{importo}$** in **{r_obj.name}**.")

    if len(miei_ruoli) == 1: await procedi(interaction, str(miei_ruoli[0].id))
    else:
        view = discord.ui.View()
        sel = discord.ui.Select(options=[discord.SelectOption(label=r.name, value=str(r.id)) for r in miei_ruoli])
        async def call(i): 
            for it in view.children: it.disabled = True
            await i.response.edit_message(view=view); await procedi(i, sel.values[0])
        sel.callback = call; view.add_item(sel)
        await interaction.followup.send("In quale fazione depositi?", view=view, ephemeral=True)

@bot.tree.command(name="preleva_soldi_fazione", description="Preleva soldi dalla fazione")
async def preleva_soldi_fazione(interaction: Interaction, importo: int):
    await interaction.response.defer()
    miei_ruoli = await get_miei_ruoli_fazione(interaction)
    if not miei_ruoli: return await interaction.followup.send("❌ No Fazione.")

    async def procedi(inter, rid):
        conn = get_db_connection(); cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT money FROM depositi WHERE role_id = %s", (rid,))
        if cur.fetchone()['money'] < importo: return await inter.followup.send("❌ Fondo fazione insufficiente.")
        cur.execute("UPDATE depositi SET money = money - %s WHERE role_id = %s", (importo, rid))
        cur.execute("UPDATE users SET wallet = wallet + %s WHERE user_id = %s", (importo, str(inter.user.id)))
        conn.commit(); cur.close(); conn.close()
        r_obj = inter.guild.get_role(int(rid))
        await inter.followup.send(f"💸 **{inter.user.display_name}** ha prelevato **{importo}$** da **{r_obj.name}**.")

    if len(miei_ruoli) == 1: await procedi(interaction, str(miei_ruoli[0].id))
    else:
        view = discord.ui.View()
        sel = discord.ui.Select(options=[discord.SelectOption(label=r.name, value=str(r.id)) for r in miei_ruoli])
        async def call(i):
            for it in view.children: it.disabled = True
            await i.response.edit_message(view=view); await procedi(i, sel.values[0])
        sel.callback = call; view.add_item(sel)
        await interaction.followup.send("Da quale fazione prelevi?", view=view, ephemeral=True)

@bot.tree.command(name="deposita_item_fazione", description="Metti un item in fazione")
async def deposita_item_fazione(interaction: Interaction, nome: str, quantita: int = 1):
    await interaction.response.defer()
    miei_ruoli = await get_miei_ruoli_fazione(interaction)
    if not miei_ruoli: return await interaction.followup.send("❌ No Fazione.")
    nome_e = await cerca_item_smart(interaction, nome, "inventory")
    if not nome_e: return

    async def procedi(inter, rid):
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("UPDATE inventory SET quantity = quantity - %s WHERE user_id = %s AND item_name = %s", (quantita, str(inter.user.id), nome_e))
        cur.execute("INSERT INTO depositi_items (role_id, item_name, quantity) VALUES (%s, %s, %s) ON CONFLICT (role_id, item_name) DO UPDATE SET quantity = depositi_items.quantity + %s", (rid, nome_e, quantita, quantita))
        cur.execute("DELETE FROM inventory WHERE quantity <= 0")
        conn.commit(); cur.close(); conn.close()
        r_obj = inter.guild.get_role(int(rid))
        await inter.followup.send(f"✅ **{inter.user.display_name}** ha messo {quantita}x **{nome_e}** in **{r_obj.name}**.")

    if len(miei_ruoli) == 1: await procedi(interaction, str(miei_ruoli[0].id))
    else:
        view = discord.ui.View()
        sel = discord.ui.Select(options=[discord.SelectOption(label=r.name, value=str(r.id)) for r in miei_ruoli])
        async def call(i):
            for it in view.children: it.disabled = True
            await i.response.edit_message(view=view); await procedi(i, sel.values[0])
        sel.callback = call; view.add_item(sel)
        await interaction.followup.send("In quale magazzino depositi?", view=view, ephemeral=True)

@bot.tree.command(name="preleva_item_fazione", description="Preleva un item dalla fazione")
async def preleva_item_fazione(interaction: Interaction, nome: str, quantita: int = 1):
    await interaction.response.defer()
    miei_ruoli = await get_miei_ruoli_fazione(interaction)
    if not miei_ruoli: return await interaction.followup.send("❌ No Fazione.")

    async def procedi(inter, rid):
        nome_e = await cerca_item_smart(inter, nome, f"fazione_{rid}")
        if not nome_e: return
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("SELECT quantity FROM depositi_items WHERE role_id = %s AND item_name = %s", (rid, nome_e))
        res = cur.fetchone()
        if not res or res[0] < quantita: return await inter.followup.send("❌ Magazzino fazione insufficiente.")
        cur.execute("UPDATE depositi_items SET quantity = quantity - %s WHERE role_id = %s AND item_name = %s", (quantita, rid, nome_e))
        cur.execute("INSERT INTO inventory (user_id, item_name, quantity) VALUES (%s, %s, %s) ON CONFLICT (user_id, item_name) DO UPDATE SET quantity = inventory.quantity + %s", (str(inter.user.id), nome_e, quantita, quantita))
        cur.execute("DELETE FROM depositi_items WHERE quantity <= 0")
        conn.commit(); cur.close(); conn.close()
        r_obj = inter.guild.get_role(int(rid))
        await inter.followup.send(f"📦 **{inter.user.display_name}** ha prelevato {quantita}x **{nome_e}** da **{r_obj.name}**.")

    if len(miei_ruoli) == 1: await procedi(interaction, str(miei_ruoli[0].id))
    else:
        view = discord.ui.View()
        sel = discord.ui.Select(options=[discord.SelectOption(label=r.name, value=str(r.id)) for r in miei_ruoli])
        async def call(i):
            for it in view.children: it.disabled = True
            await i.response.edit_message(view=view); await procedi(i, sel.values[0])
        sel.callback = call; view.add_item(sel)
        await interaction.followup.send("Da quale magazzino prelevi?", view=view, ephemeral=True)

# ================= SHOP & LAVORO =================

@bot.tree.command(name="shop", description="Mostra il catalogo")
async def shop(interaction: Interaction):
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM items")
    items = cur.fetchall()
    cur.close(); conn.close()
    emb = discord.Embed(title="🛒 Negozio", color=discord.Color.green())
    for i in items:
        req = "Nessuno" if i['role_required'] == "None" else f"<@&{i['role_required']}>"
        emb.add_field(name=i['name'], value=f"Prezzo: {i['price']}$\nReq: {req}\n{i['description']}", inline=False)
    await interaction.response.send_message(embed=emb)

@bot.tree.command(name="compra", description="Compra un oggetto")
async def compra(interaction: Interaction, nome: str, quantita: int = 1):
    await interaction.response.defer()
    nome_e = await cerca_item_smart(interaction, nome, "items")
    if not nome_e: return
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM items WHERE name = %s", (nome_e,))
    item = cur.fetchone()
    u = get_user_data(interaction.user.id)
    prezzo_totale = item['price'] * quantita
    if item['role_required'] != "None" and not any(str(r.id) == item['role_required'] for r in interaction.user.roles):
        return await interaction.followup.send("❌ Grado fazione mancante.")
    if u['wallet'] < prezzo_totale: return await interaction.followup.send("❌ Soldi insufficienti.")
    cur.execute("UPDATE users SET wallet = wallet - %s WHERE user_id = %s", (prezzo_totale, str(interaction.user.id)))
    cur.execute("INSERT INTO inventory (user_id, item_name, quantity) VALUES (%s, %s, %s) ON CONFLICT (user_id, item_name) DO UPDATE SET quantity = inventory.quantity + %s", (str(interaction.user.id), nome_e, quantita, quantita))
    conn.commit(); cur.close(); conn.close()
    await interaction.followup.send(f"🛍️ **{interaction.user.display_name}** ha comprato {quantita}x **{nome_e}**!")

@bot.tree.command(name="cerca", description="Cerca materiali (1 min)")
async def cerca(interaction: Interaction):
    await interaction.response.send_message(f"🔍 **{interaction.user.display_name}** ha iniziato a cercare materiali... torna tra 1 minuto.")
    await asyncio.sleep(60)
    mat = random.choice(["Ferro", "Rame", "Plastica", "Legno", "Pezzi di Vetro", "Cavi Elettrici"])
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("INSERT INTO inventory (user_id, item_name, quantity) VALUES (%s, %s, 1) ON CONFLICT (user_id, item_name) DO UPDATE SET quantity = inventory.quantity + 1", (str(interaction.user.id), mat))
    conn.commit(); cur.close(); conn.close()
    await interaction.channel.send(f"✅ **{interaction.user.mention}** ha trovato: **{mat}**!")

# ================= GIOCHI AZZARDO =================

@bot.tree.command(name="blackjack", description="Gioca a Blackjack")
async def blackjack(interaction: Interaction, scommessa: int):
    u = get_user_data(interaction.user.id)
    if scommessa <= 0 or u['wallet'] < scommessa: return await interaction.response.send_message("❌ Fondi insufficienti.")
    deck = [2,3,4,5,6,7,8,9,10,10,10,10,11]*4
    random.shuffle(deck)
    p_cards, d_cards = [deck.pop(), deck.pop()], [deck.pop(), deck.pop()]
    
    async def create_emb(ended=False):
        emb = discord.Embed(title="🃏 Blackjack", color=discord.Color.blue())
        emb.add_field(name=interaction.user.name, value=f"{p_cards} (Tot: {sum(p_cards)})")
        emb.add_field(name="Banco", value=f"{d_cards if ended else [d_cards[0], '?']}")
        return emb

    view = discord.ui.View()
    hit = discord.ui.Button(label="Carta", style=discord.ButtonStyle.green)
    stand = discord.ui.Button(label="Stai", style=discord.ButtonStyle.red)
    view.add_item(hit); view.add_item(stand)

    async def end(inter, res):
        for it in view.children: it.disabled = True
        conn = get_db_connection(); cur = conn.cursor()
        if res == "win": cur.execute("UPDATE users SET wallet = wallet + %s WHERE user_id = %s", (scommessa, str(interaction.user.id)))
        elif res == "lose": cur.execute("UPDATE users SET wallet = wallet - %s WHERE user_id = %s", (scommessa, str(interaction.user.id)))
        conn.commit(); cur.close(); conn.close()
        await inter.response.edit_message(embed=await create_emb(True), view=view)

    async def h_call(i):
        if i.user.id != interaction.user.id: return
        p_cards.append(deck.pop())
        if sum(p_cards) > 21: await end(i, "lose")
        else: await i.response.edit_message(embed=await create_emb())
    
    async def s_call(i):
        if i.user.id != interaction.user.id: return
        while sum(d_cards) < 17: d_cards.append(deck.pop())
        pt, dt = sum(p_cards), sum(d_cards)
        if dt > 21 or pt > dt: res = "win"
        elif pt < dt: res = "lose"
        else: res = "draw"
        await end(i, res)

    hit.callback = h_call; stand.callback = s_call
    await interaction.response.send_message(embed=await create_emb(), view=view)

@bot.tree.command(name="roulette", description="Scommetti Rosso/Nero o Numero")
async def roulette(interaction: Interaction, scommessa: int, scelta: str):
    u = get_user_data(interaction.user.id)
    if scommessa <= 0 or u['wallet'] < scommessa: return await interaction.response.send_message("❌ Fondi insufficienti.")
    n = random.randint(0, 36)
    rossi = [1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36]
    col = "verde" if n == 0 else "rosso" if n in rossi else "nero"
    vinto = False; molt = 0
    if scelta.lower() == col: vinto, molt = True, 1
    elif scelta.isdigit() and int(scelta) == n: vinto, molt = True, 35
    
    conn = get_db_connection(); cur = conn.cursor()
    if vinto: cur.execute("UPDATE users SET wallet = wallet + %s WHERE user_id = %s", (scommessa*molt, str(interaction.user.id)))
    else: cur.execute("UPDATE users SET wallet = wallet - %s WHERE user_id = %s", (scommessa, str(interaction.user.id)))
    conn.commit(); cur.close(); conn.close()
    await interaction.response.send_message(f"🎡 **{interaction.user.display_name}** ha puntato su **{scelta}**...\nUscito: **{n} {col}**. {'✅ Hai vinto!' if vinto else '❌ Hai perso.'}")

# ================= COMANDI STAFF =================

@bot.tree.command(name="staff_vedi_portafoglio", description="STAFF - Bilancio utente")
async def staff_vedi_portafoglio(interaction: Interaction, utente: discord.Member):
    if not is_staff(interaction): return await interaction.response.send_message("❌ No Staff.")
    u = get_user_data(utente.id)
    await interaction.response.send_message(f"💰 {utente.name}: Wallet {u['wallet']}$ | Bank {u['bank']}$")

@bot.tree.command(name="staff_vedi_inventario", description="STAFF - Inventario utente")
async def staff_vedi_inventario(interaction: Interaction, utente: discord.Member):
    if not is_staff(interaction): return await interaction.response.send_message("❌ No Staff.")
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT item_name, quantity FROM inventory WHERE user_id = %s", (str(utente.id),))
    items = cur.fetchall()
    cur.close(); conn.close()
    desc = "\n".join([f"{i['item_name']} x{i['quantity']}" for i in items]) if items else "Vuoto."
    await interaction.response.send_message(f"🎒 Inventario {utente.name}:\n{desc}")

@bot.tree.command(name="staff_vedi_deposito", description="STAFF - Vedi un deposito fazione")
async def staff_vedi_deposito(interaction: Interaction):
    if not is_staff(interaction): return await interaction.response.send_message("❌ No Staff.")
    await interaction.response.defer()
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("SELECT role_id FROM depositi"); fazioni_id = [r[0] for r in cur.fetchall()]
    cur.close(); conn.close()
    
    async def mostra_staff(inter, rid):
        conn_i = get_db_connection(); cur_i = conn_i.cursor(cursor_factory=RealDictCursor)
        cur_i.execute("SELECT money FROM depositi WHERE role_id = %s", (rid,))
        m = cur_i.fetchone()['money']
        cur_i.execute("SELECT item_name, quantity FROM depositi_items WHERE role_id = %s", (rid,))
        it = cur_i.fetchall()
        r_obj = inter.guild.get_role(int(rid))
        emb = discord.Embed(title=f"🏦 Ispezione: {r_obj.name if r_obj else rid}", color=discord.Color.red())
        emb.add_field(name="Soldi", value=f"{m}$", inline=False)
        lista = "\n".join([f"📦 {i['item_name']} x{i['quantity']}" for i in it]) if it else "Vuoto"
        emb.add_field(name="Oggetti", value=lista, inline=False)
        await inter.followup.send(embed=emb); cur_i.close(); conn_i.close()

    view = discord.ui.View()
    options = [discord.SelectOption(label=interaction.guild.get_role(int(rid)).name if interaction.guild.get_role(int(rid)) else rid, value=rid) for rid in fazioni_id]
    sel = discord.ui.Select(options=options[:25])
    async def call(i): 
        for it in view.children: it.disabled = True
        await i.response.edit_message(view=view); await mostra_staff(i, sel.values[0])
    sel.callback = call; view.add_item(sel)
    await interaction.followup.send("Quale deposito ispezioni?", view=view, ephemeral=True)

# ================= COMANDI ADMIN =================

@bot.tree.command(name="aggiungisoldi", description="ADMIN - Regala soldi")
async def aggiungisoldi(interaction: Interaction, utente: discord.Member, importo: int):
    if not interaction.user.guild_permissions.administrator: return
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("UPDATE users SET wallet = wallet + %s WHERE user_id = %s", (importo, str(utente.id)))
    conn.commit(); cur.close(); conn.close()
    await interaction.response.send_message(f"✅ Admin ha aggiunto **{importo}$** a {utente.mention}")

@bot.tree.command(name="rimuovisoldi", description="ADMIN - Togli soldi")
async def rimuovisoldi(interaction: Interaction, utente: discord.Member, importo: int):
    if not interaction.user.guild_permissions.administrator: return
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("UPDATE users SET wallet = GREATEST(0, wallet - %s) WHERE user_id = %s", (importo, str(utente.id)))
    conn.commit(); cur.close(); conn.close()
    await interaction.response.send_message(f"✅ Admin ha rimosso **{importo}$** a {utente.mention}")

@bot.tree.command(name="aggiungi_item", description="ADMIN - Regala item")
async def aggiungi_item(interaction: Interaction, utente: discord.Member, nome: str, quantita: int = 1):
    if not interaction.user.guild_permissions.administrator: return
    await interaction.response.defer()
    nome_e = await cerca_item_smart(interaction, nome, "items")
    if not nome_e: return
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("INSERT INTO inventory (user_id, item_name, quantity) VALUES (%s, %s, %s) ON CONFLICT (user_id, item_name) DO UPDATE SET quantity = inventory.quantity + %s", (str(utente.id), nome_e, quantita, quantita))
    conn.commit(); cur.close(); conn.close()
    await interaction.followup.send(f"✅ Admin ha dato {quantita}x **{nome_e}** a {utente.mention}")

@bot.tree.command(name="rimuovi_item", description="ADMIN - Togli item")
async def rimuovi_item(interaction: Interaction, utente: discord.Member, nome: str, quantita: int = 1):
    if not interaction.user.guild_permissions.administrator: return
    await interaction.response.defer()
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("UPDATE inventory SET quantity = GREATEST(0, quantity - %s) WHERE user_id = %s AND item_name ILIKE %s", (quantita, str(utente.id), f"%{nome}%"))
    cur.execute("DELETE FROM inventory WHERE quantity <= 0")
    conn.commit(); cur.close(); conn.close()
    await interaction.followup.send(f"✅ Admin ha rimosso {quantita}x **{nome}** a {utente.mention}")

@bot.tree.command(name="crea_item_shop", description="ADMIN - Crea item shop")
async def crea_item_shop(interaction: Interaction, nome: str, descrizione: str, prezzo: int, ruolo: discord.Role = None):
    if not interaction.user.guild_permissions.administrator: return
    rid = str(ruolo.id) if ruolo else "None"
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("INSERT INTO items (name, description, price, role_required) VALUES (%s,%s,%s,%s) ON CONFLICT (name) DO UPDATE SET price=EXCLUDED.price, description=EXCLUDED.description, role_required=EXCLUDED.role_required", (nome, descrizione, prezzo, rid))
    conn.commit(); cur.close(); conn.close()
    await interaction.response.send_message(f"✅ Item **{nome}** creato/aggiornato nello shop.")

@bot.tree.command(name="elimina_item_shop", description="ADMIN - Elimina definitivamente item dallo shop")
async def elimina_item_shop(interaction: Interaction, nome: str):
    if not interaction.user.guild_permissions.administrator: return
    await interaction.response.defer()
    nome_e = await cerca_item_smart(interaction, nome, "items")
    if not nome_e: return
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("DELETE FROM items WHERE name = %s", (nome_e,))
    conn.commit(); cur.close(); conn.close()
    await interaction.followup.send(f"🗑️ L'item **{nome_e}** è stato rimosso dallo shop.")

@bot.tree.command(name="registra_fazione", description="ADMIN - Registra ruolo fazione")
async def registra_fazione(interaction: Interaction, ruolo: discord.Role):
    if not interaction.user.guild_permissions.administrator: return
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("INSERT INTO depositi (role_id, money) VALUES (%s, 0) ON CONFLICT DO NOTHING", (str(ruolo.id),))
    conn.commit(); cur.close(); conn.close()
    await interaction.response.send_message(f"✅ Fazione **{ruolo.name}** registrata nel sistema.")

@bot.tree.command(name="wipe_utente", description="ADMIN - Reset totale utente")
async def wipe_utente(interaction: Interaction, utente: discord.Member):
    if not interaction.user.guild_permissions.administrator: return
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("UPDATE users SET wallet = 500, bank = 0 WHERE user_id = %s", (str(utente.id),))
    cur.execute("DELETE FROM inventory WHERE user_id = %s", (str(utente.id),))
    conn.commit(); cur.close(); conn.close()
    await interaction.response.send_message(f"🧹 Reset totale per **{utente.name}**.")

# ================= WEB SERVER & START =================

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"✅ {bot.user} Online! Tutti i comandi sincronizzati e pubblici.")

app = Flask("")
@app.route("/")
def home(): return "Bot Online"
def run(): app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
threading.Thread(target=run).start()

bot.run(TOKEN)
