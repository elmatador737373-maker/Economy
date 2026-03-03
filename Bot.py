import discord
from discord import app_commands, Interaction
from discord.ext import commands
import sqlite3
import random
import os
import threading
import asyncio
from flask import Flask

# ================= CONFIGURAZIONE =================
TOKEN = os.environ.get("TOKEN")
intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Connessione DB (check_same_thread=False per Flask)
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

# ================= MOTORE DI RICERCA INTELLIGENTE =================

async def cerca_item_smart(interaction: Interaction, nome_input: str, tabella="items"):
    if tabella == "items":
        cursor.execute("SELECT name FROM items WHERE name LIKE ?", (f"%{nome_input}%",))
    elif tabella == "inventory":
        cursor.execute("SELECT item_name FROM inventory WHERE user_id = ? AND item_name LIKE ?", (str(interaction.user.id), f"%{nome_input}%"))
    else: 
        cursor.execute("SELECT role_id FROM depositi")
        validi = [r[0] for r in cursor.fetchall()]
        my_role = next((str(r.id) for r in interaction.user.roles if str(r.id) in validi), None)
        if not my_role: return "NO_ROLE"
        cursor.execute("SELECT item_name FROM depositi_items WHERE role_id = ? AND item_name LIKE ?", (my_role, f"%{nome_input}%"))

    risultati = list(set([r[0] for r in cursor.fetchall()]))
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
# ================= SISTEMA NEGOZIO (SHOP) =================

@bot.tree.command(name="shop", description="Mostra la lista degli oggetti in vendita")
async def shop(interaction: discord.Interaction):
    # Usiamo defer perché se lo shop ha molti item il caricamento dell'embed può richiedere tempo
    await interaction.response.defer()

    cursor.execute("SELECT name, description, price, role_required FROM items")
    rows = cursor.fetchall()

    if not rows:
        return await interaction.followup.send("🏪 Il negozio è attualmente vuoto. Torna più tardi!")

    embed = discord.Embed(
        title="🏪 Emporio della Città", 
        description="Usa `/compra [nome]` per acquistare un oggetto.",
        color=discord.Color.gold()
    )

    for nome, descrizione, prezzo, ruolo_id in rows:
        # Controlla se l'oggetto ha un requisito di ruolo
        requisito = f"\n⚠️ **Richiede:** <@&{ruolo_id}>" if ruolo_id != "None" else ""
        
        embed.add_field(
            name=f"{nome} — {prezzo}$",
            value=f"*{descrizione}*{requisito}",
            inline=False
        )

    embed.set_footer(text="I prezzi sono IVA inclusa")
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="compra", description="Acquista un oggetto dal negozio (usa la ricerca intelligente)")
async def compra(interaction: discord.Interaction, nome: str):
    await interaction.response.defer(ephemeral=True)
    
    # Utilizza la funzione cerca_item_smart che abbiamo messo sopra nel codice
    nome_esatto = await cerca_item_smart(interaction, nome, "items")
    if not nome_esatto:
        return # Errore gestito dalla funzione smart

    # Recupera i dati dell'utente e dell'item
    user = get_user_data(interaction.user.id)
    cursor.execute("SELECT price, role_required FROM items WHERE name = ?", (nome_esatto,))
    item_data = cursor.fetchone()
    
    prezzo, ruolo_id = item_data

    # 1. Controllo Soldi
    if user[1] < prezzo:
        return await interaction.followup.send(f"❌ Non hai abbastanza soldi! Ti mancano {prezzo - user[1]}$.")

    # 2. Controllo Ruolo (se presente)
    if ruolo_id != "None":
        role_obj = interaction.guild.get_role(int(ruolo_id))
        if role_obj not in interaction.user.roles:
            return await interaction.followup.send(f"⚠️ Questo oggetto è riservato ai membri con il ruolo {role_obj.mention}.")

    # 3. Transazione
    cursor.execute("UPDATE users SET wallet = wallet - ? WHERE user_id = ?", (prezzo, str(interaction.user.id)))
    cursor.execute("""
        INSERT INTO inventory (user_id, item_name, quantity) VALUES (?, ?, 1)
        ON CONFLICT(user_id, item_name) DO UPDATE SET quantity = quantity + 1
    """, (str(interaction.user.id), nome_esatto))
    
    conn.commit()
    
    await interaction.followup.send(f"🛍️ Hai acquistato **{nome_esatto}** per **{prezzo}$**! L'oggetto è ora nel tuo `/inventario`.")

