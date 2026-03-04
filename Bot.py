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
import datetime 
import string
import time

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
    if not conn: 
        return
    cur = conn.cursor()

    # 1. Creazione Tabelle Base (Usa sempre IF NOT EXISTS)
    cur.execute("CREATE TABLE IF NOT EXISTS users (user_id TEXT PRIMARY KEY, wallet INTEGER DEFAULT 3500, bank INTEGER DEFAULT 0)")
    cur.execute("CREATE TABLE IF NOT EXISTS items (name TEXT PRIMARY KEY, description TEXT, price INTEGER, role_required TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS inventory (user_id TEXT, item_name TEXT, quantity INTEGER, PRIMARY KEY (user_id, item_name))")
    cur.execute("CREATE TABLE IF NOT EXISTS depositi (role_id TEXT PRIMARY KEY, money INTEGER DEFAULT 0)")
    cur.execute("CREATE TABLE IF NOT EXISTS depositi_items (role_id TEXT, item_name TEXT, quantity INTEGER, PRIMARY KEY (role_id, item_name))")
    cur.execute("CREATE TABLE IF NOT EXISTS turni (user_id TEXT PRIMARY KEY, inizio TIMESTAMP)")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS fatture (
            id_fattura TEXT PRIMARY KEY,
            id_cliente TEXT,
            id_azienda TEXT,
            descrizione TEXT,
            prezzo INTEGER,
            data TEXT,
            stato TEXT DEFAULT 'Pendente'
        )
    """)

    # 2. Aggiornamento tabelle esistenti (ALTER TABLE)
    # Usiamo blocchi try/except separati per ogni colonna così se una esiste già non blocca l'altra
    
    # Aggiunta ore_lavorate a users
    try:
        cur.execute("ALTER TABLE users ADD COLUMN ore_lavorate REAL DEFAULT 0")
        conn.commit()
    except Exception:
        conn.rollback() # Ignora se la colonna esiste già

    # Aggiunta ruolo a turni
    try:
        cur.execute("ALTER TABLE turni ADD COLUMN ruolo TEXT")
        conn.commit()
    except Exception:
        conn.rollback() # Ignora se la colonna esiste già

def inizializza_db_fatture():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Crea la tabella se non esiste con i nomi delle colonne corretti
        cur.execute("""
            CREATE TABLE IF NOT EXISTS fatture (
                id_fattura TEXT PRIMARY KEY,
                id_cliente TEXT NOT NULL,
                id_azienda TEXT NOT NULL,
                descrizione TEXT,
                prezzo BIGINT,
                data TEXT,
                stato TEXT DEFAULT 'Pendente'
            );
        """)
        
        # Questo comando aggiunge la colonna 'stato' se la tabella esiste già ma è vecchia
        cur.execute("""
            DO $$ 
            BEGIN 
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                               WHERE table_name='fatture' AND column_name='stato') THEN 
                    ALTER TABLE fatture ADD COLUMN stato TEXT DEFAULT 'Pendente';
                END IF;
            END $$;
        """)
        
        conn.commit()
        cur.close()
        conn.close()
        print("✅ Database Fatture sincronizzato con successo!")
    except Exception as e:
        print(f"❌ Errore inizializzazione tabella: {e}")

# RICORDA: Nel tuo evento @bot.event async def on_ready():
# aggiungi una riga con: inizializza_db_fatture()


    # Chiudiamo tutto correttamente
    cur.close()
    conn.close()
    print("✅ Database inizializzato correttamente!")

# Chiama la funzione
init_db()

# ================= HELPER FUNCTIONS =================

def get_user_data(user_id):
    conn = get_db_connection()
    if not conn: return {"wallet": 0, "bank": 0}
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM users WHERE user_id = %s", (str(user_id),))
    user = cur.fetchone()
    if not user:
        cur.execute("INSERT INTO users (user_id, wallet, bank) VALUES (%s, 3500, 0) RETURNING *", (str(user_id),))
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

    # --- COMANDO INIZIO TURNO (Ruolo Libero) ---
@bot.tree.command(name="inizio_turno", description="Inizia il turno specificando il tuo ruolo")
@app_commands.describe(ruolo="Scrivi il tuo ruolo (es. Polizia, Medico, Staff...)")
async def inizio_turno(interaction: discord.Interaction, ruolo: str):
    user_id = str(interaction.user.id)
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Controllo se l'utente è già in turno
    cur.execute("SELECT ruolo FROM turni WHERE user_id = %s", (user_id,))
    if cur.fetchone():
        conn.close()
        return await interaction.response.send_message("⚠️ Sei già in servizio! Usa `/fine_turno` prima di iniziarne uno nuovo.", ephemeral=True)
    
    ora_inizio = datetime.datetime.now()
    
    # Inserimento nel database con il ruolo scritto dall'utente
    cur.execute("INSERT INTO turni (user_id, inizio, ruolo) VALUES (%s, %s, %s)", 
                (user_id, ora_inizio, ruolo))
    conn.commit()
    cur.close(); conn.close()
    
    embed = discord.Embed(title="💼 Servizio Iniziato", color=discord.Color.green())
    embed.add_field(name="Cittadino", value=interaction.user.mention, inline=True)
    embed.add_field(name="Ruolo", value=f"**{ruolo}**", inline=True)
    embed.add_field(name="Orario", value=ora_inizio.strftime("%H:%M:%S"), inline=False)
    embed.set_footer(text="Buon lavoro in città!")
    
    await interaction.response.send_message(embed=embed)

# --- COMANDO FINE TURNO ---
@bot.tree.command(name="fine_turno", description="Termina il turno e calcola le ore lavorate")
async def fine_turno(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    # Recupero dati del turno attivo
    cur.execute("SELECT inizio, ruolo FROM turni WHERE user_id = %s", (user_id,))
    row = cur.fetchone()
    
    if not row:
        conn.close()
        return await interaction.response.send_message("❌ Non risulti essere in servizio al momento!", ephemeral=True)
    
    ora_fine = datetime.datetime.now()
    ora_inizio = row['inizio']
    ruolo_svolto = row['ruolo']
    
    # Calcolo durata
    durata = ora_fine - ora_inizio
    secondi_totali = durata.total_seconds()
    ore_decimali = secondi_totali / 3600
    
    # Formattazione HH:MM:SS
    ore, resto = divmod(int(secondi_totali), 3600)
    minuti, secondi = divmod(resto, 60)
    tempo_trascorso = f"{ore}h {minuti}m {secondi}s"

    # Aggiornamento database (rimozione turno e aggiunta ore totali)
    cur.execute("DELETE FROM turni WHERE user_id = %s", (user_id,))
    cur.execute("UPDATE users SET ore_lavorate = ore_lavorate + %s WHERE user_id = %s", (ore_decimali, user_id))
    
    conn.commit()
    cur.close(); conn.close()
    
    embed = discord.Embed(title="🏁 Fine Servizio", color=discord.Color.red())
    embed.add_field(name="Ruolo Svolto", value=f"**{ruolo_svolto}**", inline=True)
    embed.add_field(name="Tempo in Servizio", value=f"⏳ {tempo_trascorso}", inline=True)
    embed.add_field(name="Conto Ore Aggiornato", value=f"📈 +{ore_decimali:.2f} ore", inline=False)
    embed.set_footer(text=f"Grazie per il tuo lavoro, {interaction.user.display_name}!")
    
    await interaction.response.send_message(embed=embed)
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
class PagaFatturaView(discord.ui.View):
    def __init__(self, user_id, fatture):
        super().__init__(timeout=180)
        self.user_id = user_id
        
        # Creiamo le opzioni del menù
        options = []
        for f in fatture:
            options.append(discord.SelectOption(
                label=f"Fattura {f['id_fattura']}",
                description=f"Importo: {f['prezzo']}$ | Emessa da: {f['id_azienda']}",
                value=f['id_fattura']
            ))
            
        self.select = discord.ui.Select(placeholder="Seleziona la fattura da pagare...", options=options)
        self.select.callback = self.select_callback
        self.add_item(self.select)

    async def select_callback(self, interaction: discord.Interaction):
        # Fondamentale: defer per evitare l'errore 404 Unknown Interaction
        await interaction.response.defer(ephemeral=True)
        id_f = self.select.values[0]

        try:
            conn = get_db_connection()
            cur = conn.cursor()
            
            # Aggiorniamo lo stato della fattura specifica
            cur.execute("UPDATE fatture SET stato = %s WHERE id_fattura = %s", ('Pagata', id_f))
            
            conn.commit()
            cur.close()
            conn.close()

            # Disabilitiamo il menù per sicurezza
            self.select.disabled = True
            await interaction.edit_original_response(content=f"✅ Hai pagato correttamente la fattura `{id_f}`!", view=self)

        except Exception as e:
            print(f"ERRORE SQL PAGAMENTO: {e}")
            await interaction.followup.send("❌ Errore durante l'aggiornamento della fattura su Supabase.", ephemeral=True)
@bot.tree.command(name="pagafattura", description="Visualizza e paga le tue fatture pendenti")
async def pagafattura(interaction: discord.Interaction):
    # Usiamo ephemeral=True così solo l'utente vede le sue fatture
    await interaction.response.defer(ephemeral=True)
    
    try:
        conn = get_db_connection()
        # Usiamo RealDictCursor per leggere i dati come dizionari (f['prezzo'])
        from psycopg2.extras import RealDictCursor
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Cerchiamo le fatture pendenti per l'utente che ha lanciato il comando
        cur.execute("SELECT * FROM fatture WHERE id_cliente = %s AND stato = %s", (str(interaction.user.id), 'Pendente'))
        mie_fatture = cur.fetchall()
        
        cur.close()
        conn.close()

        if not mie_fatture:
            return await interaction.followup.send("✅ Ottime notizie! Non hai fatture da pagare.", ephemeral=True)

        # Mostriamo il menù a tendina
        view = PagaFatturaView(interaction.user.id, mie_fatture)
        await interaction.followup.send("Seleziona la fattura che vuoi saldare:", view=view, ephemeral=True)
    
    except Exception as e:
        print(f"ERRORE SQL LETTURA FATTURE: {e}")
        await interaction.followup.send("❌ Errore nel recupero dei dati dal database.", ephemeral=True)
@bot.tree.command(name="fattura", description="Emetti una fattura")
async def fattura(interaction: discord.Interaction, cliente: discord.Member, azienda: discord.Role, descrizione: str, prezzo: int):
    # Diciamo a discord di aspettare
    await interaction.response.defer()
    
    id_f = ''.join(random.choices(string.ascii_letters + string.digits, k=10))
    data_attuale = datetime.datetime.now().strftime("%d/%m/%Y")
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Inserimento dati - i nomi devono essere MINUSCOLI come nel SQL sopra
        cur.execute("""
            INSERT INTO fatture (id_fattura, id_cliente, id_azienda, descrizione, prezzo, data, stato) 
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (str(id_f), str(cliente.id), str(azienda.name), str(descrizione), int(prezzo), data_attuale, 'Pendente'))
        
        conn.commit()
        cur.close()
        conn.close()

        # Se tutto va bene, inviamo la conferma
        await interaction.followup.send(f"✅ Fattura emessa correttamente!\n**ID:** `{id_f}`\n**Cliente:** {cliente.mention}\n**Importo:** {prezzo}$")

    except Exception as e:
        # Questo stamperà l'errore preciso nei log di Render (es: colonna mancante)
        print(f"ERRORE SQL DETTAGLIATO: {e}")
        await interaction.followup.send(f"❌ Errore nel salvataggio su Supabase. Controlla i log di Render.", ephemeral=True)



