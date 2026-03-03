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

def get_db_connection():
    try:
        # Se DATABASE_URL inizia con postgres://, psycopg2 potrebbe dare errore.
        # Render lo corregge spesso, ma qui forziamo la stabilità.
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
        await interaction.followup.send(f"❌ Nessun oggetto trovato per '{nome_input}'.", ephemeral=True)
        return None
    if len(risultati) == 1: return risultati[0]

    view = discord.ui.View()
    select = discord.ui.Select(options=[discord.SelectOption(label=n) for n in risultati[:25]])
    async def callback(i: Interaction):
        view.value = select.values[0]; view.stop()
        await i.response.defer()
    select.callback = callback
    view.add_item(select); view.value = None
    await interaction.followup.send("🤔 Più risultati, seleziona quello corretto:", view=view, ephemeral=True)
    await view.wait()
    return view.value

# ================= COMANDI ECONOMIA BASE =================

@bot.tree.command(name="portafoglio", description="Vedi i tuoi soldi")
async def portafoglio(interaction: Interaction):
    u = get_user_data(interaction.user.id)
    await interaction.response.send_message(f"💰 **Wallet:** {u['wallet']}$ | 🏦 **Banca:** {u['bank']}$", ephemeral=True)

@bot.tree.command(name="deposita", description="Metti soldi in banca")
async def deposita(interaction: Interaction, importo: int):
    u = get_user_data(interaction.user.id)
    if importo <= 0 or u['wallet'] < importo:
        return await interaction.response.send_message("❌ Importo non valido.", ephemeral=True)
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE users SET wallet = wallet - %s, bank = bank + %s WHERE user_id = %s", (importo, importo, str(interaction.user.id)))
    conn.commit(); cur.close(); conn.close()
    await interaction.response.send_message(f"✅ Depositati {importo}$ in banca.")

@bot.tree.command(name="preleva", description="Preleva dalla banca")
async def preleva(interaction: Interaction, importo: int):
    u = get_user_data(interaction.user.id)
    if importo <= 0 or u['bank'] < importo:
        return await interaction.response.send_message("❌ Importo non valido.", ephemeral=True)
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE users SET bank = bank - %s, wallet = wallet + %s WHERE user_id = %s", (importo, importo, str(interaction.user.id)))
    conn.commit(); cur.close(); conn.close()
    await interaction.response.send_message(f"✅ Prelevati {importo}$ dalla banca.")

# ================= COMANDI FAZIONE (MULTI-RUOLO) =================

@bot.tree.command(name="deposito_fazione", description="Visualizza il deposito di fazione")
async def deposito_fazione(interaction: Interaction):
    await interaction.response.defer(ephemeral=True)
    miei_ruoli = await get_miei_ruoli_fazione(interaction)
    if not miei_ruoli: return await interaction.followup.send("❌ Non sei in una fazione.")

    async def mostra(inter, rid):
        conn = get_db_connection(); cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT money FROM depositi WHERE role_id = %s", (rid,))
        m = cur.fetchone()['money']
        cur.execute("SELECT item_name, quantity FROM depositi_items WHERE role_id = %s", (rid,))
        it = cur.fetchall()
        r_obj = inter.guild.get_role(int(rid))
        emb = discord.Embed(title=f"🏦 Deposito {r_obj.name}", color=discord.Color.blue())
        emb.add_field(name="Soldi", value=f"{m}$", inline=False)
        lista = "\n".join([f"📦 {i['item_name']} x{i['quantity']}" for i in it]) if it else "Vuoto"
        emb.add_field(name="Oggetti", value=lista, inline=False)
        await inter.followup.send(embed=emb); cur.close(); conn.close()

    if len(miei_ruoli) == 1: await mostra(interaction, str(miei_ruoli[0].id))
    else:
        view = discord.ui.View()
        sel = discord.ui.Select(options=[discord.SelectOption(label=r.name, value=str(r.id)) for r in miei_ruoli])
        async def call(i): await i.response.defer(ephemeral=True); await mostra(i, sel.values[0])
        sel.callback = call; view.add_item(sel)
        await interaction.followup.send("Scegli quale deposito aprire:", view=view)