# ================= COMANDI DEPOSITO FAZIONE (SOLDI E OGGETTI) =================

@bot.tree.command(name="deposito_fazione_info", description="Visualizza il contenuto del deposito della tua fazione")
async def deposito_fazione_info(interaction: Interaction):
    await interaction.response.defer(ephemeral=True)
    
    # Recupero ruoli fazione registrati
    cursor.execute("SELECT role_id FROM depositi")
    validi = [r[0] for r in cursor.fetchall()]
    my_role = next((str(r.id) for r in interaction.user.roles if str(r.id) in validi), None)
    
    if not my_role:
        return await interaction.followup.send("❌ Non appartieni a nessuna fazione con un deposito registrato.")

    # Recupero Soldi
    cursor.execute("SELECT money FROM depositi WHERE role_id = ?", (my_role,))
    soldi = cursor.fetchone()[0]

    # Recupero Oggetti
    cursor.execute("SELECT item_name, quantity FROM depositi_items WHERE role_id = ?", (my_role,))
    items = cursor.fetchall()
    
    embed = discord.Embed(title=f"🏦 Deposito Fazione: {interaction.guild.get_role(int(my_role)).name}", color=discord.Color.gold())
    embed.add_field(name="💰 Denaro", value=f"**{soldi}$**", inline=False)
    
    if items:
        lista_items = "\n".join([f"📦 **{i[0]}** x{i[1]}" for i in items])
        embed.add_field(name="📦 Oggetti", value=lista_items, inline=False)
    else:
        embed.add_field(name="📦 Oggetti", value="*Nessun oggetto in deposito*", inline=False)

    await interaction.followup.send(embed=embed)

@bot.tree.command(name="deposita_soldi_fazione", description="Deposita denaro nel fondo fazione")
async def deposita_soldi_fazione(interaction: Interaction, importo: int):
    await interaction.response.defer(ephemeral=True)
    if importo <= 0: return await interaction.followup.send("❌ Importo non valido.")
    
    user = get_user_data(interaction.user.id)
    if user[1] < importo: return await interaction.followup.send("❌ Non hai abbastanza soldi nel portafoglio.")

    cursor.execute("SELECT role_id FROM depositi")
    validi = [r[0] for r in cursor.fetchall()]
    my_role = next((str(r.id) for r in interaction.user.roles if str(r.id) in validi), None)
    
    if not my_role: return await interaction.followup.send("❌ Non hai ruoli fazione.")

    cursor.execute("UPDATE users SET wallet = wallet - ? WHERE user_id = ?", (importo, str(interaction.user.id)))
    cursor.execute("UPDATE depositi SET money = money + ? WHERE role_id = ?", (importo, my_role))
    conn.commit()
    await interaction.followup.send(f"✅ Hai depositato **{importo}$** nel deposito fazione.")

@bot.tree.command(name="preleva_soldi_fazione", description="Preleva denaro dal fondo fazione")
async def preleva_soldi_fazione(interaction: Interaction, importo: int):
    await interaction.response.defer(ephemeral=True)
    
    cursor.execute("SELECT role_id FROM depositi")
    validi = [r[0] for r in cursor.fetchall()]
    my_role = next((str(r.id) for r in interaction.user.roles if str(r.id) in validi), None)
    
    if not my_role: return await interaction.followup.send("❌ Non hai ruoli fazione.")

    cursor.execute("SELECT money FROM depositi WHERE role_id = ?", (my_role,))
    cassa = cursor.fetchone()[0]
    
    if cassa < importo: return await interaction.followup.send("❌ La fazione non ha abbastanza soldi.")

    cursor.execute("UPDATE depositi SET money = money - ? WHERE role_id = ?", (importo, my_role))
    cursor.execute("UPDATE users SET wallet = wallet + ? WHERE user_id = ?", (importo, str(interaction.user.id)))
    conn.commit()
    await interaction.followup.send(f"💸 Hai prelevato **{importo}$** dalla cassa fazione.")