ID_RUOLO_CONCESSIONARIO = 1414902990275612753

@bot.tree.command(name="registra_veicolo", description="Registra la vendita e consegna le chiavi con targa")
@app_commands.checks.has_any_role(ID_RUOLO_CONCESSIONARIO)
@app_commands.describe(
    acquirente="Il cittadino che compra l'auto",
    marca_modello="Es: Ferrari 488",
    targa="Es: AB123CD",
    concessionaria="Tagga il ruolo della concessionaria"
)
async def registra_veicolo(
    interaction: discord.Interaction, 
    acquirente: discord.Member, 
    marca_modello: str, 
    targa: str, 
    concessionaria: discord.Role
):
    # Rimuove il limite dei 3 secondi
    await interaction.response.defer()

    # Dati automatici
    data_ora = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
    operatore = interaction.user.display_name
    targa_maiuscola = targa.upper()
    
    # Nome dell'item che apparirà nell'inventario
    nome_item_chiavi = f"<:emoji_2:1464729413651534029> | Chiavi {marca_modello} [{targa_maiuscola}]"

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # 1. Aggiungiamo le chiavi con targa nell'inventario dell'acquirente
        cur.execute("""
            INSERT INTO inventory (user_id, item_name, quantity) 
            VALUES (%s, %s, 1) 
            ON CONFLICT (user_id, item_name) 
            DO UPDATE SET quantity = inventory.quantity + 1
        """, (str(acquirente.id), nome_item_chiavi))
        
        conn.commit()
        cur.close()
        conn.close()

        # 2. Creazione dell'Embed Modulo
        embed = discord.Embed(
            title="📝 CONTRATTO DI VENDITA VEICOLO",
            color=discord.Color.green(),
            timestamp=datetime.datetime.now()
        )
        
        embed.add_field(name="🏛️ CONCESSIONARIA", value=f"**Nome:** {concessionaria.mention}\n**Operatore:** {operatore}", inline=False)
        embed.add_field(name="👤 ACQUIRENTE", value=f"**Cittadino:** {acquirente.mention}\n**ID:** {acquirente.id}", inline=False)
        embed.add_field(name="🚘 VEICOLO", value=f"**Modello:** {marca_modello}\n**Targa:** `{targa_maiuscola}`", inline=False)
        
        embed.set_footer(text=f"Registrato il {data_ora}")
        
        # Risposta finale
        await interaction.followup.send(
            content=f"✅ Vendita completata! Chiavi consegnate a {acquirente.mention}.",
            embed=embed
        )

    except Exception as e:
        print(f"Errore registrazione veicolo: {e}")
        await interaction.followup.send("❌ Errore durante l'aggiornamento dell'inventario.", ephemeral=True)



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
class LeaderboardPagination(discord.ui.View):
    def __init__(self, data, per_page=10):
        super().__init__(timeout=60)
        self.data = data
        self.per_page = per_page
        self.current_page = 0
        self.total_pages = (len(data) - 1) // per_page + 1

    def create_embed(self, bot):
        start = self.current_page * self.per_page
        end = start + self.per_page
        page_data = self.data[start:end]

        embed = discord.Embed(
            title="🏆 Classifica Ricchezza Globale",
            color=discord.Color.gold()
        )
        
        description = ""
        for i, row in enumerate(page_data, start=start + 1):
            user_id = int(row['user_id'])
            user = bot.get_user(user_id)
            user_name = user.display_name if user else f"Cittadino ({user_id})"
            
            if i == 1: medal = "🥇"
            elif i == 2: medal = "🥈"
            elif i == 3: medal = "🥉"
            else: medal = f"**{i}.**"

            description += f"{medal} **{user_name}**: {row['totale']:,}$\n"
            description += f"└─ *Wallet: {row['wallet']:,}$ | Banca: {row['bank']:,}$*\n\n"

        embed.description = description
        embed.set_footer(text=f"Pagina {self.current_page + 1} di {self.total_pages} • Totale utenti: {len(self.data)}")
        return embed

    @discord.ui.button(label="⬅️ Indietro", style=discord.ButtonStyle.gray)
    async def previous_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
            await interaction.response.edit_message(embed=self.create_embed(interaction.client), view=self)
        else:
            await interaction.response.send_message("Sei già sulla prima pagina!", ephemeral=True)

    @discord.ui.button(label="Avanti ➡️", style=discord.ButtonStyle.gray)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            await interaction.response.edit_message(embed=self.create_embed(interaction.client), view=self)
        else:
            await interaction.response.send_message("Sei già sull'ultima pagina!", ephemeral=True)