@bot.tree.command(name="deposita_soldi_fazione", description="Deposita soldi in fazione")
async def deposita_soldi_fazione(interaction: Interaction, importo: int):
    await interaction.response.defer(ephemeral=True)
    miei_ruoli = await get_miei_ruoli_fazione(interaction)
    if not miei_ruoli: return await interaction.followup.send("❌ No Fazione.")
    u = get_user_data(interaction.user.id)
    if importo <= 0 or u['wallet'] < importo: return await interaction.followup.send("❌ Fondi insufficienti.")

    async def procedi(inter, rid):
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("UPDATE users SET wallet = wallet - %s WHERE user_id = %s", (importo, str(inter.user.id)))
        cur.execute("UPDATE depositi SET money = money + %s WHERE role_id = %s", (importo, rid))
        conn.commit(); cur.close(); conn.close()
        await inter.followup.send(f"✅ Depositati {importo}$")

    if len(miei_ruoli) == 1: await procedi(interaction, str(miei_ruoli[0].id))
    else:
        view = discord.ui.View()
        sel = discord.ui.Select(options=[discord.SelectOption(label=r.name, value=str(r.id)) for r in miei_ruoli])
        async def call(i): await i.response.defer(ephemeral=True); await procedi(i, sel.values[0])
        sel.callback = call; view.add_item(sel)
        await interaction.followup.send("In quale fazione depositi?", view=view)

@bot.tree.command(name="preleva_soldi_fazione", description="Preleva soldi dalla fazione")
async def preleva_soldi_fazione(interaction: Interaction, importo: int):
    await interaction.response.defer(ephemeral=True)
    miei_ruoli = await get_miei_ruoli_fazione(interaction)
    if not miei_ruoli: return await interaction.followup.send("❌ No Fazione.")

    async def procedi(inter, rid):
        conn = get_db_connection(); cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT money FROM depositi WHERE role_id = %s", (rid,))
        if cur.fetchone()['money'] < importo: return await inter.followup.send("❌ Fondi fazione insufficienti.")
        cur.execute("UPDATE depositi SET money = money - %s WHERE role_id = %s", (importo, rid))
        cur.execute("UPDATE users SET wallet = wallet + %s WHERE user_id = %s", (importo, str(inter.user.id)))
        conn.commit(); cur.close(); conn.close()
        await inter.followup.send(f"💸 Prelevati {importo}$")

    if len(miei_ruoli) == 1: await procedi(interaction, str(miei_ruoli[0].id))
    else:
        view = discord.ui.View()
        sel = discord.ui.Select(options=[discord.SelectOption(label=r.name, value=str(r.id)) for r in miei_ruoli])
        async def call(i): await i.response.defer(ephemeral=True); await procedi(i, sel.values[0])
        sel.callback = call; view.add_item(sel)
        await interaction.followup.send("Da quale fazione prelevi?", view=view)

@bot.tree.command(name="deposita_item_fazione", description="Metti un item in fazione")
async def deposita_item_fazione(interaction: Interaction, nome: str, quantita: int = 1):
    await interaction.response.defer(ephemeral=True)
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
        await inter.followup.send(f"✅ Depositati {quantita}x {nome_e}")

    if len(miei_ruoli) == 1: await procedi(interaction, str(miei_ruoli[0].id))
    else:
        view = discord.ui.View()
        sel = discord.ui.Select(options=[discord.SelectOption(label=r.name, value=str(r.id)) for r in miei_ruoli])
        async def call(i): await i.response.defer(ephemeral=True); await procedi(i, sel.values[0])
        sel.callback = call; view.add_item(sel)
        await interaction.followup.send(f"In quale magazzino metti {nome_e}?", view=view)