@bot.tree.command(name="preleva_item_fazione", description="Preleva un oggetto dal deposito fazione")
async def preleva_item_fazione(interaction: Interaction, nome: str, quantita: int = 1):
    await interaction.response.defer(ephemeral=True)
    
    # Ricerca intelligente nel deposito fazione
    nome_esatto = await cerca_item_smart(interaction, nome, "depositi_items")
    if nome_esatto == "NO_ROLE": return await interaction.followup.send("❌ Non hai ruoli fazione.")
    if not nome_esatto: return

    cursor.execute("SELECT role_id FROM depositi")
    validi = [r[0] for r in cursor.fetchall()]
    my_role = next((str(r.id) for r in interaction.user.roles if str(r.id) in validi), None)

    cursor.execute("SELECT quantity FROM depositi_items WHERE role_id = ? AND item_name = ?", (my_role, nome_esatto))
    disp = cursor.fetchone()[0]
    
    if disp < quantita: return await interaction.followup.send(f"❌ Nel deposito ci sono solo {disp}x di questo oggetto.")

    cursor.execute("UPDATE depositi_items SET quantity = quantity - ? WHERE role_id = ? AND item_name = ?", (quantita, my_role, nome_esatto))
    cursor.execute("INSERT INTO inventory (user_id, item_name, quantity) VALUES (?, ?, ?) ON CONFLICT(user_id, item_name) DO UPDATE SET quantity = quantity + ?", (str(interaction.user.id), nome_esatto, quantita, quantita))
    cursor.execute("DELETE FROM depositi_items WHERE quantity <= 0")
    conn.commit()
    await interaction.followup.send(f"📦 Hai prelevato {quantita}x **{nome_esatto}** dal deposito.")

@bot.tree.command(name="registra_fazione", description="ADMIN - Registra un ruolo come fazione con deposito")
async def registra_fazione(interaction: Interaction, ruolo: discord.Role):
    await interaction.response.defer(ephemeral=True)
    if not interaction.user.guild_permissions.administrator: return await interaction.followup.send("❌ Solo gli admin possono farlo.")
    
    cursor.execute("INSERT OR IGNORE INTO depositi (role_id, money) VALUES (?, 0)", (str(ruolo.id),))
    conn.commit()
    await interaction.followup.send(f"🏢 Il ruolo {ruolo.mention} è stato registrato come fazione con deposito.")


# ================= GIOCHI E ATTIVITÀ =================

@bot.tree.command(name="cerca", description="Cerca oggetti tra i rifiuti (richiede 1 minuto)")
async def cerca(interaction: Interaction):
    await interaction.response.defer()
    await interaction.followup.send("🔍 Hai iniziato a cercare tra i rifiuti... ci vorrà circa un minuto. Attendi.")
    
    await asyncio.sleep(60) # Attesa realistica di 1 minuto

    loot = random.choices(["Rame", "Ferro", "Plastica", "Nulla"], weights=[20, 15, 25, 40])[0]
    if loot == "Nulla":
        return await interaction.followup.send(f"⚠️ {interaction.user.mention}, non hai trovato nulla questa volta.")
    
    cursor.execute("INSERT INTO inventory (user_id, item_name, quantity) VALUES (?, ?, 1) ON CONFLICT(user_id, item_name) DO UPDATE SET quantity = quantity + 1", (str(interaction.user.id), loot))
    conn.commit()
    await interaction.followup.send(f"📦 {interaction.user.mention}, hai trovato: **{loot}**!")