@bot.tree.command(name="leaderboard", description="Mostra la classifica completa sfogliabile")
async def leaderboard(interaction: discord.Interaction):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    # Prendiamo tutti i dati ordinati per ricchezza totale
    cur.execute("SELECT user_id, wallet, bank, (wallet + bank) AS totale FROM users ORDER BY totale DESC")
    all_users = cur.fetchall()
    cur.close(); conn.close()

    if not all_users:
        return await interaction.response.send_message("📭 Database vuoto.")

    view = LeaderboardPagination(all_users)
    # Passiamo bot (client) per recuperare i nomi degli utenti
    embed = view.create_embed(interaction.client)
    
    await interaction.response.send_message(embed=embed, view=view)
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

# --- CLASSE VIEW PER I BOTTONI ---

# --- CLASSE VIEW PER I BOTTONI (Corretta e Reattiva) ---
class BlackjackView(discord.ui.View):
    def __init__(self, interaction, somma, mano_p, mano_b):
        super().__init__(timeout=60) # Il gioco scade dopo 60 secondi di inattività
        self.interaction = interaction
        self.somma = somma
        self.mano_p = mano_p
        self.mano_b = mano_b

    def get_tot(self, mano):
        tot = sum(mano)
        as_count = mano.count(11)
        while tot > 21 and as_count > 0:
            tot -= 10
            as_count -= 1
        return tot

    @discord.ui.button(label="Carta 🃏", style=discord.ButtonStyle.green)
    async def carta(self, inter: discord.Interaction, button: discord.ui.Button):
        # Controllo che solo chi ha iniziato la partita possa giocare
        if inter.user.id != self.interaction.user.id:
            return await inter.response.send_message("❌ Questa non è la tua partita!", ephemeral=True)
        
        self.mano_p.append(random.randint(2, 11))
        
        if self.get_tot(self.mano_p) > 21:
            await self.concludi(inter, "sballato")
        else:
            await self.update_msg(inter)

    @discord.ui.button(label="Stai ✋", style=discord.ButtonStyle.red)
    async def stai(self, inter: discord.Interaction, button: discord.ui.Button):
        if inter.user.id != self.interaction.user.id:
            return await inter.response.send_message("❌ Questa non è la tua partita!", ephemeral=True)
        
        # Logica del Banco
        while self.get_tot(self.mano_b) < 17:
            self.mano_b.append(random.randint(2, 11))
        
        tot_p = self.get_tot(self.mano_p)
        tot_b = self.get_tot(self.mano_b)
        
        if tot_b > 21 or tot_p > tot_b:
            esito = "vinto"
        elif tot_p < tot_b:
            esito = "perso"
        else:
            esito = "pareggio"
            
        await self.concludi(inter, esito)

    async def update_msg(self, inter):
        # Usiamo edit_message per aggiornare l'interfaccia senza inviare nuovi messaggi
        emb = discord.Embed(title="🃏 Blackjack - In Corso", color=discord.Color.gold())
        emb.add_field(name="La tua mano 👤", value=f"{self.mano_p}\n**Totale: {self.get_tot(self.mano_p)}**", inline=True)
        emb.add_field(name="Banco 🏛️", value=f"[{self.mano_b[0]}, ?]\n**Totale: ?**", inline=True)
        emb.set_footer(text=f"Puntata: {self.somma}$")
        await inter.response.edit_message(embed=emb, view=self)

    async def concludi(self, inter, esito):
        self.stop() # Disattiva i bottoni immediatamente
        tot_p = self.get_tot(self.mano_p)
        tot_b = self.get_tot(self.mano_b)
        
        # Connessione al database per pagare/sottrarre
        conn = get_db_connection()
        cur = conn.cursor()
        
        try:
            if esito == "vinto":
                # Paga il premio (raddoppio)
                cur.execute("UPDATE users SET wallet = wallet + %s WHERE user_id = %s", (self.somma, str(self.interaction.user.id)))
                txt = f"🏆 **Hai vinto!** Ti sono stati accreditati **{self.somma}$**."
                colore = discord.Color.green()
            elif esito == "pareggio":
                txt = "🤝 **Pareggio!** Non hai perso nulla."
                colore = discord.Color.light_gray()
            else:
                # Sottrae la scommessa
                cur.execute("UPDATE users SET wallet = wallet - %s WHERE user_id = %s", (self.somma, str(self.interaction.user.id)))
                txt = f"💀 **Hai perso {self.somma}$**. Il banco vince."
                colore = discord.Color.red()
            
            conn.commit()
        except Exception as e:
            print(f"Errore DB Blackjack: {e}")
        finally:
            cur.close()
            conn.close()

        emb = discord.Embed(title="🃏 Blackjack - Risultato Finale", color=colore)
        emb.add_field(name="Tu 👤", value=f"{self.mano_p} (Tot: {tot_p})", inline=True)
        emb.add_field(name="Banco 🏛️", value=f"{self.mano_b} (Tot: {tot_b})", inline=True)
        emb.add_field(name="Esito", value=txt, inline=False)
        
        await inter.response.edit_message(embed=emb, view=None)