@bot.tree.command(name="preleva_item_fazione", description="Preleva un item dalla fazione")
async def preleva_item_fazione(interaction: Interaction, nome: str, quantita: int = 1):
    await interaction.response.defer(ephemeral=True)
    miei_ruoli = await get_miei_ruoli_fazione(interaction)
    if not miei_ruoli: return await interaction.followup.send("❌ No Fazione.")

    async def procedi(inter, rid):
        nome_e = await cerca_item_smart(inter, nome, f"fazione_{rid}")
        if not nome_e: return
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("SELECT quantity FROM depositi_items WHERE role_id = %s AND item_name = %s", (rid, nome_e))
        res = cur.fetchone()
        if not res or res[0] < quantita: return await inter.followup.send("❌ Quantità insufficiente.")
        cur.execute("UPDATE depositi_items SET quantity = quantity - %s WHERE role_id = %s AND item_name = %s", (quantita, rid, nome_e))
        cur.execute("INSERT INTO inventory (user_id, item_name, quantity) VALUES (%s, %s, %s) ON CONFLICT (user_id, item_name) DO UPDATE SET quantity = inventory.quantity + %s", (str(inter.user.id), nome_e, quantita, quantita))
        cur.execute("DELETE FROM depositi_items WHERE quantity <= 0")
        conn.commit(); cur.close(); conn.close()
        await inter.followup.send(f"📦 Prelevati {quantita}x {nome_e}")

    if len(miei_ruoli) == 1: await procedi(interaction, str(miei_ruoli[0].id))
    else:
        view = discord.ui.View()
        sel = discord.ui.Select(options=[discord.SelectOption(label=r.name, value=str(r.id)) for r in miei_ruoli])
        async def call(i): await i.response.defer(ephemeral=True); await procedi(i, sel.values[0])
        sel.callback = call; view.add_item(sel)
        await interaction.followup.send(f"Da quale magazzino prelevi?", view=view)
# ================= COMANDI ADMIN & SHOP (SUPABASE) =================

@bot.tree.command(name="rimuovisoldi", description="ADMIN - Togli soldi a un utente")
async def rimuovisoldi(interaction: Interaction, utente: discord.Member, importo: int):
    if not interaction.user.guild_permissions.administrator: return
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("UPDATE users SET wallet = GREATEST(0, wallet - %s) WHERE user_id = %s", (importo, str(utente.id)))
    conn.commit(); cur.close(); conn.close()
    await interaction.response.send_message(f"✅ Rimossi **{importo}$** dal portafoglio di {utente.mention}.")

@bot.tree.command(name="aggiungi_item", description="ADMIN - Regala un oggetto a un utente")
async def aggiungi_item(interaction: Interaction, utente: discord.Member, nome: str, quantita: int = 1):
    if not interaction.user.guild_permissions.administrator: return
    await interaction.response.defer(ephemeral=True)
    nome_e = await cerca_item_smart(interaction, nome, "items") # Cerca se l'item esiste nello shop
    if not nome_e: return

    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("""
        INSERT INTO inventory (user_id, item_name, quantity) 
        VALUES (%s, %s, %s) 
        ON CONFLICT (user_id, item_name) 
        DO UPDATE SET quantity = inventory.quantity + %s
    """, (str(utente.id), nome_e, quantita, quantita))
    conn.commit(); cur.close(); conn.close()
    await interaction.followup.send(f"✅ Aggiunti {quantita}x **{nome_e}** a {utente.mention}.")

@bot.tree.command(name="rimuovi_item", description="ADMIN - Togli un oggetto a un utente")
async def rimuovi_item(interaction: Interaction, utente: discord.Member, nome: str, quantita: int = 1):
    if not interaction.user.guild_permissions.administrator: return
    await interaction.response.defer(ephemeral=True)
    
    conn = get_db_connection(); cur = conn.cursor()
    # Cerchiamo l'item nell'inventario dell'utente
    cur.execute("SELECT item_name FROM inventory WHERE user_id = %s AND item_name ILIKE %s", (str(utente.id), f"%{nome}%"))
    res = cur.fetchone()
    if not res: return await interaction.followup.send("❌ L'utente non ha questo oggetto.")
    nome_e = res[0]

    cur.execute("UPDATE inventory SET quantity = GREATEST(0, quantity - %s) WHERE user_id = %s AND item_name = %s", (quantita, str(utente.id), nome_e))
    cur.execute("DELETE FROM inventory WHERE quantity <= 0")
    conn.commit(); cur.close(); conn.close()
    await interaction.followup.send(f"✅ Rimossi {quantita}x **{nome_e}** a {utente.mention}.")