# --- BLACKJACK ---
class BlackjackView(discord.ui.View):
    def __init__(self, interaction, scommessa, user_id, deck):
        super().__init__(timeout=60)
        self.interaction, self.scommessa, self.user_id, self.deck = interaction, scommessa, user_id, deck
        self.player_hand = [self.deck.pop(), self.deck.pop()]
        self.dealer_hand = [self.deck.pop(), self.deck.pop()]

    def get_score(self, hand):
        score, aces = 0, 0
        for card in hand:
            val = card.split()[0]
            if val in ['J', 'Q', 'K']: score += 10
            elif val == 'A': aces += 1; score += 11
            else: score += int(val)
        while score > 21 and aces: score -= 10; aces -= 1
        return score

    def create_embed(self, title, color, finished=False):
        embed = discord.Embed(title=title, color=color)
        p_score = self.get_score(self.player_hand)
        d_score = self.get_score(self.dealer_hand) if finished else "?"
        d_cards = ", ".join(self.dealer_hand) if finished else f"{self.dealer_hand[0]}, ❓"
        embed.add_field(name="🃏 Tua Mano", value=f"`{', '.join(self.player_hand)}` (Punti: **{p_score}**)")
        embed.add_field(name="🏛️ Dealer", value=f"`{d_cards}` (Punti: **{d_score}**)")
        return embed

    @discord.ui.button(label="Carta", style=discord.ButtonStyle.green)
    async def hit(self, inter: Interaction, button: discord.ui.Button):
        if str(inter.user.id) != self.user_id: return
        self.player_hand.append(self.deck.pop())
        if self.get_score(self.player_hand) > 21:
            await self.end_game(inter, "HAI SBALLATO! ❌", discord.Color.red(), "perso")
        else:
            await inter.response.edit_message(embed=self.create_embed("Blackjack - In corso", discord.Color.blue()))

    @discord.ui.button(label="Stai", style=discord.ButtonStyle.grey)
    async def stand(self, inter: Interaction, button: discord.ui.Button):
        if str(inter.user.id) != self.user_id: return
        while self.get_score(self.dealer_hand) < 17: self.dealer_hand.append(self.deck.pop())
        p_s, d_s = self.get_score(self.player_hand), self.get_score(self.dealer_hand)
        if d_s > 21 or p_s > d_s: res, msg, col = "vinto", "HAI VINTO! 🎉", discord.Color.green()
        elif p_s < d_s: res, msg, col = "perso", "IL BANCO VINCE! 🏛️", discord.Color.red()
        else: res, msg, col = "pareggio", "PAREGGIO! ⚖️", discord.Color.gold()
        await self.end_game(inter, msg, col, res)

    async def end_game(self, inter, msg, color, result):
        self.stop()
        if result == "vinto": cursor.execute("UPDATE users SET wallet = wallet + ? WHERE user_id = ?", (self.scommessa, self.user_id))
        elif result == "perso": cursor.execute("UPDATE users SET wallet = wallet - ? WHERE user_id = ?", (self.scommessa, self.user_id))
        conn.commit()
        await inter.response.edit_message(embed=self.create_embed(msg, color, True), view=None)

@bot.tree.command(name="blackjack", description="Gioca contro il banco")
async def blackjack(interaction: Interaction, scommessa: int):
    await interaction.response.defer()
    user = get_user_data(interaction.user.id)
    if scommessa <= 0 or user[1] < scommessa: return await interaction.followup.send("❌ Fondi insufficienti.")
    deck = [f"{v} {s}" for v in ['2','3','4','5','6','7','8','9','10','J','Q','K','A'] for s in ['❤️','♦️','♣️','♠️']]
    random.shuffle(deck)
    view = BlackjackView(interaction, scommessa, str(interaction.user.id), deck)
    await interaction.followup.send(embed=view.create_embed("Tavolo da Blackjack", discord.Color.blue()), view=view)