# --- COMANDO SLASH ---
@bot.tree.command(name="blackjack", description="Gioca a Blackjack contro il banco")
async def blackjack(interaction: discord.Interaction, somma: int):
    # Recupero dati per controllo fondi
    u = get_user_data(interaction.user.id)
    
    if somma <= 0:
        return await interaction.response.send_message("❌ Inserisci una somma valida!", ephemeral=True)
    if u['wallet'] < somma:
        return await interaction.response.send_message(f"❌ Non hai abbastanza contanti! Hai solo {u['wallet']}$.", ephemeral=True)

    # Carte iniziali
    mano_p = [random.randint(2, 11), random.randint(2, 11)]
    mano_b = [random.randint(2, 11)]
    
    view = BlackjackView(interaction, somma, mano_p, mano_b)
    
    emb = discord.Embed(title="🃏 Blackjack", color=discord.Color.gold())
    emb.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
    emb.add_field(name="La tua mano 👤", value=f"{mano_p}\n**Totale: {view.get_tot(mano_p)}**", inline=True)
    emb.add_field(name="Banco 🏛️", value=f"[{mano_b[0]}, ?]\n**Totale: ?**", inline=True)
    emb.set_footer(text=f"Puntata: {somma}$")

    await interaction.response.send_message(embed=emb, view=view)