@bot.tree.command(name="compra", description="Compra un oggetto dal negozio")
async def compra(interaction: Interaction, nome: str, quantita: int = 1):
    await interaction.response.defer(ephemeral=True)
    nome_e = await cerca_item_smart(interaction, nome, "items")
    if not nome_e: return

    conn = get_db_connection(); cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM items WHERE name = %s", (nome_e,))
    item = cur.fetchone()
    
    u = get_user_data(interaction.user.id)
    prezzo_totale = item['price'] * quantita

    # Controllo Ruolo (se l'item richiede un ruolo fazione)
    if item['role_required'] != "None":
        if not any(str(r.id) == item['role_required'] for r in interaction.user.roles):
            return await interaction.followup.send(f"❌ Non hai il grado necessario per comprare questo oggetto.")

    if u['wallet'] < prezzo_totale:
        return await interaction.followup.send(f"❌ Non hai abbastanza soldi. Ti servono **{prezzo_totale}$**.")

    # Esecuzione acquisto
    cur.execute("UPDATE users SET wallet = wallet - %s WHERE user_id = %s", (prezzo_totale, str(interaction.user.id)))
    cur.execute("""
        INSERT INTO inventory (user_id, item_name, quantity) 
        VALUES (%s, %s, %s) 
        ON CONFLICT (user_id, item_name) 
        DO UPDATE SET quantity = inventory.quantity + %s
    """, (str(interaction.user.id), nome_e, quantita, quantita))
    
    conn.commit(); cur.close(); conn.close()
    await interaction.followup.send(f"🛍️ Hai comprato {quantita}x **{nome_e}** per **{prezzo_totale}$**!")

# ================= SHOP & GIOCHI =================

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

@bot.tree.command(name="cerca", description="Cerca materiali (1 min)")
async def cerca(interaction: Interaction):
    await interaction.response.send_message("🔍 Stai cercando... torna tra 1 minuto.")
    await asyncio.sleep(60)
    mat = random.choice(["Ferro", "Rame", "Plastica", "Legno"])
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("INSERT INTO inventory (user_id, item_name, quantity) VALUES (%s, %s, 1) ON CONFLICT (user_id, item_name) DO UPDATE SET quantity = inventory.quantity + 1", (str(interaction.user.id), mat))
    conn.commit(); cur.close(); conn.close()
    await interaction.followup.send(f"✅ Hai trovato: **{mat}**!")

# ================= GIOCHI D'AZZARDO (SUPABASE) =================