# --- ROULETTE ---
@bot.tree.command(name="roulette", description="Scommetti sul colore")
@app_commands.choices(colore=[app_commands.Choice(name="Rosso (x2)", value="rosso"), app_commands.Choice(name="Nero (x2)", value="nero"), app_commands.Choice(name="Verde (x14)", value="verde")])
async def roulette(interaction: Interaction, scommessa: int, colore: str):
    await interaction.response.defer()
    user = get_user_data(interaction.user.id)
    if scommessa <= 0 or user[1] < scommessa: return await interaction.followup.send("❌ Fondi insufficienti.")
    
    msg = await interaction.followup.send(embed=discord.Embed(title="🎰 Roulette", description="La pallina gira...", color=discord.Color.light_grey()))
    await asyncio.sleep(3)
    
    num = random.randint(0, 36)
    res_col = "verde" if num == 0 else ("rosso" if num in [1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36] else "nero")
    
    if colore == res_col:
        molt = 14 if res_col == "verde" else 2
        guadagno = scommessa * (molt - 1)
        cursor.execute("UPDATE users SET wallet = wallet + ? WHERE user_id = ?", (guadagno, str(interaction.user.id)))
        embed = discord.Embed(title="🎰 VITTORIA!", description=f"È uscito **{num} ({res_col})**! Hai vinto **{guadagno}$**", color=discord.Color.green())
    else:
        cursor.execute("UPDATE users SET wallet = wallet - ? WHERE user_id = ?", (scommessa, str(interaction.user.id)))
        embed = discord.Embed(title="🎰 SCONFITTA", description=f"È uscito **{num} ({res_col})**. Hai perso **{scommessa}$**", color=discord.Color.red())
    
    conn.commit()
    await msg.edit(embed=embed)

# ================= COMANDI ADMIN E UTENTE (Precedenti) =================

@bot.tree.command(name="portafoglio", description="Mostra i tuoi soldi")
async def portafoglio(interaction: Interaction):
    await interaction.response.defer(ephemeral=True)
    user = get_user_data(interaction.user.id)
    await interaction.followup.send(f"💰 **Portafoglio:** {user[1]}$ | 🏦 **Banca:** {user[2]}$")

@bot.tree.command(name="inventario", description="Mostra i tuoi oggetti")
async def inventario(interaction: Interaction):
    await interaction.response.defer(ephemeral=True)
    cursor.execute("SELECT item_name, quantity FROM inventory WHERE user_id = ?", (str(interaction.user.id),))
    items = cursor.fetchall()
    if not items: return await interaction.followup.send("🎒 Inventario vuoto.")
    lista = "\n".join([f"📦 **{i[0]}** x{i[1]}" for i in items])
    await interaction.followup.send(embed=discord.Embed(title="Il tuo Inventario", description=lista, color=discord.Color.blue()))


@bot.tree.command(name="crea_item_shop", description="ADMIN - Aggiungi oggetto allo shop")
async def crea_item_shop(interaction: Interaction, nome: str, descrizione: str, prezzo: int, ruolo_richiesto: discord.Role = None):
    await interaction.response.defer(ephemeral=True)
    if not interaction.user.guild_permissions.administrator: return await interaction.followup.send("❌ No Admin.")
    r_id = str(ruolo_richiesto.id) if ruolo_richiesto else "None"
    cursor.execute("INSERT OR REPLACE INTO items (name, description, price, role_required) VALUES (?, ?, ?, ?)", (nome, descrizione, prezzo, r_id))
    conn.commit()
    await interaction.followup.send(f"✅ Item **{nome}** creato.")

# ================= COMANDI AMMINISTRATORE (SOLO ADMIN) =================

@bot.tree.command(name="aggiungisoldi", description="ADMIN - Regala soldi a un utente")
async def aggiungisoldi(interaction: discord.Interaction, utente: discord.Member, importo: int):
    await interaction.response.defer(ephemeral=True)
    if not interaction.user.guild_permissions.administrator:
        return await interaction.followup.send("❌ Non hai i permessi per usare questo comando.")
    
    get_user_data(utente.id) # Assicura che l'utente sia nel database
    cursor.execute("UPDATE users SET wallet = wallet + ? WHERE user_id = ?", (importo, str(utente.id)))
    conn.commit()
    await interaction.followup.send(f"✅ Accreditati **{importo}$** nel portafoglio di {utente.mention}.")