@bot.tree.command(name="roulette", description="Punta i tuoi soldi alla roulette (Attesa 10s)")
@app_commands.choices(puntata=[
    app_commands.Choice(name="🔴 Rosso (x2)", value="rosso"),
    app_commands.Choice(name="⚫ Nero (x2)", value="nero"),
    app_commands.Choice(name="🟢 Numero Singolo (x36)", value="numero")
])
async def roulette(interaction: discord.Interaction, puntata: str, somma: int, numero_scelto: int = None):
    u = get_user_data(interaction.user.id)
    if somma <= 0:
        return await interaction.response.send_message("❌ Inserisci una cifra valida!", ephemeral=True)
    if u['wallet'] < somma:
        return await interaction.response.send_message(f"❌ Non hai abbastanza contanti! (Hai {u['wallet']}$)", ephemeral=True)

    if puntata == "numero" and (numero_scelto is None or numero_scelto < 0 or numero_scelto > 36):
        return await interaction.response.send_message("❌ Se punti su un numero, scegline uno tra 0 e 36!", ephemeral=True)

    await interaction.response.send_message(f"🎰 **{interaction.user.display_name}** ha puntato **{somma}$** su **{puntata.upper()}**...\n*La pallina sta girando...* 🎡")
    
    await asyncio.sleep(10) # Attesa per creare suspense
    
    risultato = random.randint(0, 36)
    rossi = [1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36]
    colore_uscito = "rosso" if risultato in rossi else "nero" if risultato != 0 else "verde"
    emoji = "🔴" if colore_uscito == "rosso" else "⚫" if colore_uscito == "nero" else "🟢"

    vinto = False
    moltiplicatore = 2
    if puntata == "rosso" and colore_uscito == "rosso": vinto = True
    elif puntata == "nero" and colore_uscito == "nero": vinto = True
    elif puntata == "numero" and numero_scelto == risultato: 
        vinto = True
        moltiplicatore = 36

    conn = get_db_connection()
    cur = conn.cursor()
    
    if vinto:
        # Guadagno Netto: se punti 100 e vinci x2, ricevi +100 (totale 200)
        vincita_netta = somma * (moltiplicatore - 1)
        cur.execute("UPDATE users SET wallet = wallet + %s WHERE user_id = %s", (vincita_netta, str(interaction.user.id)))
        testo = f"✅ RISULTATO: **{risultato} {emoji}**. Hai vinto! Ti sono stati accreditati **{somma * moltiplicatore}$** 🎉"
    else:
        # Perdita: ti vengono sottratti i soldi puntati
        cur.execute("UPDATE users SET wallet = wallet - %s WHERE user_id = %s", (somma, str(interaction.user.id)))
        testo = f"💀 RISULTATO: **{risultato} {emoji}**. Hai perso **{somma}$**. La casa vince! 🏛️"
    
    conn.commit()
    cur.close(); conn.close()
    await interaction.channel.send(f"🎰 **{interaction.user.mention}**\n{testo}")


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