@bot.tree.command(name="blackjack", description="Gioca a Blackjack contro il banco")
async def blackjack(interaction: Interaction, scommessa: int):
    if scommessa <= 0: 
        return await interaction.response.send_message("❌ La scommessa deve essere maggiore di 0.", ephemeral=True)
    
    u = get_user_data(interaction.user.id)
    if u['wallet'] < scommessa:
        return await interaction.response.send_message("❌ Non hai abbastanza soldi nel portafoglio.", ephemeral=True)

    def get_deck():
        cards = [2, 3, 4, 5, 6, 7, 8, 9, 10, 10, 10, 10, 11] * 4
        random.shuffle(cards)
        return cards

    deck = get_deck()
    player_cards = [deck.pop(), deck.pop()]
    dealer_cards = [deck.pop(), deck.pop()]

    async def create_bj_embed(p_cards, d_cards, ended=False):
        p_score = sum(p_cards)
        d_score = sum(d_cards)
        emb = discord.Embed(title="🃏 Blackjack", color=discord.Color.blue())
        emb.add_field(name="Le tue carte", value=f"{', '.join(map(str, p_cards))} (Totale: **{p_score}**)", inline=False)
        dealer_val = f"{', '.join(map(str, d_cards))} (Totale: **{d_score}**)" if ended else f"{d_cards[0]}, ?"
        emb.add_field(name="Banco", value=dealer_val, inline=False)
        return emb

    view = discord.ui.View()
    hit_btn = discord.ui.Button(label="Carta", style=discord.ButtonStyle.green)
    stand_btn = discord.ui.Button(label="Stai", style=discord.ButtonStyle.red)
    view.add_item(hit_btn)
    view.add_item(stand_btn)

    await interaction.response.send_message(embed=await create_bj_embed(player_cards, dealer_cards), view=view)

    async def end_game(inter, result):
        conn = get_db_connection()
        cur = conn.cursor()
        if result == "win":
            cur.execute("UPDATE users SET wallet = wallet + %s WHERE user_id = %s", (scommessa, str(interaction.user.id)))
            msg = f"🏆 Hai vinto **{scommessa}$**!"
        elif result == "lose":
            cur.execute("UPDATE users SET wallet = wallet - %s WHERE user_id = %s", (scommessa, str(interaction.user.id)))
            msg = f"💀 Hai perso **{scommessa}$**."
        else:
            msg = "🤝 Pareggio, i soldi restano a te."
        
        conn.commit()
        cur.close(); conn.close()
        
        emb = await create_bj_embed(player_cards, dealer_cards, True)
        emb.set_footer(text=msg)
        await inter.edit_original_response(embed=emb, view=None)

    async def hit_callback(i: Interaction):
        if i.user.id != interaction.user.id: return
        player_cards.append(deck.pop())
        if sum(player_cards) > 21:
            view.stop()
            await end_game(i, "lose")
        else:
            await i.response.edit_message(embed=await create_bj_embed(player_cards, dealer_cards))

    async def stand_callback(i: Interaction):
        if i.user.id != interaction.user.id: return
        view.stop()
        while sum(dealer_cards) < 17:
            dealer_cards.append(deck.pop())
        
        p_total, d_total = sum(player_cards), sum(dealer_cards)
        if d_total > 21 or p_total > d_total: res = "win"
        elif p_total < d_total: res = "lose"
        else: res = "draw"
        await i.response.defer()
        await end_game(i, res)

    hit_btn.callback = hit_callback
    stand_btn.callback = stand_callback

@bot.tree.command(name="roulette", description="Scommetti su un colore (rosso/nero) o un numero (0-36)")
async def roulette(interaction: Interaction, scommessa: int, scelta: str):
    await interaction.response.defer()
    u = get_user_data(interaction.user.id)
    
    if scommessa <= 0 or u['wallet'] < scommessa:
        return await interaction.followup.send("❌ Fondi insufficienti o scommessa non valida.")

    numero_vincente = random.randint(0, 36)
    rossi = [1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36]
    
    if numero_vincente == 0: colore_vincente = "verde"
    elif numero_vincente in rossi: colore_vincente = "rosso"
    else: colore_vincente = "nero"

    vinto = False
    moltiplicatore = 0
    scelta_pulita = scelta.lower().strip()

    # Logica Vittoria
    if scelta_pulita == colore_vincente:
        vinto = True
        moltiplicatore = 1 # Raddoppia la posta
    elif scelta_pulita.isdigit() and int(scelta_pulita) == numero_vincente:
        vinto = True
        moltiplicatore = 35 # 35 volte la posta

    conn = get_db_connection()
    cur = conn.cursor()
    
    if vinto:
        premio = scommessa * moltiplicatore
        cur.execute("UPDATE users SET wallet = wallet + %s WHERE user_id = %s", (premio, str(interaction.user.id)))
        color_emoji = "🔴" if colore_vincente == "rosso" else "⚫" if colore_vincente == "nero" else "🟢"
        result_text = f"🎡 Risultato: **{numero_vincente} {color_emoji}**\n✅ Complimenti! Hai vinto **{premio}$**!"
    else:
        cur.execute("UPDATE users SET wallet = wallet - %s WHERE user_id = %s", (scommessa, str(interaction.user.id)))
        color_emoji = "🔴" if colore_vincente == "rosso" else "⚫" if colore_vincente == "nero" else "🟢"
        result_text = f"🎡 Risultato: **{numero_vincente} {color_emoji}**\n❌ Mi dispiace, hai perso **{scommessa}$**."
    
    conn.commit()
    cur.close(); conn.close()
    await interaction.followup.send(result_text)