@bot.tree.command(name="rimuovisoldi", description="ADMIN - Togli soldi a un utente")
async def rimuovisoldi(interaction: discord.Interaction, utente: discord.Member, importo: int):
    await interaction.response.defer(ephemeral=True)
    if not interaction.user.guild_permissions.administrator:
        return await interaction.followup.send("❌ Permessi insufficienti.")
    
    # MAX(0, ...) impedisce ai soldi di andare in negativo
    cursor.execute("UPDATE users SET wallet = MAX(0, wallet - ?) WHERE user_id = ?", (importo, str(utente.id)))
    conn.commit()
    await interaction.followup.send(f"✅ Rimossi **{importo}$** a {utente.mention}.")

@bot.tree.command(name="admin_aggiungi_item", description="ADMIN - Regala un oggetto a un utente")
async def admin_aggiungi_item(interaction: discord.Interaction, utente: discord.Member, item: str, quantita: int = 1):
    await interaction.response.defer(ephemeral=True)
    if not interaction.user.guild_permissions.administrator:
        return await interaction.followup.send("❌ Permessi insufficienti.")
    
    cursor.execute("""
        INSERT INTO inventory (user_id, item_name, quantity) VALUES (?, ?, ?)
        ON CONFLICT(user_id, item_name) DO UPDATE SET quantity = quantity + ?
    """, (str(utente.id), item, quantita, quantita))
    conn.commit()
    await interaction.followup.send(f"✅ Consegnati {quantita}x **{item}** a {utente.mention}.")

@bot.tree.command(name="admin_rimuovi_item", description="ADMIN - Togli un oggetto a un utente")
async def admin_rimuovi_item(interaction: discord.Interaction, utente: discord.Member, item: str, quantita: int = 1):
    await interaction.response.defer(ephemeral=True)
    if not interaction.user.guild_permissions.administrator:
        return await interaction.followup.send("❌ Permessi insufficienti.")
    
    cursor.execute("UPDATE inventory SET quantity = MAX(0, quantity - ?) WHERE user_id = ? AND item_name = ?", (quantita, str(utente.id), item))
    cursor.execute("DELETE FROM inventory WHERE quantity <= 0") # Pulisce le righe con 0 oggetti
    conn.commit()
    await interaction.followup.send(f"✅ Rimossi {quantita}x **{item}** a {utente.mention}.")

@bot.tree.command(name="wipe_utente", description="ADMIN - AZZERA SOLDI E ITEM DI UN UTENTE (IRREVERSIBILE)")
async def wipe_utente(interaction: discord.Interaction, utente: discord.Member):
    await interaction.response.defer(ephemeral=True)
    if not interaction.user.guild_permissions.administrator:
        return await interaction.followup.send("❌ Solo un Amministratore può eseguire un wipe totale.")

    # Reset Soldi (Wallet e Banca)
    cursor.execute("UPDATE users SET wallet = 0, bank = 0 WHERE user_id = ?", (str(utente.id),))
    # Reset Inventario
    cursor.execute("DELETE FROM inventory WHERE user_id = ?", (str(utente.id),))
    
    conn.commit()
    
    embed = discord.Embed(
        title="🧹 Wipe Effettuato", 
        description=f"Tutti i beni di {utente.mention} sono stati azzerati con successo.",
        color=discord.Color.dark_red()
    )
    embed.add_field(name="Soldi", value="Portafoglio e Banca: 0$")
    embed.add_field(name="Inventario", value="Svuotato completamente")
    
    await interaction.followup.send(embed=embed)


# ================= WEB SERVER & START =================
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"✅ {bot.user} Online!")

app = Flask("")
@app.route("/")
def home(): return "Online"
def run(): app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
threading.Thread(target=run).start()
bot.run(TOKEN)