# ================= COMANDI ADMIN =================

@bot.tree.command(name="aggiungisoldi", description="ADMIN - Regala soldi")
async def aggiungisoldi(interaction: Interaction, utente: discord.Member, importo: int):
    if not interaction.user.guild_permissions.administrator: return
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("UPDATE users SET wallet = wallet + %s WHERE user_id = %s", (importo, str(utente.id)))
    conn.commit(); cur.close(); conn.close()
    await interaction.response.send_message(f"✅ Aggiunti {importo}$ a {utente.mention}")

@bot.tree.command(name="wipe_utente", description="ADMIN - RESET TOTALE")
async def wipe_utente(interaction: Interaction, utente: discord.Member):
    if not interaction.user.guild_permissions.administrator: return
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("UPDATE users SET wallet = 500, bank = 0 WHERE user_id = %s", (str(utente.id),))
    cur.execute("DELETE FROM inventory WHERE user_id = %s", (str(utente.id),))
    conn.commit(); cur.close(); conn.close()
    await interaction.response.send_message(f"🧹 Reset completato per {utente.mention}")

@bot.tree.command(name="registra_fazione", description="ADMIN - Registra ruolo")
async def registra_fazione(interaction: Interaction, ruolo: discord.Role):
    if not interaction.user.guild_permissions.administrator: return
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("INSERT INTO depositi (role_id, money) VALUES (%s, 0) ON CONFLICT DO NOTHING", (str(ruolo.id),))
    conn.commit(); cur.close(); conn.close()
    await interaction.response.send_message(f"✅ Fazione {ruolo.name} registrata.")

@bot.tree.command(name="crea_item_shop", description="ADMIN - Crea item")
async def crea_item_shop(interaction: Interaction, nome: str, descrizione: str, prezzo: int, ruolo: discord.Role = None):
    if not interaction.user.guild_permissions.administrator: return
    rid = str(ruolo.id) if ruolo else "None"
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("INSERT INTO items (name, description, price, role_required) VALUES (%s,%s,%s,%s) ON CONFLICT (name) DO UPDATE SET price=EXCLUDED.price", (nome, descrizione, prezzo, rid))
    conn.commit(); cur.close(); conn.close()
    await interaction.response.send_message(f"✅ Item {nome} creato.")

# ID del ruolo staff fornito
RUOLO_STAFF_ID = 1465412245264662734

# Helper per controllare se l'utente è staff
def is_staff(interaction: discord.Interaction):
    return any(role.id == RUOLO_STAFF_ID for role in interaction.user.roles)

# ================= COMANDI VISUALIZZAZIONE STAFF =================

@bot.tree.command(name="staff_vedi_portafoglio", description="STAFF - Vedi i soldi di un utente")
async def staff_vedi_portafoglio(interaction: Interaction, utente: discord.Member):
    if not is_staff(interaction):
        return await interaction.response.send_message("❌ Non hai il ruolo Staff per usare questo comando.", ephemeral=True)
    
    await interaction.response.defer(ephemeral=True)
    u = get_user_data(utente.id)
    
    embed = discord.Embed(title=f"💰 Bilancio di {utente.display_name}", color=discord.Color.gold())
    embed.add_field(name="Portafoglio", value=f"{u['wallet']}$", inline=True)
    embed.add_field(name="Banca", value=f"{u['bank']}$", inline=True)
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="staff_vedi_inventario", description="STAFF - Vedi l'inventario di un utente")
async def staff_vedi_inventario(interaction: Interaction, utente: discord.Member):
    if not is_staff(interaction):
        return await interaction.response.send_message("❌ Non hai il ruolo Staff.", ephemeral=True)
    
    await interaction.response.defer(ephemeral=True)
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT item_name, quantity FROM inventory WHERE user_id = %s", (str(utente.id),))
    items = cur.fetchall()
    cur.close(); conn.close()

    embed = discord.Embed(title=f"🎒 Inventario di {utente.display_name}", color=discord.Color.blue())
    if items:
        desc = "\n".join([f"📦 **{i['item_name']}** x{i['quantity']}" for i in items])
        embed.description = desc
    else:
        embed.description = "*L'inventario è vuoto.*"
    
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="staff_vedi_deposito", description="STAFF - Vedi un deposito fazione")
async def staff_vedi_deposito(interaction: Interaction):
    if not is_staff(interaction):
        return await interaction.response.send_message("❌ Non hai il ruolo Staff.", ephemeral=True)
    
    await interaction.response.defer(ephemeral=True)
    
    # Lo staff vede TUTTE le fazioni registrate nel DB
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT role_id FROM depositi")
    fazioni_id = [r[0] for r in cur.fetchall()]
    cur.close(); conn.close()

    if not fazioni_id:
        return await interaction.followup.send("❌ Non ci sono fazioni registrate nel database.")

    async def mostra_staff(inter, rid):
        conn_i = get_db_connection(); cur_i = conn_i.cursor(cursor_factory=RealDictCursor)
        cur_i.execute("SELECT money FROM depositi WHERE role_id = %s", (rid,))
        m = cur_i.fetchone()['money']
        cur_i.execute("SELECT item_name, quantity FROM depositi_items WHERE role_id = %s", (rid,))
        it = cur_i.fetchall()
        r_obj = inter.guild.get_role(int(rid))
        
        emb = discord.Embed(title=f"🏦 Ispezione Deposito: {r_obj.name if r_obj else rid}", color=discord.Color.red())
        emb.add_field(name="Soldi", value=f"{m}$", inline=False)
        lista = "\n".join([f"📦 {i['item_name']} x{i['quantity']}" for i in it]) if it else "Vuoto"
        emb.add_field(name="Oggetti", value=lista, inline=False)
        await inter.followup.send(embed=emb); cur_i.close(); conn_i.close()

    # Menu di selezione per lo staff
    view = discord.ui.View()
    options = []
    for rid in fazioni_id:
        role = interaction.guild.get_role(int(rid))
        label = role.name if role else f"ID: {rid}"
        options.append(discord.SelectOption(label=label, value=rid))
    
    select = discord.ui.Select(placeholder="Scegli quale fazione ispezionare...", options=options[:25])
    async def callback(i):
        await i.response.defer(ephemeral=True)
        await mostra_staff(i, select.values[0])
    
    select.callback = callback
    view.add_item(select)
    await interaction.followup.send("🕵️ Ispezione Staff: Quale deposito vuoi controllare?", view=view)

@bot.tree.command(name="inventario", description="Mostra gli oggetti nel tuo zaino")
async def inventario(interaction: Interaction):
    await interaction.response.defer(ephemeral=True)
    
    conn = get_db_connection()
    if not conn:
        return await interaction.followup.send("❌ Errore di connessione al database.")
    
    cur = conn.cursor(cursor_factory=RealDictCursor)
    # Recupera gli oggetti solo per l'utente che ha lanciato il comando
    cur.execute("SELECT item_name, quantity FROM inventory WHERE user_id = %s", (str(interaction.user.id),))
    items = cur.fetchall()
    cur.close()
    conn.close()

    embed = discord.Embed(
        title="🎒 Il Tuo Inventario", 
        color=discord.Color.blue(),
        description=f"Lista degli oggetti di {interaction.user.display_name}"
    )
    
    if items:
        # Formatta la lista degli oggetti (es: 📦 Ferro x5)
        lista_oggetti = "\n".join([f"📦 **{i['item_name']}** x{i['quantity']}" for i in items])
        embed.description = lista_oggetti
    else:
        embed.description = "*Il tuo zaino è attualmente vuoto.*"
    
    embed.set_footer(text="Solo tu puoi vedere questo messaggio")
    await interaction.followup.send(embed=embed)


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

