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
RUOLO_STAFF_ID = 1465432780551753811

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
    
# --- 1. COMANDO CREA ---
@bot.tree.command(name="crea", description="Invia l'embed base con immagine")
@discord.app_commands.checks.has_permissions(administrator=True)
async def crea(interaction: discord.Interaction, testo: str, url_immagine: str):
    embed = discord.Embed(description=testo, color=0x2b2d31)
    embed.set_image(url=url_immagine)
    await interaction.response.send_message(embed=embed)
    
    
    
    
    
# --- 2. COMANDO AGGIUNGI BOTTONE ---
@bot.tree.command(name="aggiungi", description="Aggiunge un bottone link a un messaggio esistente")
@discord.app_commands.checks.has_permissions(administrator=True)
async def aggiungi(interaction: discord.Interaction, id_messaggio: str, testo_bottone: str, link: str, emoji: str = None):
    try:
        messaggio = await interaction.channel.fetch_message(int(id_messaggio))
        view = discord.ui.View()

        if messaggio.components:
            for row in messaggio.components:
                for comp in row.children:
                    if isinstance(comp, discord.Button):
                        view.add_item(discord.ui.Button(label=comp.label, url=comp.url, emoji=comp.emoji, style=discord.ButtonStyle.link))

        view.add_item(discord.ui.Button(label=testo_bottone, url=link, emoji=emoji, style=discord.ButtonStyle.link))
        await messaggio.edit(view=view)
        await interaction.response.send_message(f"✅ Bottone '{testo_bottone}' aggiunto!", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ Errore: {e}", ephemeral=True)
# --- LOGICA STAFF: VIEW E MODAL PER APPROVAZIONE ---

class ModificaBottinoModal(discord.ui.Modal, title="Modifica Bottino Rapina"):
    nuovo_importo = discord.ui.TextInput(label="Nuovo Ammontare (€)", placeholder="Inserisci la cifra...")
    
    def __init__(self, user_id, luogo):
        super().__init__()
        self.user_id = user_id
        self.luogo = luogo

    async def on_submit(self, interaction: discord.Interaction):
        try:
            valore = int(self.nuovo_importo.value)
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("UPDATE users SET wallet = wallet + %s WHERE user_id = %s", (valore, self.user_id))
            conn.commit()
            cur.close()
            conn.close()
            
            await interaction.response.edit_message(content=f"✍️ **BOTTINO MODIFICATO**: Accreditati **{valore}€** a <@{self.user_id}> per la rapina a **{self.luogo}**.", embed=None, view=None)
        except ValueError:
            await interaction.response.send_message("❌ Inserisci un numero valido!", ephemeral=True)

class RapinaStaffView(discord.ui.View):
    def __init__(self, user_id, ammontare, luogo):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.ammontare = ammontare
        self.luogo = luogo

    @discord.ui.button(label="Conferma", style=discord.ButtonStyle.success)
    async def conferma(self, interaction: discord.Interaction, button: discord.ui.Button):
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("UPDATE users SET wallet = wallet + %s WHERE user_id = %s", (self.ammontare, self.user_id))
        conn.commit()
        cur.close()
        conn.close()
        await interaction.response.edit_message(content=f"✅ **PAGAMENTO APPROVATO**: {self.ammontare}€ accreditati a <@{self.user_id}>.", embed=None, view=None)

    @discord.ui.button(label="Annulla", style=discord.ButtonStyle.danger)
    async def annulla(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content=f"❌ **RAPINA ANNULLATA**: Il colpo di <@{self.user_id}> è stato invalidato.", embed=None, view=None)

    @discord.ui.button(label="Modifica Importo", style=discord.ButtonStyle.secondary)
    async def modifica(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ModificaBottinoModal(self.user_id, self.luogo))

# --- COMANDO SETTAGGIO CANALE (SOLO ADMIN) ---

@bot.tree.command(name="set_canale_rapine", description="Imposta il canale per le approvazioni rapine (Solo Admin)")
@app_commands.checks.has_permissions(administrator=True)
async def set_canale_rapine(interaction: discord.Interaction, canale: discord.TextChannel):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO server_settings (setting_name, setting_value) 
            VALUES ('canale_rapine', %s) 
            ON CONFLICT (setting_name) DO UPDATE SET setting_value = EXCLUDED.setting_value
        """, (str(canale.id),))
        conn.commit()
        cur.close()
        conn.close()
        await interaction.response.send_message(f"✅ Canale approvazione rapine impostato su: {canale.mention}")
    except Exception as e:
        await interaction.response.send_message(f"❌ Errore: {e}", ephemeral=True)
# 1. DEFINISCI PRIMA LA FUNZIONE DI AUTOCOMPLETE
async def rapina_autocomplete(interaction: discord.Interaction, current: str):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT nome FROM rapine_config WHERE nome ILIKE %s LIMIT 25", (f'%{current}%',))
    choices = [app_commands.Choice(name=row[0].title(), value=row[0]) for row in cur.fetchall()]
    cur.close()
    conn.close()
    return choices


# --- COMANDO INIZIA RAPINA CON SISTEMA BBC ---
@bot.tree.command(name="inizia_rapina", description="Inizia lo scasso in un luogo configurato")
@app_commands.autocomplete(luogo=rapina_autocomplete)
async def inizia_rapina(interaction: discord.Interaction, luogo: str):
    await interaction.response.defer()
    
    conn = get_db_connection()
    from psycopg2.extras import RealDictCursor
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    # 1. Recupera Config Rapina
    cur.execute("SELECT * FROM rapine_config WHERE nome = %s", (luogo.lower(),))
    config = cur.fetchone()
    
    # 2. Recupera Canale Staff per le rapine
    cur.execute("SELECT setting_value FROM server_settings WHERE setting_name = 'canale_rapine'")
    res_canale = cur.fetchone()
    
    if not config:
        cur.close()
        conn.close()
        return await interaction.followup.send("❌ Luogo non configurato.")
    
    if not res_canale:
        cur.close()
        conn.close()
        return await interaction.followup.send("❌ Canale staff rapine non impostato. Usa `/set_canale_rapine`.")

    canale_staff_id = int(res_canale['setting_value'])
    tempo_rimanente = config['tempo_scasso']
    paga_casuale = random.randint(config['paga_min'], config['paga_max'])
    
    embed = discord.Embed(title="🚨 RAPINA IN CORSO", description=f"Sede: **{luogo.upper()}**", color=discord.Color.red())
    embed.add_field(name="Progresso", value=f"⏳ Scasso in corso: `{tempo_rimanente}s`")
    
    msg = await interaction.followup.send(embed=embed)

    # --- LOOP DEL TIMER ---
    while tempo_rimanente > 0:
        await asyncio.sleep(5)
        tempo_rimanente -= 5
        if tempo_rimanente < 0: tempo_rimanente = 0
        embed.set_field_at(0, name="Progresso", value=f"⏳ Scasso in corso: `{tempo_rimanente}s`")
        try:
            await msg.edit(embed=embed)
        except:
            cur.close()
            conn.close()
            return

    # --- FINE SCASSO (NESSUN ACCREDITO SOLDI QUI!) ---
    
    embed.title = "🛠️ SCASSINAMENTO COMPLETATO"
    embed.color = discord.Color.orange()
    embed.set_field_at(0, name="Stato", value="⌛ In attesa di approvazione staff...")
    await msg.edit(embed=embed)

    # Invio richiesta al Canale Staff
    canale_staff = interaction.guild.get_channel(canale_staff_id)
    if canale_staff:
        embed_staff = discord.Embed(title="🛡️ RICHIESTA BOTTINO RAPINA", color=discord.Color.gold())
        embed_staff.add_field(name="Cittadino", value=interaction.user.mention, inline=True)
        embed_staff.add_field(name="Luogo", value=luogo.upper(), inline=True)
        embed_staff.add_field(name="Importo Generato", value=f"**{paga_casuale}€**", inline=False)
        
        # Passiamo i dati alla View: sarà lei a pagare tramite il bottone
        view = RapinaStaffView(str(interaction.user.id), paga_casuale, luogo)
        await canale_staff.send(embed=embed_staff, view=view)
    else:
        # Se il bot non trova il canale, avvisa l'utente
        await interaction.followup.send("⚠️ Errore: Il canale staff non è raggiungibile. Contatta un Admin.")

    cur.close()
    conn.close()




# --- 3. COMANDO AGGIORNA CONTENUTO ---
@bot.tree.command(name="aggiorna", description="Modifica testo o immagine dell'embed")
@discord.app_commands.checks.has_permissions(administrator=True)
async def aggiorna(interaction: discord.Interaction, id_messaggio: str, nuovo_testo: str = None, nuova_img: str = None):
    try:
        messaggio = await interaction.channel.fetch_message(int(id_messaggio))
        if not messaggio.embeds:
            return await interaction.response.send_message("❌ Nessun embed trovato!", ephemeral=True)

        embed = messaggio.embeds[0]
        if nuovo_testo: embed.description = nuovo_testo
        if nuova_img: embed.set_image(url=nuova_img)
            
        await messaggio.edit(embed=embed)
        await interaction.response.send_message("✅ Contenuto aggiornato!", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ Errore: {e}", ephemeral=True)

# --- GESTORE ERRORI ---
@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
    if isinstance(error, discord.app_commands.MissingPermissions):
        await interaction.response.send_message("❌ Non hai i permessi di Amministratore!", ephemeral=True)

@bot.tree.command(name="lista_anonimi", description="Mostra la lista di tutti i nickname anonimi associati agli utenti")
async def lista_anonimi(interaction: discord.Interaction):
    # Controllo se l'utente è staff o admin per evitare che tutti vedano i nomi
    ID_RUOLO_STAFF = 1465432780551753811 # tuo ID ruolo staff
    is_staff = any(r.id == ID_RUOLO_STAFF for r in interaction.user.roles) or interaction.user.guild_permissions.administrator
    
    if not is_staff:
        return await interaction.response.send_message("❌ Non hai i permessi per vedere questa lista.", ephemeral=True)

    await interaction.response.defer(ephemeral=True)

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Recuperiamo tutti gli utenti registrati
        cur.execute("SELECT user_id, nickname FROM utenti_anonimi")
        rows = cur.fetchall()
        
        cur.close()
        conn.close()

        if not rows:
            return await interaction.followup.send("📭 Non ci sono utenti registrati nel database anonimo.", ephemeral=True)

        # Creiamo la stringa della tabella
        testo_lista = "## 📋 DATABASE IDENTITÀ ANONIME\n\n"
        for row in rows:
            user_mention = f"<@{row['user_id']}>"
            nickname = row['nickname']
            testo_lista += f"{user_mention} = **{nickname}**\n"

        # Creiamo un embed per renderlo più ordinato
        embed = discord.Embed(
            title="🕵️ Registro Alias Segreti",
            description=testo_lista,
            color=discord.Color.blue(),
            timestamp=datetime.datetime.now()
        )
        embed.set_footer(text="Accesso riservato allo Staff")

        await interaction.followup.send(embed=embed, ephemeral=True)

    except Exception as e:
        print(f"Errore lista_anonimi: {e}")
        await interaction.followup.send("❌ Errore nel recupero del database.", ephemeral=True)


@bot.tree.command(name="me", description="Esegui un'azione in gioco (Roleplay)")
@app_commands.describe(azione="Descrivi l'azione che stai compiendo")
async def me(interaction: discord.Interaction, azione: str):
    # Creazione dell'Embed con i parametri richiesti
    embed = discord.Embed(
        title="🎬 𝐀𝐳𝐢𝐨𝐧𝐞 🎦",
        description=f"{interaction.user.mention} : {azione}",
        color=discord.Color.from_rgb(170, 142, 214) # Un viola elegante per le azioni RP
    )
    
    # Invia il messaggio nel canale in cui è stato usato il comando
    await interaction.response.send_message(embed=embed)
# --- COMANDO SETUP WL (Solo Admin) ---
@bot.tree.command(name="setup_wl", description="[ADMIN] Configura il sistema WL")
@app_commands.describe(
    ruolo_passata="Ruolo per chi passa",
    ruolo_rifiutata="Ruolo per chi viene bocciato",
    ruolo_staff_display="Ruolo visualizzato nell'embed (es. @Responsabile)",
    ruolo_per_fare_esito="Il ruolo che lo staffer DEVE AVERE per usare il comando /esito-wl"
)
@app_commands.checks.has_permissions(administrator=True)
async def setup_wl(
    interaction: discord.Interaction, 
    ruolo_passata: discord.Role, 
    ruolo_rifiutata: discord.Role,
    ruolo_staff_display: discord.Role,
    ruolo_per_fare_esito: discord.Role
):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO wl_config (guild_id, ruolo_passata, ruolo_rifiutata, ruolo_staff, ruolo_abilitato_esito) 
        VALUES (%s, %s, %s, %s, %s) 
        ON CONFLICT (guild_id) DO UPDATE SET 
        ruolo_passata = EXCLUDED.ruolo_passata, 
        ruolo_rifiutata = EXCLUDED.ruolo_rifiutata,
        ruolo_staff = EXCLUDED.ruolo_staff,
        ruolo_abilitato_esito = EXCLUDED.ruolo_abilitato_esito
    """, (str(interaction.guild.id), str(ruolo_passata.id), str(ruolo_rifiutata.id), 
          str(ruolo_staff_display.id), str(ruolo_per_fare_esito.id)))
    conn.commit()
    cur.close(); conn.close()
    
    await interaction.response.send_message(f"✅ Configurazione WL salvata correttamente!", ephemeral=True)

# --- COMANDO ESITO WL ---
@bot.tree.command(name="esito-wl", description="Invia l'esito della Whitelist")
@app_commands.choices(esito=[
    app_commands.Choice(name="✅ Passata", value="accettato"),
    app_commands.Choice(name="❌ Rifiutata", value="rifiutato")
])
async def esito_wl(interaction: discord.Interaction, utente: discord.Member, esito: app_commands.Choice[str], errori: int):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM wl_config WHERE guild_id = %s", (str(interaction.guild.id),))
    config = cur.fetchone()
    cur.close(); conn.close()

    if not config:
        return await interaction.response.send_message("❌ Sistema non configurato.", ephemeral=True)

    # --- CONTROLLO RUOLO ABILITATO ---
    id_ruolo_esito = config.get('ruolo_abilitato_esito')
    if id_ruolo_esito:
        ruolo_necessario = interaction.guild.get_role(int(id_ruolo_esito))
        if ruolo_necessario not in interaction.user.roles:
            return await interaction.response.send_message(f"❌ Solo chi ha il ruolo {ruolo_necessario.mention} può dare esiti WL!", ephemeral=True)

    await interaction.response.defer()

    # Logica Estetica
    color = discord.Color.green() if esito.value == "accettato" else discord.Color.red()
    emoji_status = "🟩" if esito.value == "accettato" else "🟥"
    
    # Assegnazione Ruolo all'utente
    role_to_add_id = config['ruolo_passata'] if esito.value == "accettato" else config['ruolo_rifiutata']
    role_to_add = interaction.guild.get_role(int(role_to_add_id))
    if role_to_add:
        try: await utente.add_roles(role_to_add)
        except: pass

    # Recupero Ruolo Staff da mostrare nell'embed
    display_staff_role = f"<@&{config['ruolo_staff']}>" if config['ruolo_staff'] else "@Staffer"

    # Creazione Embed
    embed = discord.Embed(title=f"{emoji_status} | Approval notices", color=color)
    embed.set_thumbnail(url=interaction.guild.icon.url if interaction.guild.icon else None)
    embed.add_field(name="Evrenians ❯❯", value=utente.mention, inline=False)
    embed.add_field(name="Esito ❯❯", value=f"**{esito.value.upper()}**", inline=True)
    embed.add_field(name="Errori ❯❯", value=f"**{errori}**", inline=True)
    embed.add_field(name="━━━━━━━━━━━━━━━━━━━━", value=" ", inline=False)
    embed.add_field(name=f"Da {display_staff_role} :", value=interaction.user.mention, inline=False)
    embed.set_footer(text=f"Evren City RP • {discord.utils.utcnow().strftime('%d/%m/%Y')}")

    await interaction.followup.send(content=utente.mention, embed=embed)

@bot.tree.command(name="clear", description="Elimina un numero specifico di messaggi da questo canale")
@app_commands.describe(quantita="Numero di messaggi da eliminare (max 100)")
async def clear(interaction: discord.Interaction, quantita: int):
    # ID del ruolo autorizzato
    ID_RUOLO_AUTORIZZATO = 1465432780551753811
    
    # Controllo se l'utente ha il ruolo richiesto
    role = interaction.guild.get_role(RUOLO_STAFF_ID)
    if role not in interaction.user.roles:
        return await interaction.response.send_message(
            "❌ Non hai i permessi necessari (Staff) per usare questo comando.", 
            ephemeral=True
        )

    # Controllo che la quantità sia valida
    if quantita < 1 or quantita > 100:
        return await interaction.response.send_message(
            "⚠️ Puoi eliminare da 1 a 100 messaggi alla volta.", 
            ephemeral=True
        )

    await interaction.response.defer(ephemeral=True)

    try:
        # Elimina i messaggi
        deleted = await interaction.channel.purge(limit=quantita)
        
        # Crea un embed di conferma
        embed = discord.Embed(
            description=f"✅ Pulizia completata: eliminati **{len(deleted)}** messaggi.",
            color=discord.Color.green()
        )
        
        # Invia la conferma (visibile solo a chi ha usato il comando)
        await interaction.followup.send(embed=embed)
        
    except discord.Forbidden:
        await interaction.followup.send("❌ Il bot non ha i permessi di 'Gestire i messaggi' in questo canale.", ephemeral=True)
    except Exception as e:
        print(f"Errore comando clear: {e}")
        await interaction.followup.send("❌ Si è verificato un errore durante la pulizia.", ephemeral=True)
# Sostituisci con l'ID reale del tuo ruolo Staff
 
import asyncio
import random

@bot.tree.command(name="scassina", description="Tenta di scassinare una serratura (10 secondi)")
async def scassina(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    item_nome = "Grimaldello"
    
    # 1. Controllo immediato dell'oggetto (senza defer per rispondere subito)
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT quantity FROM inventory WHERE user_id = %s AND item_name = %s", (user_id, item_nome))
    res = cur.fetchone()
    
    if not res or res[0] <= 0:
        cur.close(); conn.close()
        return await interaction.response.send_message(f"❌ Non hai un **{item_nome}**!", ephemeral=True)

    # 2. Risposta iniziale e inizio countdown
    await interaction.response.send_message(f"🛠️ {interaction.user.mention} ha iniziato a manomettere la serratura...")
    msg = await interaction.original_response()

    # --- FASE DI ATTESA (10 SECONDI) ---
    tempo_attesa = 10
    while tempo_attesa > 0:
        await asyncio.sleep(2) # Aggiorniamo ogni 2 secondi per non sovraccaricare Discord
        tempo_attesa -= 2
        if tempo_attesa > 0:
            await interaction.edit_original_response(content=f"🛠️ {interaction.user.mention} sta scassinando... `{tempo_attesa}s` rimanenti.")

    # 3. Fine attesa: Consumo oggetto e calcolo successo
    cur.execute("UPDATE inventory SET quantity = quantity - 1 WHERE user_id = %s AND item_name = %s", (user_id, item_nome))
    cur.execute("DELETE FROM inventory WHERE quantity <= 0")
    conn.commit()
    
    successo = random.random() < 0.60
    
    # 4. Embed finale
    embed = discord.Embed(
        title="Scassinamento eseguito",
        description=f"{interaction.user.mention} ha terminato il tentativo.",
        color=0xE91E63 if not successo else 0x2ECC71 # Rosa se fallisce, Verde se riesce
    )
    embed.set_thumbnail(url="https://i.imgur.com/8Nn3vC9.png")

    if successo:
        embed.add_field(name="Risultato:", value="✅ **SUCCESSO!** La serratura è stata forzata.", inline=False)
    else:
        embed.add_field(name="Risultato:", value="• **FALLITO!** Il grimaldello si è spezzato.\n• Hai consumato 1x Grimaldello", inline=False)

    embed.set_footer(text="Evren City RP - Sistema Sicurezza")
    
    # Modifica il messaggio finale trasformandolo nell'Embed del risultato
    await interaction.edit_original_response(content=None, embed=embed)
    
    cur.close()
    conn.close()
import discord
from discord import app_commands
from discord.ext import commands

# --- MODALE PER L'INSERIMENTO DEL BACKGROUND ---
class BackgroundModal(discord.ui.Modal, title="Compilazione Background PG"):
    # Abbiamo 5 campi disponibili (il massimo su Discord)
    campo1 = discord.ui.TextInput(label="Nome, Età e ID PSN", placeholder="Es: Mario Rossi, 25, PSN_ID", min_length=10)
    campo2 = discord.ui.TextInput(label="Esperienze RP", style=discord.TextStyle.long, placeholder="Descrivi i server dove hai giocato...")
    campo3 = discord.ui.TextInput(label="Storia del Personaggio", style=discord.TextStyle.long, placeholder="Racconta il passato del tuo PG...")
    campo4 = discord.ui.TextInput(label="Paure e Obiettivi PG", style=discord.TextStyle.long, placeholder="Cosa teme e cosa vuole fare in città?")
    campo5 = discord.ui.TextInput(label="Presa visione Regolamento", placeholder="Scrivi 'Sì' se hai letto e accettato il regolamento")

    def __init__(self, staff_channel):
        super().__init__()
        self.staff_channel = staff_channel

    async def on_submit(self, interaction: discord.Interaction):
        # Messaggio di conferma privato all'utente
        await interaction.response.send_message("✅ Background inviato! Riceverai l'esito qui nei tuoi messaggi privati (DM).", ephemeral=True)
        
        # Embed per il canale STAFF con le risposte separate
        embed = discord.Embed(title="📝 Nuovo Background Ricevuto", color=discord.Color.blue())
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        
        embed.add_field(name="👤 Info Generali", value=self.campo1.value, inline=False)
        embed.add_field(name="🎮 Esperienze RP", value=self.campo2.value, inline=False)
        embed.add_field(name="📖 Storia PG", value=self.campo3.value[:1024], inline=False)
        embed.add_field(name="🔍 Paure e Obiettivi", value=self.campo4.value[:1024], inline=False)
        embed.add_field(name="📜 Regolamento", value=self.campo5.value, inline=False)
        
        embed.set_footer(text=f"Inviato da: {interaction.user.name} ({interaction.user.id})")

        # Passiamo l'ID utente alla View per poterlo contattare dopo
        view = BackgroundStaffView(user_id=interaction.user.id, info_generali=self.campo1.value)
        await self.staff_channel.send(embed=embed, view=view)

# --- VIEW PER LO STAFF CON INVIO DM ---
class BackgroundStaffView(discord.ui.View):
    def __init__(self, user_id, info_generali):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.info_generali = info_generali

    @discord.ui.button(label="ACCETTA", style=discord.ButtonStyle.success, emoji="✅")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        member = guild.get_member(self.user_id)
        
        if not member:
            return await interaction.response.send_message("❌ Utente non trovato nel server.", ephemeral=True)

        # Cerchiamo di estrarre l'ID PSN per il nickname (assumendo sia l'ultima parte del campo 1)
        # In alternativa, lo staff può cambiarlo a mano se il formato non è chiaro
        
        embed_dm = discord.Embed(
            title="✅ Background Approvato!",
            description="Il tuo background per **Evren City** è stato visionato e **ACCETTATO**.\n\nPuoi ora procedere nel server. Benvenuto!",
            color=discord.Color.green()
        )

        try:
            await member.send(embed=embed_dm)
            status_msg = f"✅ Esito inviato in DM a {member.mention}"
        except discord.Forbidden:
            status_msg = f"⚠️ Background accettato, ma non ho potuto inviare il DM (Messaggi chiusi)."

        await interaction.response.edit_message(content=f"{status_msg} | Gestito da {interaction.user.mention}", view=None)

    @discord.ui.button(label="RIFIUTA", style=discord.ButtonStyle.danger, emoji="❌")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        member = guild.get_member(self.user_id)
        
        if not member:
            return await interaction.response.send_message("❌ Utente non trovato nel server.", ephemeral=True)

        embed_dm = discord.Embed(
            title="❌ Background Rifiutato",
            description="Purtroppo il tuo background non è stato approvato.\n\nTi consigliamo di rileggere il regolamento e approfondire la storia del tuo personaggio prima di riprovare.",
            color=discord.Color.red()
        )

        try:
            await member.send(embed=embed_dm)
            status_msg = f"❌ Esito di rifiuto inviato in DM a {member.mention}"
        except discord.Forbidden:
            status_msg = f"⚠️ Background rifiutato, ma non ho potuto inviare il DM (Messaggi chiusi)."

        await interaction.response.edit_message(content=f"{status_msg} | Gestito da {interaction.user.mention}", view=None)

# --- COMANDO STAFF: AGGIUNGI DROGA ---
@bot.tree.command(name="crea_droga", description="Configura una nuova droga (Solo Staff)")
@app_commands.describe(nome="Nome della droga", quantita="Quanti pezzi si raccolgono al minuto")
async def crea_droga(interaction: discord.Interaction, nome: str, quantita: int):
    # Controllo Ruolo Staff
    if not any(role.id == RUOLO_STAFF_ID for role in interaction.user.roles):
        return await interaction.response.send_message("❌ Non hai i permessi per usare questo comando.", ephemeral=True)

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO droghe_config (nome, quantita_al_minuto)
            VALUES (%s, %s)
            ON CONFLICT (nome) DO UPDATE SET quantita_al_minuto = EXCLUDED.quantita_al_minuto
        """, (nome.lower(), quantita))
        conn.commit()
        cur.close()
        conn.close()
        
        await interaction.response.send_message(f"✅ Droga **{nome}** configurata: {quantita} pezzi/minuto.")
    except Exception as e:
        await interaction.response.send_message(f"❌ Errore DB: {e}", ephemeral=True)

# --- AUTOCOMPLETE PER IL COMANDO INIZIA ---
async def droga_autocomplete(interaction: discord.Interaction, current: str):
    conn = get_db_connection()
    cur = conn.cursor()
    # Cerca le droghe esistenti nella tabella droghe_config
    cur.execute("SELECT nome FROM droghe_config WHERE nome ILIKE %s LIMIT 25", (f'%{current}%',))
    choices = [app_commands.Choice(name=row[0].capitalize(), value=row[0]) for row in cur.fetchall()]
    cur.close()
    conn.close()
    return choices

# --- COMANDO INIZIA RACCOLTA ---
@bot.tree.command(name="inizia_raccolta", description="Inizia la raccolta di una droga specifica")
@app_commands.autocomplete(cosa=droga_autocomplete)
async def inizia_raccolta(interaction: discord.Interaction, cosa: str):
    await interaction.response.defer()
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Verifica se la droga scelta esiste effettivamente nella config
        cur.execute("SELECT nome FROM droghe_config WHERE nome = %s", (cosa,))
        if not cur.fetchone():
            cur.close()
            conn.close()
            return await interaction.followup.send("❌ Questa droga non è configurata. Usa una delle opzioni suggerite.", ephemeral=True)

        cur.execute("""
            INSERT INTO sessioni_raccolta (user_id, cosa_raccoglie, inizio_timestamp)
            VALUES (%s, %s, NOW())
            ON CONFLICT (user_id) DO UPDATE SET
                cosa_raccoglie = EXCLUDED.cosa_raccoglie,
                inizio_timestamp = NOW()
        """, (str(interaction.user.id), cosa))
        
        conn.commit()
        cur.close()
        conn.close()
        
        embed = discord.Embed(title="🌿 RACCOLTA AVVIATA", color=discord.Color.blue())
        embed.description = f"Hai iniziato a raccogliere: **{cosa.capitalize()}**\nUsa `/finisci_raccolta` per terminare."
        await interaction.followup.send(embed=embed)
        
    except Exception as e:
        print(f"Errore inizia_raccolta: {e}")
        await interaction.followup.send("❌ Errore tecnico nel database.", ephemeral=True)

# --- COMANDO FINISCI RACCOLTA ---
@bot.tree.command(name="finisci_raccolta", description="Termina la raccolta e ricevi i prodotti")
async def finisci_raccolta(interaction: discord.Interaction):
    await interaction.response.defer()
    
    try:
        conn = get_db_connection()
        from psycopg2.extras import RealDictCursor
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Join tra sessione attiva e configurazione per calcolare il guadagno
        cur.execute("""
            SELECT s.cosa_raccoglie, d.quantita_al_minuto,
            EXTRACT(EPOCH FROM (NOW() - s.inizio_timestamp)) / 60 AS minuti
            FROM sessioni_raccolta s
            JOIN droghe_config d ON s.cosa_raccoglie = d.nome
            WHERE s.user_id = %s
        """, (str(interaction.user.id),))
        
        res = cur.fetchone()
        
        if not res:
            cur.close()
            conn.close()
            return await interaction.followup.send("❌ Non hai sessioni di raccolta attive.", ephemeral=True)

        minuti_passati = int(res['minuti'])
        quantita_guadagnata = minuti_passati * res['quantita_al_minuto']
        item = res['cosa_raccoglie']
        
        # 1. Elimina la sessione
        cur.execute("DELETE FROM sessioni_raccolta WHERE user_id = %s", (str(interaction.user.id),))
        
        # 2. Aggiungi all'inventario se ha raccolto almeno qualcosa
        if quantita_guadagnata > 0:
            cur.execute("""
                INSERT INTO inventory (user_id, item_name, quantity)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id, item_name) DO UPDATE SET
                quantity = inventory.quantity + EXCLUDED.quantity
            """, (str(interaction.user.id), item, quantita_guadagnata))
        
        conn.commit()
        cur.close()
        conn.close()
        
        embed = discord.Embed(title="📦 RACCOLTA COMPLETATA", color=discord.Color.green())
        embed.add_field(name="Cittadino", value=interaction.user.mention, inline=True)
        embed.add_field(name="Prodotto", value=item.capitalize(), inline=True)
        embed.add_field(name="Tempo", value=f"{minuti_passati} minuti", inline=True)
        embed.add_field(name="Quantità Ricevuta", value=f"**x{quantita_guadagnata}**", inline=False)
        
        await interaction.followup.send(embed=embed)
        
    except Exception as e:
        print(f"Errore finisci_raccolta: {e}")
        await interaction.followup.send("❌ Errore nel processare la fine della raccolta.", ephemeral=True)

@bot.command()
@commands.is_owner() # Solo il proprietario del bot può usarlo per sicurezza
async def sync(ctx):
    try:
        # Sincronizza i comandi con l'API di Discord
        synced = await bot.tree.sync()
        await ctx.send(f"✅ Sincronizzazione completata! {len(synced)} comandi slash sono ora attivi.")
    except Exception as e:
        await ctx.send(f"❌ Si è verificato un errore durante il sync: {e}")
# --- COMANDO AGGIORNATO ---
@bot.tree.command(name="anonimo", description="Invia un messaggio criptato sulla rete segreta")
@app_commands.describe(
    messaggio="Il testo del messaggio segreto",
    nickname="Il tuo alias segreto (obbligatorio solo la prima volta o per cambiarlo)"
)
async def anonimo(interaction: discord.Interaction, messaggio: str, nickname: str = None):
    await interaction.response.defer(ephemeral=True)
    
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        cur.execute("SELECT nickname FROM utenti_anonimi WHERE user_id = %s", (str(interaction.user.id),))
        res = cur.fetchone()
        
        if not res and not nickname:
            cur.close()
            conn.close()
            return await interaction.followup.send("❌ Devi specificare un `nickname` la prima volta!", ephemeral=True)
        
        alias_da_usare = nickname if nickname else res['nickname']
        
        if nickname:
            cur.execute("""
                INSERT INTO utenti_anonimi (user_id, nickname)
                VALUES (%s, %s)
                ON CONFLICT (user_id) DO UPDATE SET nickname = EXCLUDED.nickname
            """, (str(interaction.user.id), nickname))
            conn.commit()
            
        desc_testo = (
            f"```\n"
            f"SISTEMA: Connessione Criptata\n"
            f"MITTENTE: {alias_da_usare}\n"
            f"```\n"
            f"**MESSAGGIO RICEVUTO:**\n"
            f"> {messaggio}"
        )

        embed = discord.Embed(
            title="🔐 █▓▒░ ＥＮＣＲＹＰＴＥＤ ＮＥＴＷＯＲＫ ░▒▓█ 🔐",
            description=desc_testo,
            color=discord.Color.dark_theme(),
            timestamp=datetime.datetime.now()
        )
        embed.set_footer(text="Tracciamento IP: Fallito • Rete Anonima")
        
        # Invio e salvataggio ID messaggio per futura investigazione
        msg_inviato = await interaction.channel.send(embed=embed)
        
        # Logghiamo il legame tra messaggio e utente nel DB
        cur.execute("INSERT INTO messaggi_anonimi (message_id, user_id) VALUES (%s, %s)", 
                    (str(msg_inviato.id), str(interaction.user.id)))
        conn.commit()
            
        cur.close()
        conn.close()
        
        await interaction.followup.send("✅ Messaggio inviato in totale anonimato.", ephemeral=True)

    except Exception as e:
        print(f"Errore anonimo: {e}")
        await interaction.followup.send("❌ Errore critico nel sistema di criptazione.", ephemeral=True)


@bot.event
async def on_raw_reaction_add(payload):
    # 1. Configurazione ID Ruolo Staff
    ID_RUOLO_STAFF = 1465432780551753811
     
    
    # 2. Filtro: solo l'emoji corretta e non il bot stesso
    if str(payload.emoji) != "❓" or payload.user_id == bot.user.id:
        return

    # 3. Recupero Server e Membro
    guild = bot.get_guild(payload.guild_id)
    if not guild: return
    member = guild.get_member(payload.user_id)
    if not member: return

    # 4. Controllo Permessi Staff
    is_staff = any(r.id == ID_RUOLO_STAFF for r in member.roles) or member.guild_permissions.administrator

    if is_staff:
        try:
            conn = get_db_connection()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("SELECT user_id FROM messaggi_anonimi WHERE message_id = %s", (str(payload.message_id),))
            res = cur.fetchone()
            
            if res:
                utente_id = int(res['user_id'])
                utente = await bot.fetch_user(utente_id)
                
                # Invio il DM allo staffer
                info_embed = discord.Embed(title="🔍 Identità Svelata", color=discord.Color.red())
                info_embed.add_field(name="Messaggio ID", value=f"`{payload.message_id}`", inline=False)
                info_embed.add_field(name="Autore", value=f"{utente.mention} ({utente.name})", inline=True)
                info_embed.add_field(name="ID Utente", value=f"`{utente_id}`", inline=True)
                
                await member.send(embed=info_embed)

                # --- RIMOZIONE REAZIONE (Il punto critico) ---
                channel = bot.get_channel(payload.channel_id)
                if channel:
                    # Usiamo fetch_message perché il messaggio potrebbe non essere in cache
                    msg = await channel.fetch_message(payload.message_id)
                    await msg.remove_reaction(payload.emoji, member)
            
            cur.close()
            conn.close()
        except Exception as e:
            print(f"Errore durante la rimozione o l'invio DM: {e}")


# --- VIEW PER IL BOTTONE DI VERIFICA ---
# Questa classe gestisce il comportamento del bottone dopo che è stato creato
class VerificaButton(discord.ui.Button):
    def __init__(self, label, emoji, roles_to_assign, dm_message):
        super().__init__(
            label=label,
            emoji=emoji,
            style=discord.ButtonStyle.success,
            custom_id="btn_verifica_evren" # ID statico per farlo funzionare dopo il riavvio
        )
        self.roles_to_assign = roles_to_assign # Lista di ID ruolo
        self.dm_message = dm_message

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        assigned_roles = []
        for role_id in self.roles_to_assign:
            role = interaction.guild.get_role(int(role_id))
            if role:
                try:
                    await interaction.user.add_roles(role)
                    assigned_roles.append(role.name)
                except discord.Forbidden:
                    return await interaction.followup.send("❌ Non ho i permessi per assegnare alcuni ruoli. Controlla la gerarchia!", ephemeral=True)

        # Invio messaggio in DM
        try:
            await interaction.user.send(self.dm_message)
        except:
            pass # DM chiusi, ignoriamo l'errore

        await interaction.followup.send(f"✅ Ti sei verificato con successo! Hai ricevuto: **{', '.join(assigned_roles)}**", ephemeral=True)

# --- COMANDO SETUP VERIFICA ---
@bot.tree.command(name="setup_verifica", description="[ADMIN] Crea il messaggio di verifica")
@app_commands.describe(
    titolo="Titolo dell'embed",
    testo="Testo dell'embed",
    testo_bottone="Scritta sul bottone",
    emoji_bottone="Emoji sul bottone",
    messaggio_dm="Cosa scrivere all'utente in privato",
    colore="Colore della barra laterale",
    ruolo_da_dare="Il ruolo che riceveranno TUTTI"
)
@app_commands.choices(colore=[
    app_commands.Choice(name="Verde", value="green"),
    app_commands.Choice(name="Blu", value="blue"),
    app_commands.Choice(name="Rosso", value="red"),
    app_commands.Choice(name="Grigio", value="grey"),
    app_commands.Choice(name="Giallo", value="yellow")
])
@app_commands.checks.has_permissions(administrator=True)
async def setup_verifica(
    interaction: discord.Interaction, 
    titolo: str, 
    testo: str, 
    testo_bottone: str, 
    emoji_bottone: str,
    messaggio_dm: str,
    ruolo_da_dare: discord.Role, # Questo è quello che riceveranno tutti
    colore: str = "green",
    ruolo_extra_1: discord.Role = None, ruolo_extra_2: discord.Role = None,
    ruolo_extra_3: discord.Role = None, ruolo_extra_4: discord.Role = None,
    ruolo_extra_5: discord.Role = None, ruolo_extra_6: discord.Role = None,
    ruolo_extra_7: discord.Role = None, ruolo_extra_8: discord.Role = None,
    ruolo_extra_9: discord.Role = None
):
    # Mapping dei colori
    colors = {
        "green": discord.Color.green(),
        "blue": discord.Color.blue(),
        "red": discord.Color.red(),
        "grey": discord.Color.light_grey(),
        "yellow": discord.Color.gold()
    }

    # Creiamo la lista degli ID dei ruoli da assegnare (partendo da quello obbligatorio)
    roles_list = [str(ruolo_da_dare.id)]
    
    # Aggiungiamo quelli facoltativi se sono stati inseriti
    optional_roles = [
        ruolo_extra_1, ruolo_extra_2, ruolo_extra_3, ruolo_extra_4, 
        ruolo_extra_5, ruolo_extra_6, ruolo_extra_7, ruolo_extra_8, ruolo_extra_9
    ]
    for r in optional_roles:
        if r:
            roles_list.append(str(r.id))

    # Creazione Embed
    embed = discord.Embed(
        title=titolo,
        description=testo.replace("\\n", "\n"),
        color=colors.get(colore, discord.Color.green())
    )
    
    # Creazione View e Bottone
    view = discord.ui.View(timeout=None)
    view.add_item(VerificaButton(testo_bottone, emoji_bottone, roles_list, messaggio_dm))

    await interaction.channel.send(embed=embed, view=view)
    await interaction.response.send_message("✅ Messaggio di verifica inviato!", ephemeral=True)

# --- COMANDO RP ON ---
@bot.tree.command(name="rpon", description="Segnala che l'RP è ONLINE")
@app_commands.checks.has_role(1253707509399683202)
async def rpon(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🟢 RP ONLINE",
        description="La sessione di Roleplay è ufficialmente **APERTA**. Potete entrare!",
        color=discord.Color.green()
    )
    await interaction.response.send_message(embed=embed)
@bot.tree.command(name="sondaggio", description="Crea un sondaggio per l'orario dell'RP e avvisa tutti in DM")
@app_commands.describe(ora="Inserisci l'orario (es. 21:30)")
@app_commands.checks.has_role( 1465432780551753811)
async def sondaggio(interaction: discord.Interaction, ora: str):
    # 1. Creazione dell'Embed per il canale
    embed = discord.Embed(
        title="🏙️ EVREN CITY RP - SESSIONE PROGRAMMATA",
        description=f"È stata pianificata una nuova sessione!\n\n"
                    f"⏰ Orario: **{ora}**\n"
                    f"📍 Canale: {interaction.channel.mention}\n\n"
                    "Confermate la vostra presenza tramite le reazioni qui sotto:",
        color=discord.Color.gold()
    )
    embed.add_field(name="✅ Si", value="Presente", inline=True)
    embed.add_field(name="❌ No", value="Assente", inline=True)
    embed.add_field(name="🕒 Ritardo", value="In ritardo", inline=True)
    embed.set_footer(text="Evren City RP Staff")
    
    # Conferma l'azione all'admin
    await interaction.response.send_message("Sondaggio creato e invio DM ai cittadini iniziato!", ephemeral=True)
    
    # Invia il messaggio nel canale e aggiunge reazioni
    messaggio = await interaction.channel.send(content="@everyone", embed=embed)
    await messaggio.add_reaction("✅")
    await messaggio.add_reaction("❌")
    await messaggio.add_reaction("🕒")

    # 2. Logica Invio DM a tutti i membri
    embed_dm = discord.Embed(
        title="📢 NUOVO SONDAGGIO RP - EVREN CITY",
        description=f"Ciao Cittadino! È stato indetto un sondaggio per la prossima sessione.\n\n"
                    f"🕔 **Orario scelto:** {ora}\n"
                    f"🔗 **Vota qui:** [Clicca per andare al sondaggio]({messaggio.jump_url})\n\n"
                    "Assicurati di votare per aiutarci a organizzare l'RP!",
        color=discord.Color.blue()
    )
    embed_dm.set_thumbnail(url=interaction.guild.icon.url if interaction.guild.icon else None)

    # Scorre i membri del server
    # Nota: Assicurati di avere i 'members intent' attivi nel pannello developer
    count = 0
    for member in interaction.guild.members:
        if member.bot: continue # Salta i bot
        
        try:
            await member.send(embed=embed_dm)
            count += 1
            # Piccola pausa ogni 5 DM per evitare il rate limit di Discord
            if count % 5 == 0:
                await asyncio.sleep(1)
        except discord.Forbidden:
            # Succede se l'utente ha i DM chiusi
            continue
        except Exception as e:
            print(f"Errore invio DM a {member.name}: {e}")

# --- COMANDO RP OFF ---
@bot.tree.command(name="rpoff", description="Segnala che l'RP è OFFLINE")
@app_commands.checks.has_role(1253707509399683202)
async def rpoff(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🔴 RP OFFLINE",
        description="La sessione di Roleplay è terminata. Grazie a tutti per aver partecipato!",
        color=discord.Color.red()
    )
    await interaction.response.send_message(embed=embed)

# ================= COMANDI ECONOMIA BASE =================

@bot.tree.command(name="portafoglio", description="Visualizza il tuo saldo contanti e in banca")
async def portafoglio(interaction: discord.Interaction):
    u = get_user_data(interaction.user.id)
    
    # Creazione dell'Embed
    embed = discord.Embed(
        title="💰 ESTRATTO CONTO PERSONALE",
        color=discord.Color.gold(), # Colore oro per il tema soldi
        timestamp=datetime.datetime.now()
    )
    
    # Imposta l'avatar dell'utente come miniatura a destra
    embed.set_thumbnail(url=interaction.user.display_avatar.url)
    
    # Campi per i saldi (inline=True li mette uno di fianco all'altro)
    embed.add_field(
        name="💵 Contanti (Wallet)", 
        value=f"**{u['wallet']:,}$**", 
        inline=True
    )
    embed.add_field(
        name="💳 Conto Bancario", 
        value=f"**{u['bank']:,}$**", 
        inline=True
    )
    
    # Calcolo del patrimonio totale
    totale = u['wallet'] + u['bank']
    embed.add_field(
        name="📊 Patrimonio Totale", 
        value=f"**{totale:,}$**", 
        inline=False
    )

    embed.set_footer(text=f"Richiesto da {interaction.user.display_name}")

    await interaction.response.send_message(embed=embed)

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
# --- COMANDO PER CREARE IL DOCUMENTO ---
@bot.tree.command(name="crea_documento", description="Registra il tuo documento d'identità")
@app_commands.choices(genere=[
    app_commands.Choice(name="Maschio", value="Maschio"),
    app_commands.Choice(name="Femmina", value="Femmina")
])
async def crea_documento(
    interaction: discord.Interaction, 
    nome: str, 
    cognome: str, 
    data_di_nascita: str, 
    luogo_di_nascita: str, 
    altezza: int, 
    genere: app_commands.Choice[str]
):
    await interaction.response.defer(ephemeral=True)
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Inserisce o aggiorna se esiste già (così uno può rifarsi il documento)
        cur.execute("""
            INSERT INTO documenti (user_id, nome, cognome, data_nascita, luogo_nascita, altezza, genere)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (user_id) DO UPDATE SET
                nome = EXCLUDED.nome,
                cognome = EXCLUDED.cognome,
                data_nascita = EXCLUDED.data_nascita,
                luogo_nascita = EXCLUDED.luogo_nascita,
                altezza = EXCLUDED.altezza,
                genere = EXCLUDED.genere
        """, (str(interaction.user.id), nome, cognome, data_di_nascita, luogo_di_nascita, altezza, genere.value))
        
        conn.commit()
        cur.close()
        conn.close()
        
        await interaction.followup.send("✅ Documento creato con successo! Usa `/mostra_documento` per vederlo.", ephemeral=True)
        
    except Exception as e:
        print(f"ERRORE CREAZIONE DOCUMENTO: {e}")
        await interaction.followup.send("❌ Errore durante la creazione del documento.", ephemeral=True)

# --- COMANDO PER MOSTRARE IL DOCUMENTO ---
@bot.tree.command(name="mostra_documento", description="Mostra il tuo documento o quello di un altro cittadino")
async def mostra_documento(interaction: discord.Interaction, cittadino: discord.Member = None):
    await interaction.response.defer()
    
    # Se non specifichi un utente, mostra il tuo
    target = cittadino if cittadino else interaction.user
    
    try:
        conn = get_db_connection()
        from psycopg2.extras import RealDictCursor
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        cur.execute("SELECT * FROM documenti WHERE user_id = %s", (str(target.id),))
        doc = cur.fetchone()
        
        cur.close()
        conn.close()
        
        if not doc:
            msg = "Non hai ancora un documento. Crealo con `/crea_documento`!" if target == interaction.user else f"{target.display_name} non ha ancora un documento."
            return await interaction.followup.send(msg)

        # Creazione dell'Embed stile Carta d'Identità
        embed = discord.Embed(
            title="🪪 CARTA D'IDENTITÀ",
            color=discord.Color.dark_red() if doc['genere'] == "Maschio" else discord.Color.magenta()
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="Nome", value=doc['nome'], inline=True)
        embed.add_field(name="Cognome", value=doc['cognome'], inline=True)
        embed.add_field(name="Sesso", value=doc['genere'], inline=True)
        embed.add_field(name="Data di Nascita", value=doc['data_nascita'], inline=True)
        embed.add_field(name="Luogo di Nascita", value=doc['luogo_nascita'], inline=True)
        embed.add_field(name="Altezza", value=f"{doc['altezza']} cm", inline=True)
        embed.set_footer(text=f"ID Cittadino: {target.id}")
        
        # Messaggio di Roleplay
        testo_rp = f"***{interaction.user.display_name}** estrae il documento e lo mostra.*"
        await interaction.followup.send(content=testo_rp, embed=embed)
        
    except Exception as e:
        print(f"ERRORE MOSTRA DOCUMENTO: {e}")
        await interaction.followup.send("❌ Errore nel recupero del documento.")
    # --- COMANDO INIZIO TURNO (Ruolo Libero) ---
# --- MODAL PER MODIFICA STIPENDIO ---
class ModificaStipendioModal(discord.ui.Modal, title="Modifica Stipendio Turno"):
    nuovo_importo = discord.ui.TextInput(label="Nuovo Totale (€)", placeholder="Inserisci la cifra corretta...")

    def __init__(self, user_id, ore, ruolo_nome):
        super().__init__()
        self.user_id = user_id
        self.ore = ore
        self.ruolo_nome = ruolo_nome

    async def on_submit(self, interaction: discord.Interaction):
        try:
            valore = int(self.nuovo_importo.value)
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("""
                UPDATE users SET bank = bank + %s, ore_lavorate = ore_lavorate + %s 
                WHERE user_id = %s
            """, (valore, self.ore, self.user_id))
            conn.commit()
            cur.close()
            conn.close()
            await interaction.response.edit_message(
                content=f"✍️ **STIPENDIO MODIFICATO**: Accreditati **{valore}€** a <@{self.user_id}> (Ruolo: {self.ruolo_nome}).", 
                embed=None, view=None
            )
        except ValueError:
            await interaction.response.send_message("❌ Inserisci un numero valido!", ephemeral=True)

# --- VIEW PER LO STAFF (BOTTONI) ---
class TurnoStaffView(discord.ui.View):
    def __init__(self, user_id, stipendio, ore, ruolo_nome):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.stipendio = stipendio
        self.ore = ore
        self.ruolo_nome = ruolo_nome

    @discord.ui.button(label="Approva", style=discord.ButtonStyle.success)
    async def conferma(self, interaction: discord.Interaction, button: discord.ui.Button):
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("UPDATE users SET bank = bank + %s, ore_lavorate = ore_lavorate + %s WHERE user_id = %s", 
                   (self.stipendio, self.ore, self.user_id))
        conn.commit()
        cur.close()
        conn.close()
        await interaction.response.edit_message(content=f"✅ **APPROVATO**: {self.stipendio}€ accreditati a <@{self.user_id}>.", embed=None, view=None)

    @discord.ui.button(label="Rifiuta", style=discord.ButtonStyle.danger)
    async def annulla(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content=f"❌ **RIFIUTATO**: Turno di <@{self.user_id}> annullato.", embed=None, view=None)

    @discord.ui.button(label="Modifica Importo", style=discord.ButtonStyle.secondary)
    async def modifica(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ModificaStipendioModal(self.user_id, self.ore, self.ruolo_nome))

# --- COMANDI SLASH ---

@bot.tree.command(name="set_canale_paghe", description="Imposta il canale approvazione stipendi (Admin)")
@app_commands.checks.has_permissions(administrator=True)
async def set_canale_paghe(interaction: discord.Interaction, canale: discord.TextChannel):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO server_settings (setting_name, setting_value) VALUES ('canale_paghe', %s) ON CONFLICT (setting_name) DO UPDATE SET setting_value = EXCLUDED.setting_value", (str(canale.id),))
    conn.commit()
    cur.close()
    conn.close()
    await interaction.response.send_message(f"✅ Canale paghe: {canale.mention}")

@bot.tree.command(name="inizia_turno", description="Inizia il turno di lavoro")
async def inizia_turno(interaction: discord.Interaction, ruolo: discord.Role, paga_oraria: int):
    await interaction.response.defer()
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO turni (user_id, inizio, ruolo) VALUES (%s, NOW(), %s) ON CONFLICT (user_id) DO UPDATE SET inizio = NOW(), ruolo = EXCLUDED.ruolo", (str(interaction.user.id), f"{ruolo.name}|{paga_oraria}"))
    conn.commit()
    cur.close()
    conn.close()
    
    embed = discord.Embed(title="🛠️ TURNO INIZIATO", color=discord.Color.green())
    embed.add_field(name="Ruolo", value=ruolo.mention)
    embed.add_field(name="Paga", value=f"{paga_oraria}€/h")
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="finisci_turno", description="Termina il turno e richiedi stipendio")
async def finisci_turno(interaction: discord.Interaction):
    await interaction.response.defer()
    conn = get_db_connection()
    from psycopg2.extras import RealDictCursor
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    cur.execute("SELECT *, EXTRACT(EPOCH FROM (NOW() - inizio)) / 3600 AS ore FROM turni WHERE user_id = %s", (str(interaction.user.id),))
    turno = cur.fetchone()
    cur.execute("SELECT setting_value FROM server_settings WHERE setting_name = 'canale_paghe'")
    res_canale = cur.fetchone()
    
    if not turno or not res_canale:
        cur.close()
        conn.close()
        return await interaction.followup.send("❌ Turno non attivo o canale non configurato.")

    dati = turno['ruolo'].split('|')
    nome_ruolo, paga_h = dati[0], int(dati[1])
    ore_lavorate = round(float(turno['ore']), 2)
    stipendio = int(ore_lavorate * paga_h)
    
    cur.execute("DELETE FROM turni WHERE user_id = %s", (str(interaction.user.id),))
    conn.commit()
    cur.close()
    conn.close()

    # Notifica Utente
    embed_u = discord.Embed(title="🏁 TURNO FINITO", description=f"Ore: `{ore_lavorate}`\nRichiesta inviata allo staff.", color=discord.Color.orange())
    await interaction.followup.send(embed=embed_u)

    # Richiesta Staff
    canale_staff = interaction.guild.get_channel(int(res_canale['setting_value']))
    if canale_staff:
        embed_s = discord.Embed(title="💼 RICHIESTA STIPENDIO", color=discord.Color.blue())
        embed_s.add_field(name="Utente", value=interaction.user.mention)
        embed_s.add_field(name="Ruolo", value=nome_ruolo)
        embed_s.add_field(name="Stipendio", value=f"{stipendio}€ ({ore_lavorate}h)")
        await canale_staff.send(embed=embed_s, view=TurnoStaffView(str(interaction.user.id), stipendio, ore_lavorate, nome_ruolo))


class WipeConfirmView(discord.ui.View):
    def __init__(self, original_interaction):
        super().__init__(timeout=30)
        self.original_interaction = original_interaction

    @discord.ui.button(label="CONFERMA WIPE TOTALE", style=discord.ButtonStyle.danger, emoji="⚠️")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Verifica di sicurezza aggiuntiva sul bottone
        is_owner = await bot.is_owner(interaction.user)
        is_guild_owner = interaction.user == interaction.guild.owner
        
        if not (is_owner or is_guild_owner):
            return await interaction.response.send_message("❌ Non sei autorizzato a confermare questa azione.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        
        try:
            conn = get_db_connection()
            cur = conn.cursor()

            # Elenco di tutte le tabelle da svuotare (TRUNCATE le svuota all'istante)
            tabelle = [
                "users", "inventory", "items", "ricette", "veicoli", 
                "documenti", "fatture", "multe", "arresti", "depositi", 
                "depositi_items", "turni", "sessioni_raccolta"
            ]
            
            # Eseguiamo il reset
            query = f"TRUNCATE TABLE {', '.join(tabelle)} RESTART IDENTITY CASCADE;"
            cur.execute(query)
            
            conn.commit()
            await interaction.followup.send("✅ **WIPE COMPLETATO.** Il database è stato resettato correttamente.", ephemeral=True)
            
            # Log opzionale nel canale log se lo hai configurato
            # await send_log("⚠️ WIPE TOTALE eseguito da " + interaction.user.name)

        except Exception as e:
            await interaction.followup.send(f"❌ Errore durante il wipe: `{e}`", ephemeral=True)
        finally:
            if conn: cur.close(); conn.close()

    @discord.ui.button(label="Annulla", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="❌ Operazione annullata.", view=None)

@bot.tree.command(name="wipe_totale", description="ELIMINA TUTTI I DATI (Solo Owner)")
async def wipe_totale(interaction: discord.Interaction):
    # 1. Controllo se è il proprietario del bot o del server
    is_owner = await bot.is_owner(interaction.user)
    is_guild_owner = interaction.user == interaction.guild.owner

    if not (is_owner or is_guild_owner):
        return await interaction.response.send_message("⛔ Solo il proprietario del server o del bot può eseguire questa azione!", ephemeral=True)

    # 2. Messaggio di avvertimento con bottone
    embed = discord.Embed(
        title="⚠️ ATTENZIONE: WIPE TOTALE",
        description=(
            "Stai per eliminare **TUTTI** i dati del server:\n"
            "• Account utenti (Banca e Portafoglio)\n"
            "• Inventari e Veicoli\n"
            "• Catalogo Shop e Ricette\n"
            "• Documenti, Fatture e Multe\n\n"
            "**Questa azione è irreversibile.** Vuoi procedere?"
        ),
        color=discord.Color.red()
    )
    
    view = WipeConfirmView(interaction)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

# --- COMANDO PER ELIMINARE IL DOCUMENTO (SOLO ADMIN) ---
@bot.tree.command(name="elimina_documento", description="Elimina il documento di un cittadino (Solo Staff)")
@app_commands.describe(cittadino="Il cittadino a cui vuoi cancellare il documento")
async def elimina_documento(interaction: discord.Interaction, cittadino: discord.Member):
    # Controllo se l'utente ha il ruolo richiesto
    if not any(role.id == RUOLO_STAFF_ID for role in interaction.user.roles):
        return await interaction.response.send_message(
            "❌ Non hai i permessi necessari (Ruolo Staff richiesto) per usare questo comando.", 
            ephemeral=True
        )

    await interaction.response.defer(ephemeral=True)
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Verifichiamo prima se il documento esiste
        cur.execute("SELECT nome, cognome FROM documenti WHERE user_id = %s", (str(cittadino.id),))
        result = cur.fetchone()
        
        if not result:
            cur.close()
            conn.close()
            return await interaction.followup.send(f"❌ Nessun documento trovato per {cittadino.display_name}.", ephemeral=True)
        
        # Eliminazione fisica dalla tabella
        cur.execute("DELETE FROM documenti WHERE user_id = %s", (str(cittadino.id),))
        
        conn.commit()
        cur.close()
        conn.close()
        
        await interaction.followup.send(
            f"✅ Documento di **{result[0]} {result[1]}** ({cittadino.display_name}) eliminato permanentemente dal database.", 
            ephemeral=True
        )
        
    except Exception as e:
        print(f"ERRORE ELIMINAZIONE DOCUMENTO: {e}")
        await interaction.followup.send("❌ Errore tecnico durante l'eliminazione.", ephemeral=True)
        
        
        
# --- CLASSE VIEW PER IL CRAFTING ---
class CraftingView(discord.ui.View):
    def __init__(self, item_risultato, materiali_dict, user_id):
        super().__init__(timeout=None)
        self.item_risultato = item_risultato
        self.materiali_dict = materiali_dict
        self.user_id = user_id

    @discord.ui.button(label="Inizia Crafting (1m)", style=discord.ButtonStyle.success, emoji="🔨")
    async def inizia_craft(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.user_id:
            return await interaction.response.send_message("❌ Questo banco da lavoro non è tuo.", ephemeral=True)

        user_id = self.user_id
        conn = get_db_connection()
        cur = conn.cursor()

        # 1. Verifica disponibilità materiali
        for mat, qta in self.materiali_dict.items():
            cur.execute("SELECT quantity FROM inventory WHERE user_id = %s AND item_name ILIKE %s", (user_id, mat))
            res = cur.fetchone()
            if not res or res[0] < qta:
                cur.close(); conn.close()
                return await interaction.response.send_message(f"❌ Ti mancano dei materiali: **{mat}**.", ephemeral=True)

        # 2. Avvio processo
        button.disabled = True
        button.label = "🔨 Lavorazione..."
        await interaction.response.edit_message(view=self)

        # 3. Timer di 60 secondi
        tempo_rimanente = 60
        while tempo_rimanente > 0:
            await asyncio.sleep(10)
            tempo_rimanente -= 10
            if tempo_rimanente > 0:
                try:
                    await interaction.edit_original_response(content=f"🔨 Stai assemblando **{self.item_risultato}**... `{tempo_rimanente}s` al termine.")
                except: break

        # 4. Conclusione
        try:
            for mat, qta in self.materiali_dict.items():
                cur.execute("UPDATE inventory SET quantity = quantity - %s WHERE user_id = %s AND item_name ILIKE %s", (qta, user_id, mat))
            
            cur.execute("""
                INSERT INTO inventory (user_id, item_name, quantity) VALUES (%s, %s, 1) 
                ON CONFLICT (user_id, item_name) DO UPDATE SET quantity = inventory.quantity + 1
            """, (user_id, self.item_risultato))
            
            cur.execute("DELETE FROM inventory WHERE quantity <= 0")
            conn.commit()

            await interaction.edit_original_response(content=f"✅ **CRAFTING COMPLETATO!**\nHai ottenuto: **{self.item_risultato}**.", view=None, embed=None)
        except Exception as e:
            await interaction.edit_original_response(content=f"❌ Errore DB: {e}", view=None)
        finally:
            cur.close(); conn.close()

# --- FUNZIONE AUTOCOMPLETE ---
async def ricette_autocomplete(interaction: discord.Interaction, current: str):
    conn = get_db_connection()
    from psycopg2.extras import RealDictCursor
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT item_risultato FROM ricette WHERE item_risultato ILIKE %s LIMIT 25", (f'%{current}%',))
    ricette = cur.fetchall()
    cur.close(); conn.close()
    return [app_commands.Choice(name=r['item_risultato'].title(), value=r['item_risultato']) for r in ricette]

# --- COMANDO STAFF: SET RICETTA ---
@bot.tree.command(name="set_ricetta", description="[STAFF] Crea o modifica una ricetta di crafting")
@app_commands.describe(item_finale="Nome dell'oggetto finale", materiali="Esempio: Ferro:3,Legno:2")
@app_commands.checks.has_role(RUOLO_STAFF_ID)
async def set_ricetta(interaction: discord.Interaction, item_finale: str, materiali: str):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO ricette (item_risultato, materiali) 
            VALUES (%s, %s) 
            ON CONFLICT (item_risultato) DO UPDATE SET materiali = EXCLUDED.materiali
        """, (item_finale.lower(), materiali))
        conn.commit()
        cur.close(); conn.close()
        await interaction.response.send_message(f"✅ Ricetta per **{item_finale}** salvata correttamente.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ Errore: {e}", ephemeral=True)

# --- COMANDO UTENTE: CRAFTA ---
@bot.tree.command(name="crafta", description="Apri il banco da lavoro per costruire un oggetto")
@app_commands.describe(item="Oggetto da costruire")
@app_commands.autocomplete(item=ricette_autocomplete)
async def crafta(interaction: discord.Interaction, item: str):
    conn = get_db_connection()
    from psycopg2.extras import RealDictCursor
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    cur.execute("SELECT * FROM ricette WHERE item_risultato = %s", (item.lower(),))
    ricetta = cur.fetchone()
    cur.close(); conn.close()

    if not ricetta:
        return await interaction.response.send_message("❌ Questo oggetto non è craftabile.", ephemeral=True)

    materiali_dict = {}
    testo_materiali = ""
    for m in ricetta['materiali'].split(','):
        nome, qta = m.split(':')
        materiali_dict[nome.strip()] = int(qta)
        testo_materiali += f"• **{nome.strip()}**: x{qta}\n"

    embed = discord.Embed(
        title=f"🛠️ Banco da Lavoro: {item.title()}",
        description=f"Per procedere sono necessari i seguenti materiali:\n\n{testo_materiali}\n*Tempo richiesto: 60 secondi.*",
        color=0x2C3E50
    )

    view = CraftingView(item.title(), materiali_dict, str(interaction.user.id))
    await interaction.response.send_message(embed=embed, view=view)

# --- GESTORE ERRORE RUOLO ---
@set_ricetta.error
async def set_ricetta_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingRole):
        await interaction.response.send_message("❌ Solo lo Staff può gestire le ricette.", ephemeral=True)

POLIZIA_ROLE_ID = 1359569600198611104

# --- FUNZIONE DI CONTROLLO POLIZIA ---
def is_polizia(interaction: discord.Interaction):
    return any(role.id == POLIZIA_ROLE_ID for role in interaction.user.roles)
# Sostituisci con l'ID reale del ruolo Polizia

# --- COMANDO: SEQUESTRA MEZZO ---
@bot.tree.command(name="sequestra_mezzo", description="Metti sotto sequestro un veicolo (Solo Polizia)")
@app_commands.describe(targa="La targa del veicolo da sequestrare")
async def sequestra_mezzo(interaction: discord.Interaction, targa: str):
    # Controllo Ruolo Polizia
    if not any(role.id == POLIZIA_ROLE_ID for role in interaction.user.roles):
        return await interaction.response.send_message("❌ Non sei autorizzato a eseguire sequestri.", ephemeral=True)

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Controlla se il veicolo esiste
        cur.execute("SELECT modello, owner_id FROM veicoli WHERE targa = %s", (targa.upper(),))
        veicolo = cur.fetchone()
        
        if not veicolo:
            cur.close()
            conn.close()
            return await interaction.response.send_message(f"❌ Nessun veicolo trovato con targa **{targa.upper()}**.", ephemeral=True)

        # Aggiorna lo stato in sequestrato
        cur.execute("UPDATE veicoli SET sequestrato = TRUE WHERE targa = %s", (targa.upper(),))
        
        conn.commit()
        cur.close()
        conn.close()

        embed = discord.Embed(
            title="🚔 SEQUESTRO EFFETTUATO",
            description=f"Il veicolo con targa **{targa.upper()}** è stato posto sotto sequestro.",
            color=discord.Color.dark_red()
        )
        embed.add_field(name="Modello", value=veicolo[0])
        embed.add_field(name="Proprietario", value=f"<@{veicolo[1]}>")
        embed.set_footer(text=f"Agente: {interaction.user.display_name}")

        await interaction.response.send_message(embed=embed)

    except Exception as e:
        await interaction.response.send_message(f"❌ Errore: {e}", ephemeral=True)

# --- COMANDO: LISTA E DISSEQUESTRO ---
@bot.tree.command(name="gestisci_sequestri", description="Visualizza e gestisci i mezzi sequestrati (Solo Polizia)")
async def gestisci_sequestri(interaction: discord.Interaction):
    if not any(role.id == POLIZIA_ROLE_ID for role in interaction.user.roles):
        return await interaction.response.send_message("❌ Accesso negato.", ephemeral=True)

    await interaction.response.defer()

    try:
        conn = get_db_connection()
        from psycopg2.extras import RealDictCursor
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Recupera tutti i mezzi sequestrati
        cur.execute("SELECT targa, modello, owner_id FROM veicoli WHERE sequestrato = TRUE")
        sequestrati = cur.fetchall()
        
        if not sequestrati:
            cur.close()
            conn.close()
            return await interaction.followup.send("📑 Non ci sono veicoli attualmente sotto sequestro.")

        embed = discord.Embed(
            title="📋 REGISTRO SEQUESTRI",
            description="Ecco la lista dei mezzi nel deposito giudiziario:",
            color=discord.Color.blue()
        )

        for v in sequestrati:
            embed.add_field(
                name=f"🚗 {v['modello']} ({v['targa']})",
                value=f"Proprietario: <@{v['owner_id']}>\nPer dissequestrare: `/dissequestra {v['targa']}`",
                inline=False
            )

        cur.close()
        conn.close()
        await interaction.followup.send(embed=embed)

    except Exception as e:
        await interaction.followup.send(f"❌ Errore nel recupero dati: {e}", ephemeral=True)

# --- COMANDO: DISSEQUESTRA (SOTTO-COMANDO DI SUPPORTO) ---
@bot.tree.command(name="dissequestra", description="Rilascia un veicolo dal sequestro (Solo Polizia)")
@app_commands.describe(targa="Targa del veicolo da rilasciare")
async def dissequestra(interaction: discord.Interaction, targa: str):
    if not any(role.id == POLIZIA_ROLE_ID for role in interaction.user.roles):
        return await interaction.response.send_message("❌ Non autorizzato.", ephemeral=True)

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("UPDATE veicoli SET sequestrato = FALSE WHERE targa = %s AND sequestrato = TRUE", (targa.upper(),))
        
        if cur.rowcount == 0:
            cur.close()
            conn.close()
            return await interaction.response.send_message("❌ Il veicolo non è sotto sequestro o la targa è errata.", ephemeral=True)

        conn.commit()
        cur.close()
        conn.close()
        
        await interaction.response.send_message(f"✅ Il veicolo **{targa.upper()}** è stato dissequestrato e restituito al proprietario.")
        
    except Exception as e:
        await interaction.response.send_message(f"❌ Errore DB: {e}", ephemeral=True)

# --- COMANDO /MULTA ---
@bot.tree.command(name="multa", description="Emetti una sanzione a un cittadino")
async def multa(interaction: discord.Interaction, utente: discord.Member, ammontare: int, motivo: str, dipartimento: discord.Role):
    if not is_polizia(interaction):
        return await interaction.response.send_message("❌ Solo i membri della Polizia possono multare!", ephemeral=True)
    
    await interaction.response.defer()
    id_m = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
    data_attuale = datetime.datetime.now().strftime("%d/%m/%Y")

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO multe (id_multa, user_id, ammontare, id_azienda, motivo, data)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (id_m, str(utente.id), ammontare, str(dipartimento.id), motivo, data_attuale))
        conn.commit()
        cur.close()
        conn.close()

        embed = discord.Embed(title="🚨 Multa Emessa", color=discord.Color.red())
        embed.add_field(name="Cittadino", value=utente.mention, inline=True)
        embed.add_field(name="Importo", value=f"{ammontare}$", inline=True)
        embed.add_field(name="Dipartimento", value=dipartimento.name, inline=True)
        embed.add_field(name="Motivo", value=motivo, inline=False)
        embed.set_footer(text=f"ID Multa: {id_m} | Usa /pagamulta")
        
        await interaction.followup.send(content=f"✅ Multa registrata per {utente.mention}", embed=embed)
    except Exception as e:
        print(f"Errore multa: {e}")
        await interaction.followup.send("❌ Errore nel database.")

# --- COMANDO /PAGAMULTA ---
@bot.tree.command(name="pagamulta", description="Paga le tue sanzioni pendenti")
async def pagamulta(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        conn = get_db_connection()
        from psycopg2.extras import RealDictCursor
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Cerchiamo l'ultima multa pendente dell'utente
        cur.execute("SELECT * FROM multe WHERE user_id = %s LIMIT 1", (str(interaction.user.id),))
        multa = cur.fetchone()
        
        if not multa:
            return await interaction.followup.send("✅ Non hai multe da pagare.")

        # Controllo se ha i soldi nel wallet (tabella users)
        cur.execute("SELECT wallet FROM users WHERE user_id = %s", (str(interaction.user.id),))
        user_wallet = cur.fetchone()

        if not user_wallet or user_wallet['wallet'] < multa['ammontare']:
            return await interaction.followup.send(f"❌ Non hai abbastanza contanti! Ti servono {multa['ammontare']}$.")

        # TRANSAZIONE: Scala wallet -> Aggiungi a depositi fazione -> Elimina multa
        cur.execute("UPDATE users SET wallet = wallet - %s WHERE user_id = %s", (multa['ammontare'], str(interaction.user.id)))
        
        cur.execute("""
            INSERT INTO depositi (role_id, money) VALUES (%s, %s)
            ON CONFLICT (role_id) DO UPDATE SET money = depositi.money + EXCLUDED.money
        """, (multa['id_azienda'], multa['ammontare']))
        
        cur.execute("DELETE FROM multe WHERE id_multa = %s", (multa['id_multa'],))
        
        conn.commit()
        cur.close()
        conn.close()

        await interaction.followup.send(f"✅ Hai pagato la multa di {multa['ammontare']}$. I soldi sono andati al dipartimento.")
    except Exception as e:
        print(f"Errore pagamulta: {e}")
        await interaction.followup.send("❌ Errore nel pagamento.")
@bot.tree.command(name="arresto", description="Registra un arresto nel database e annuncialo in chat")
@app_commands.describe(
    utente="Il cittadino da arrestare",
    tempo_minuti="Durata della pena in minuti",
    motivo="Il reato commesso"
)
async def arresto(interaction: discord.Interaction, utente: discord.Member, tempo_minuti: int, motivo: str):
    # Controllo se l'utente è un poliziotto
    if not any(role.id == 1359569600198611104 for role in interaction.user.roles):

        return await interaction.response.send_message("❌ Non hai i permessi per effettuare un arresto.", ephemeral=True)

    await interaction.response.defer()
    
    data_attuale = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # 1. Salvataggio nel database per la futura /ricerca
        cur.execute("""
            INSERT INTO arresti (user_id, agente_id, motivo, tempo, data)
            VALUES (%s, %s, %s, %s, %s)
        """, (str(utente.id), str(interaction.user.id), motivo, tempo_minuti, data_attuale))
        
        conn.commit()
        cur.close()
        conn.close()

        # 2. Creazione dell'Embed per il Roleplay
        embed = discord.Embed(
            title="⚖️ VERBALE DI ARRESTO",
            color=discord.Color.dark_blue(),
            timestamp=datetime.datetime.now()
        )
        embed.set_thumbnail(url="https://i.imgur.com/8f6uT8R.png") # Opzionale: un'icona della polizia
        
        embed.add_field(name="👤 Detenuto", value=utente.mention, inline=True)
        embed.add_field(name="⏳ Pena", value=f"{tempo_minuti} minuti", inline=True)
        embed.add_field(name="👮 Agente", value=interaction.user.mention, inline=False)
        embed.add_field(name="📝 Motivo", value=motivo, inline=False)
        
        embed.set_footer(text=f"ID Caso registrato nel sistema centrale")

        # Invio del messaggio pubblico
        await interaction.followup.send(
            content=f"🚨 {utente.mention} è stato preso in custodia.",
            embed=embed
        )

    except Exception as e:
        print(f"ERRORE ARRESTO: {e}")
        await interaction.followup.send("❌ Errore durante la registrazione dell'arresto su Supabase.", ephemeral=True)

# --- COMANDI FISICI: AMMANETTA, SMANETTA, ARRESTO ---
@bot.tree.command(name="ammanetta", description="Metti le manette a un cittadino")
async def ammanetta(interaction: discord.Interaction, utente: discord.Member):
    if not is_polizia(interaction):
        return await interaction.response.send_message("❌ Solo la Polizia può usare le manette.", ephemeral=True)
    await interaction.response.send_message(f"🔗 **{interaction.user.display_name}** ha ammanettato **{utente.display_name}**.")

@bot.tree.command(name="smanetta", description="Togli le manette a un cittadino")
async def smanetta(interaction: discord.Interaction, utente: discord.Member):
    if not is_polizia(interaction):
        return await interaction.response.send_message("❌ Non hai le chiavi delle manette.", ephemeral=True)
    await interaction.response.send_message(f"🔓 **{interaction.user.display_name}** ha rimosso le manette a **{utente.display_name}**.")@bot.tree.command(name="arresto", description="Porta un cittadino in cella e registra l'arresto")
async def arresto(interaction: discord.Interaction, utente: discord.Member, tempo_minuti: int, motivo: str):
    if not is_polizia(interaction):
        return await interaction.response.send_message("❌ Non sei un agente.", ephemeral=True)
    
    await interaction.response.defer()
    data_attuale = datetime.datetime.now().strftime("%d/%m/%Y")

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO arresti (user_id, agente_id, motivo, tempo, data)
            VALUES (%s, %s, %s, %s, %s)
        """, (str(utente.id), str(interaction.user.id), motivo, tempo_minuti, data_attuale))
        conn.commit()
        cur.close()
        conn.close()

        embed = discord.Embed(title="⚖️ Verbale di Arresto", color=discord.Color.dark_blue())
        embed.add_field(name="Detenuto", value=utente.mention, inline=True)
        embed.add_field(name="Tempo", value=f"{tempo_minuti} minuti", inline=True)
        embed.add_field(name="Agente", value=interaction.user.mention, inline=False)
        embed.add_field(name="Motivo", value=motivo, inline=False)
        
        await interaction.followup.send(embed=embed)
    except Exception as e:
        print(f"Errore arresto: {e}")
        await interaction.followup.send("❌ Errore nel salvataggio dell'arresto.")
# --- CLASSE PER IL MENU DI SCELTA CITTADINO ---
class CitizenSelect(discord.ui.Select):
    def __init__(self, options, original_interaction):
        super().__init__(placeholder="Seleziona il cittadino corretto...", options=options)
        self.original_interaction = original_interaction

    async def callback(self, interaction: discord.Interaction):
        # Quando l'utente seleziona qualcuno dal menu, richiamiamo la visualizzazione del fascicolo
        await interaction.response.defer()
        target_id = self.values[0]
        # Funzione helper per mostrare il fascicolo (definita sotto)
        await mostra_fascicolo(interaction, target_id, self.original_interaction)

class CitizenView(discord.ui.View):
    def __init__(self, options, original_interaction):
        super().__init__(timeout=60)
        self.add_item(CitizenSelect(options, original_interaction))

# --- COMANDO RICERCA AGGIORNATO ---
@bot.tree.command(name="ricerca_cittadino", description="Ricerca avanzata con selezione multipla")
@app_commands.describe(
    cittadino="Tagga l'utente (opzionale)",
    nome="Nome o parte del nome (opzionale)",
    cognome="Cognome o parte del cognome (opzionale)"
)
async def ricerca(interaction: discord.Interaction, cittadino: discord.Member = None, nome: str = None, cognome: str = None):
    if not any(role.id == POLIZIA_ROLE_ID for role in interaction.user.roles):
        return await interaction.response.send_message("❌ Accesso negato.", ephemeral=True)
    
    await interaction.response.defer()

    try:
        conn = get_db_connection()
        from psycopg2.extras import RealDictCursor
        cur = conn.cursor(cursor_factory=RealDictCursor)

        if cittadino:
            cur.close()
            conn.close()
            return await mostra_fascicolo(interaction, str(cittadino.id))

        if nome or cognome:
            search_nome = f"%{nome}%" if nome else "%"
            search_cognome = f"%{cognome}%" if cognome else "%"

            cur.execute("""
                SELECT user_id, nome, cognome FROM documenti 
                WHERE nome ILIKE %s AND cognome ILIKE %s
                LIMIT 25
            """, (search_nome, search_cognome))
            
            results = cur.fetchall()
            cur.close()
            conn.close()

            if not results:
                return await interaction.followup.send("❌ Nessun cittadino trovato.")
            
            if len(results) == 1:
                # Un solo risultato, vai diretto
                return await mostra_fascicolo(interaction, results[0]['user_id'])
            
            # Più risultati: crea il menu a tendina
            options = [
                discord.SelectOption(
                    label=f"{r['nome']} {r['cognome']}", 
                    description=f"ID: {r['user_id']}", 
                    value=r['user_id']
                ) for r in results
            ]
            
            view = CitizenView(options, interaction)
            await interaction.followup.send("🔎 Ho trovato più persone. Seleziona quella corretta:", view=view)
        else:
            return await interaction.followup.send("⚠️ Inserisci un TAG o un Nome/Cognome.")

    except Exception as e:
        print(f"Errore ricerca: {e}")
        await interaction.followup.send("❌ Errore nel database.")

# --- FUNZIONE HELPER PER MOSTRARE IL FASCICOLO ---
async def mostra_fascicolo(interaction, target_id, original_interaction=None):
    # original_interaction serve se stiamo rispondendo a una selezione dal menu
    ctx = interaction if not original_interaction else original_interaction
    
    try:
        conn = get_db_connection()
        from psycopg2.extras import RealDictCursor
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # Query dati (Documenti, Veicoli, Multe, Arresti)
        cur.execute("SELECT * FROM documenti WHERE user_id = %s", (target_id,))
        doc = cur.fetchone()
        cur.execute("SELECT targa, modello, sequestrato FROM veicoli WHERE owner_id = %s", (target_id,))
        veicoli = cur.fetchall()
        cur.execute("SELECT * FROM multe WHERE user_id = %s", (target_id,))
        multe = cur.fetchall()
        cur.execute("SELECT * FROM arresti WHERE user_id = %s ORDER BY id_arresto DESC LIMIT 5", (target_id,))
        arresti = cur.fetchall()
        cur.close()
        conn.close()

        target_member = ctx.guild.get_member(int(target_id))
        nome_display = f"{doc['nome']} {doc['cognome']}" if doc else "Sconosciuto"
        
        embed = discord.Embed(title=f"📁 FASCICOLO: {nome_display}", color=discord.Color.dark_blue())
        embed.description = f"**ID Discord:** `{target_id}`"
        
        if target_member:
            embed.set_thumbnail(url=target_member.display_avatar.url)

        if doc:
            embed.add_field(name="🪪 Anagrafica", value=f"Nascita: {doc['data_nascita']} ({doc['luogo_nascita']})\nSesso: {doc['genere']} | H: {doc['altezza']}cm", inline=False)
        
        if veicoli:
            v_list = "\n".join([f"• `{v['targa']}` - {v['modello']} {'(🚫)' if v['sequestrato'] else ''}" for v in veicoli])
            embed.add_field(name="🚘 Veicoli", value=v_list, inline=False)
        
        if multe:
            m_list = "\n".join([f"• {m['ammontare']}€ - {m['motivo']}" for m in multe])
            embed.add_field(name="⚠️ Multe", value=m_list, inline=False)

        if arresti:
            a_list = "\n".join([f"• {a['data']}: {a['motivo']}" for a in arresti])
            embed.add_field(name="🚔 Arresti", value=a_list, inline=False)

        # Se veniamo dal menu, dobbiamo usare followup.send o edit_original_response
        if original_interaction:
            await interaction.followup.send(embed=embed)
        else:
            await ctx.followup.send(embed=embed)

    except Exception as e:
        print(f"Errore mostra_fascicolo: {e}")





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

# --- FUNZIONE AUTOCOMPLETE (Suggerimenti dinamici) ---
async def inventory_autocomplete(interaction: discord.Interaction, current: str):
    """Suggerisce all'utente solo gli oggetti che possiede realmente nel DB"""
    conn = get_db_connection()
    from psycopg2.extras import RealDictCursor
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    # Cerca gli item dell'utente filtrando per quello che sta scrivendo (case-insensitive)
    cur.execute("""
        SELECT item_name 
        FROM inventory 
        WHERE user_id = %s AND item_name ILIKE %s 
        LIMIT 25
    """, (str(interaction.user.id), f'%{current}%'))
    
    items = cur.fetchall()
    cur.close()
    conn.close()
    
    # Genera la lista di scelte per Discord
    return [app_commands.Choice(name=f"{item['item_name']}", value=item['item_name']) for item in items]

# --- COMANDO: DAI ITEM ---
@bot.tree.command(name="dai_item", description="Passa un oggetto dal tuo inventario a un altro utente")
@app_commands.describe(
    utente="L'utente a cui dare l'oggetto", 
    nome="Seleziona l'oggetto dal tuo inventario", 
    quantita="Quante unità vuoi passare"
)
@app_commands.autocomplete(nome=inventory_autocomplete) # Attiva la selezione suggerita
async def dai_item(interaction: discord.Interaction, utente: discord.Member, nome: str, quantita: int = 1):
    # Controllo di base: non dare a se stessi
    if utente.id == interaction.user.id: 
        return await interaction.response.send_message("❌ Non puoi passare oggetti a te stesso.", ephemeral=True)
    
    if quantita <= 0:
        return await interaction.response.send_message("❌ Inserisci una quantità valida (minimo 1).", ephemeral=True)

    await interaction.response.defer()
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    # 1. Verifica se il mittente ha l'oggetto e ne ha abbastanza
    cur.execute("SELECT quantity FROM inventory WHERE user_id = %s AND item_name = %s", (str(interaction.user.id), nome))
    res = cur.fetchone()
    
    if not res or res[0] < quantita:
        cur.close(); conn.close()
        return await interaction.followup.send(f"❌ Non hai abbastanza **{nome}** (Posseduti: {res[0] if res else 0}).")

    try:
        # 2. Sottrae gli oggetti al mittente
        cur.execute("UPDATE inventory SET quantity = quantity - %s WHERE user_id = %s AND item_name = %s", (quantita, str(interaction.user.id), nome))
        
        # 3. Aggiunge gli oggetti al destinatario (Gestisce la creazione se non esiste)
        cur.execute("""
            INSERT INTO inventory (user_id, item_name, quantity) 
            VALUES (%s, %s, %s) 
            ON CONFLICT (user_id, item_name) 
            DO UPDATE SET quantity = inventory.quantity + EXCLUDED.quantity
        """, (str(utente.id), nome, quantita))
        
        # 4. Pulizia automatica: elimina righe con quantità zero
        cur.execute("DELETE FROM inventory WHERE quantity <= 0")
        
        conn.commit()
        await interaction.followup.send(f"📦 **{interaction.user.display_name}** ha passato {quantita}x **{nome}** a **{utente.mention}**.")
    
    except Exception as e:
        print(f"Errore comando dai_item: {e}")
        await interaction.followup.send("❌ Si è verificato un errore durante lo scambio.")
    finally:
        cur.close(); conn.close()

# --- COMANDO: USA ---
@bot.tree.command(name="usa", description="Usa un oggetto dal tuo inventario")
@app_commands.describe(nome="Seleziona l'oggetto da usare")
@app_commands.autocomplete(nome=inventory_autocomplete) # Attiva la selezione suggerita
async def usa(interaction: discord.Interaction, nome: str):
    await interaction.response.defer()
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    # 1. Verifica se l'utente possiede l'oggetto selezionato
    cur.execute("SELECT quantity FROM inventory WHERE user_id = %s AND item_name = %s", (str(interaction.user.id), nome))
    res = cur.fetchone()
    
    if not res or res[0] <= 0:
        cur.close(); conn.close()
        return await interaction.followup.send(f"❌ Non possiedi l'oggetto **{nome}**.")

    try:
        # 2. Sottrae 1 unità dall'inventario
        cur.execute("UPDATE inventory SET quantity = quantity - 1 WHERE user_id = %s AND item_name = %s", (str(interaction.user.id), nome))
        
        # 3. Elimina l'oggetto se la quantità è arrivata a zero
        cur.execute("DELETE FROM inventory WHERE quantity <= 0")
        
        conn.commit()
        await interaction.followup.send(f"✨ **{interaction.user.display_name}** ha usato **{nome}**!")
        
    except Exception as e:
        print(f"Errore comando usa: {e}")
        await interaction.followup.send("❌ Errore durante l'uso dell'oggetto.")
    finally:
        cur.close(); conn.close()

# 1. DEFINIZIONE DELLA CLASSE (Deve stare sopra il comando)
# ==========================================
# 1. CLASSE PER IL PAGAMENTO (PagaFatturaView)
# ==========================================
class PagaFatturaView(discord.ui.View):
    def __init__(self, user_id, fatture):
        super().__init__(timeout=180)
        self.user_id = user_id
        
        options = []
        for f in fatture:
            # Salviamo: ID Fattura | Prezzo | ID Azienda (Ruolo)
            options.append(discord.SelectOption(
                label=f"Fattura {f['id_fattura']}",
                description=f"Importo: {f['prezzo']}$",
                value=f"{f['id_fattura']}|{f['prezzo']}|{f['id_azienda']}"
            ))
            
        self.select = discord.ui.Select(placeholder="Scegli la fattura da saldare...", options=options)
        self.select.callback = self.select_callback
        self.add_item(self.select)

    async def select_callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        # Spacchettiamo i dati
        data = self.select.values[0].split('|')
        id_f = data[0]
        prezzo = int(data[1])
        id_azienda = data[2] # Questo è l'ID numerico del ruolo

        try:
            conn = get_db_connection()
            from psycopg2.extras import RealDictCursor
            cur = conn.cursor(cursor_factory=RealDictCursor)
            
            # 1. Controllo se il cittadino ha i soldi nel wallet
            cur.execute("SELECT wallet FROM users WHERE user_id = %s", (str(interaction.user.id),))
            user_data = cur.fetchone()
            
            if not user_data or user_data['wallet'] < prezzo:
                cur.close()
                conn.close()
                return await interaction.followup.send("❌ Non hai abbastanza contanti nel wallet!", ephemeral=True)

            # --- TRANSAZIONE ECONOMICA ---
            # A. Sottrazione soldi al cittadino
            cur.execute("UPDATE users SET wallet = wallet - %s WHERE user_id = %s", (prezzo, str(interaction.user.id)))
            
            # B. Accredito nel deposito fazione (Usa l'ID del ruolo)
            cur.execute("""
                INSERT INTO depositi (role_id, money) 
                VALUES (%s, %s) 
                ON CONFLICT (role_id) 
                DO UPDATE SET money = depositi.money + EXCLUDED.money
            """, (str(id_azienda), prezzo))
            
            # C. Aggiornamento stato fattura
            cur.execute("UPDATE fatture SET stato = 'Pagata' WHERE id_fattura = %s", (id_f,))
            
            conn.commit()
            cur.close()
            conn.close()

            self.select.disabled = True
            await interaction.edit_original_response(
                content=f"✅ Fattura `{id_f}` pagata! **{prezzo}$** accreditati nel deposito fazione.", 
                view=self
            )

        except Exception as e:
            print(f"ERRORE SQL PAGAMENTO: {e}")
            await interaction.followup.send("❌ Errore durante il trasferimento dei fondi.", ephemeral=True)

# ==========================================
# 2. COMANDO PER EMETTERE FATTURA (/fattura)
# ==========================================
@bot.tree.command(name="fattura", description="Emetti una fattura a un cittadino")
async def fattura(interaction: discord.Interaction, cliente: discord.Member, azienda: discord.Role, descrizione: str, prezzo: int):
    await interaction.response.defer()
    
    id_f = ''.join(random.choices(string.ascii_letters + string.digits, k=10))
    data_attuale = datetime.datetime.now().strftime("%d/%m/%Y")
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # IMPORTANTE: Salviamo azienda.id (stringa) per matchare la tabella depositi
        cur.execute("""
            INSERT INTO fatture (id_fattura, id_cliente, id_azienda, descrizione, prezzo, data, stato) 
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (id_f, str(cliente.id), str(azienda.id), descrizione, prezzo, data_attuale, 'Pendente'))
        
        conn.commit()
        cur.close()
        conn.close()

        embed = discord.Embed(title="📑 Fattura Emessa", color=discord.Color.gold())
        embed.add_field(name="🏢 Azienda Emittente", value=azienda.mention, inline=True)
        embed.add_field(name="👤 Cliente", value=cliente.mention, inline=True)
        embed.add_field(name="💰 Importo", value=f"**{prezzo}$**", inline=True)
        embed.add_field(name="📝 Causale", value=descrizione, inline=False)
        embed.set_footer(text=f"ID Unico: {id_f}")
        
        await interaction.followup.send(embed=embed)

    except Exception as e:
        print(f"ERRORE SQL FATTURA: {e}")
        await interaction.followup.send("❌ Errore nel salvataggio della fattura.", ephemeral=True)

# ==========================================
# 3. COMANDO PER VISUALIZZARE FATTURE (/pagafattura)
# ==========================================
@bot.tree.command(name="pagafattura", description="Paga le tue fatture pendenti")
async def pagafattura(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        conn = get_db_connection()
        from psycopg2.extras import RealDictCursor
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM fatture WHERE id_cliente = %s AND stato = 'Pendente'", (str(interaction.user.id),))
        mie_fatture = cur.fetchall()
        cur.close()
        conn.close()

        if not mie_fatture:
            return await interaction.followup.send("✅ Non hai fatture in sospeso.", ephemeral=True)

        view = PagaFatturaView(interaction.user.id, mie_fatture)
        await interaction.followup.send("Seleziona la fattura da pagare:", view=view, ephemeral=True)
    except Exception as e:
        print(f"ERRORE CARICAMENTO: {e}")
        await interaction.followup.send("❌ Errore nel caricamento dei dati.", ephemeral=True)



ID_RUOLO_CONCESSIONARIO = 1253460178305679433

@bot.tree.command(name="registra_veicolo", description="Registra la vendita e salva i dati nel database motorizzazione")
@app_commands.checks.has_any_role(ID_RUOLO_CONCESSIONARIO)
async def registra_veicolo(
    interaction: discord.Interaction, 
    acquirente: discord.Member, 
    marca_modello: str, 
    targa: str, 
    concessionaria: discord.Role
):
    await interaction.response.defer()

    data_ora = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
    targa_maiuscola = targa.upper().replace(" ", "") # Puliamo la targa da spazi
    nome_item_chiavi = f"<:emoji_2:1464729413651534029> | Chiavi {marca_modello} [{targa_maiuscola}]"

    try:
        conn = get_db_connection()
        cur = conn.cursor()

        # 1. SALVATAGGIO NELLA MOTORIZZAZIONE (Tabella veicoli)
        # Usiamo ON CONFLICT così se la targa esiste già (es. auto usata rivenduta), aggiorna il proprietario
        cur.execute("""
            INSERT INTO veicoli (targa, modello, owner_id, data_vendita) 
            VALUES (%s, %s, %s, %s) 
            ON CONFLICT (targa) 
            DO UPDATE SET 
                owner_id = EXCLUDED.owner_id,
                modello = EXCLUDED.modello,
                data_vendita = EXCLUDED.data_vendita
        """, (targa_maiuscola, marca_modello, str(acquirente.id), data_ora))

        # 2. AGGIUNTA CHIAVI NELL'INVENTARIO (Tabella inventory)
        cur.execute("""
            INSERT INTO inventory (user_id, item_name, quantity) 
            VALUES (%s, %s, 1) 
            ON CONFLICT (user_id, item_name) 
            DO UPDATE SET quantity = inventory.quantity + 1
        """, (str(acquirente.id), nome_item_chiavi))
        
        conn.commit()
        cur.close()
        conn.close()

        # 3. Embed del Contratto
        embed = discord.Embed(title="📝 CONTRATTO DI VENDITA", color=discord.Color.green())
        embed.add_field(name="🏛️ CONCESSIONARIA", value=concessionaria.mention, inline=True)
        embed.add_field(name="👤 ACQUIRENTE", value=f"{acquirente.mention}\nID: `{acquirente.id}`", inline=True)
        embed.add_field(name="🚘 VEICOLO", value=f"**Modello:** {marca_modello}\n**Targa:** `{targa_maiuscola}`", inline=False)
        embed.set_footer(text=f"Registrato in Motorizzazione il {data_ora}")
        
        await interaction.followup.send(content=f"✅ Vendita completata! Veicolo registrato a nome di {acquirente.mention}.", embed=embed)

    except Exception as e:
        print(f"Errore registrazione veicolo: {e}")
        await interaction.followup.send("❌ Errore durante la registrazione nel database.", ephemeral=True)

# --- CLASSE PER IL MENU DI SCELTA TARGA ---
class TargaSelect(discord.ui.Select):
    def __init__(self, options, original_interaction):
        super().__init__(placeholder="Seleziona il veicolo corretto...", options=options)
        self.original_interaction = original_interaction

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        # Chiamiamo la funzione di visualizzazione usando la targa selezionata
        await mostra_risultato_targa(interaction, self.values[0], self.original_interaction)

class TargaView(discord.ui.View):
    def __init__(self, options, original_interaction):
        super().__init__(timeout=60)
        self.add_item(TargaSelect(options, original_interaction))

# --- COMANDO RICERCA TARGA ---
@bot.tree.command(name="ricerca_targa", description="Ricerca nel database motorizzazione (anche targa parziale)")
@app_commands.describe(targa="Inserisci la targa o parte di essa")
async def ricerca_targa(interaction: discord.Interaction, targa: str):
    if not any(role.id == POLIZIA_ROLE_ID for role in interaction.user.roles):
        return await interaction.response.send_message("❌ Accesso negato.", ephemeral=True)
    
    await interaction.response.defer()
    targa_query = f"%{targa.upper().replace(' ', '')}%"

    try:
        conn = get_db_connection()
        from psycopg2.extras import RealDictCursor
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        # Cerchiamo i veicoli che corrispondono alla targa parziale
        cur.execute("""
            SELECT targa, modello 
            FROM veicoli 
            WHERE targa ILIKE %s 
            LIMIT 25
        """, (targa_query,))
        
        results = cur.fetchall()
        cur.close()
        conn.close()

        if not results:
            return await interaction.followup.send(f"⚠️ Nessun veicolo trovato con targa simile a `{targa.upper()}`.")

        if len(results) == 1:
            # Risultato univoco
            return await mostra_risultato_targa(interaction, results[0]['targa'])
        
        # Più risultati: mostra il menu
        options = [
            discord.SelectOption(
                label=f"Targa: {r['targa']}", 
                description=f"Modello: {r['modello']}", 
                value=r['targa']
            ) for r in results
        ]
        
        view = TargaView(options, interaction)
        await interaction.followup.send(f"🔎 Ho trovato {len(results)} targhe simili. Scegli quella corretta:", view=view)

    except Exception as e:
        print(f"Errore ricerca_targa: {e}")
        await interaction.followup.send("❌ Errore nel database.")

# --- FUNZIONE HELPER PER MOSTRARE IL RISULTATO ---
async def mostra_risultato_targa(interaction, targa_exact, original_interaction=None):
    ctx = interaction if not original_interaction else original_interaction
    
    try:
        conn = get_db_connection()
        from psycopg2.extras import RealDictCursor
        cur = conn.cursor(cursor_factory=RealDictCursor)
        
        cur.execute("""
            SELECT v.*, d.nome, d.cognome 
            FROM veicoli v
            LEFT JOIN documenti d ON v.owner_id = d.user_id
            WHERE v.targa = %s
        """, (targa_exact,))
        
        res = cur.fetchone()
        cur.close()
        conn.close()

        if not res:
            return await ctx.followup.send("❌ Errore: veicolo scomparso dal database.")

        embed = discord.Embed(title="🔍 RISULTATO MOTORIZZAZIONE", color=discord.Color.blue())
        
        # Stato Sequestro (se presente nella tabella come visto nei messaggi precedenti)
        stato_veicolo = "✅ Regolare"
        if res.get('sequestrato'):
            stato_veicolo = "⚠️ SOTTO SEQUESTRO"
            embed.color = discord.Color.red()

        embed.add_field(name="🚘 Veicolo", value=f"**Modello:** {res['modello']}\n**Targa:** `{res['targa']}`\n**Stato:** {stato_veicolo}", inline=False)
        
        proprietario_nome = f"{res['nome']} {res['cognome']}" if res['nome'] else "Documento non registrato"
        embed.add_field(name="👤 Proprietario", value=f"**Nome:** {proprietario_nome}\n**Menzione:** <@{res['owner_id']}>", inline=False)
        
        if original_interaction:
            await interaction.followup.send(embed=embed)
        else:
            await ctx.followup.send(embed=embed)

    except Exception as e:
        print(f"Errore visualizzazione targa: {e}")



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
class ShopPaginationView(discord.ui.View):
    def __init__(self, items, interaction_user):
        super().__init__(timeout=120)
        self.items = items
        self.user = interaction_user
        self.current_page = 0
        self.items_per_page = 5
        self.create_buttons()

    def create_buttons(self):
        self.clear_items()
        start = self.current_page * self.items_per_page
        end = start + self.items_per_page
        current_items = self.items[start:end]

        for item in current_items:
            self.add_item(ShopBuyButton(item))

        if len(self.items) > self.items_per_page:
            prev_btn = discord.ui.Button(label="⬅️", style=discord.ButtonStyle.secondary, disabled=(self.current_page == 0))
            prev_btn.callback = self.prev_page
            self.add_item(prev_btn)

            next_btn = discord.ui.Button(label="➡️", style=discord.ButtonStyle.secondary, disabled=(end >= len(self.items)))
            next_btn.callback = self.next_page
            self.add_item(next_btn)

    def create_embed(self):
        start = self.current_page * self.items_per_page
        end = start + self.items_per_page
        page_items = self.items[start:end]
        total_pages = (len(self.items) - 1) // self.items_per_page + 1
        
        embed = discord.Embed(
            title="🛒 Catalogo Evren City",
            description=f"Pagina `{self.current_page + 1}/{total_pages}`\nUsa i bottoni verdi per acquistare.",
            color=0x2ECC71
        )
        
        for i in page_items:
            # Sincronizzato con colonna role_required
            role_id = i.get('role_required')
            req = f"\n🛡️ *Richiede: <@&{role_id}>*" if role_id and str(role_id).lower() != "none" else ""
            
            embed.add_field(
                name=f"📦 {i['name']}", 
                value=f"{i.get('description', 'Nessuna descrizione')}{req}\n━━━━━━━━━━━━━━", 
                inline=False
            )
        embed.set_footer(text="Evren City RP - Il tuo destino ti aspetta")
        return embed

    async def prev_page(self, interaction: discord.Interaction):
        if interaction.user.id != self.user.id: return await interaction.response.send_message("❌ Non puoi farlo.", ephemeral=True)
        self.current_page -= 1
        self.create_buttons()
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    async def next_page(self, interaction: discord.Interaction):
        if interaction.user.id != self.user.id: return await interaction.response.send_message("❌ Non puoi farlo.", ephemeral=True)
        self.current_page += 1
        self.create_buttons()
        await interaction.response.edit_message(embed=self.create_embed(), view=self)

class ShopBuyButton(discord.ui.Button):
    def __init__(self, item):
        self.item_nome = item['name']
        self.prezzo = item['price']
        self.ruolo_req = item.get('role_required')
        super().__init__(label=f"$ {self.prezzo} - {self.item_nome}", style=discord.ButtonStyle.success)

    async def callback(self, interaction: discord.Interaction):
        # Controllo Ruolo
        if self.ruolo_req and str(self.ruolo_req).lower() != "none":
            if not any(str(r.id) == str(self.ruolo_req) for r in interaction.user.roles):
                return await interaction.response.send_message(f"❌ Non hai il ruolo richiesto!", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        
        conn = None
        try:
            conn = get_db_connection()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            
            # Controllo Soldi su colonna 'bank'
            cur.execute("SELECT bank FROM users WHERE user_id = %s", (str(interaction.user.id),))
            res = cur.fetchone()

            if not res or res['bank'] < self.prezzo:
                return await interaction.followup.send("❌ Fondi insufficienti in Banca!", ephemeral=True)

            # Transazione
            cur.execute("UPDATE users SET bank = bank - %s WHERE user_id = %s", (self.prezzo, str(interaction.user.id)))
            cur.execute("""
                INSERT INTO inventory (user_id, item_name, quantity) 
                VALUES (%s, %s, 1)
                ON CONFLICT (user_id, item_name) 
                DO UPDATE SET quantity = inventory.quantity + 1
            """, (str(interaction.user.id), self.item_nome))
            
            conn.commit()
            await interaction.followup.send(f"✅ Acquisto completato: **{self.item_nome}**!", ephemeral=True)
            
        except Exception as e:
            await interaction.followup.send(f"⚠️ Errore: {e}", ephemeral=True)
        finally:
            if conn: cur.close(); conn.close()

@bot.tree.command(name="shop", description="Apri il catalogo")
async def shop(interaction: discord.Interaction):
    await interaction.response.defer()
    
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        # Sincronizzato con tabella items
        cur.execute("SELECT name, description, price, role_required FROM items ORDER BY price ASC")
        items = cur.fetchall()
        
        if not items:
            return await interaction.followup.send("🛒 Il catalogo è vuoto.")

        view = ShopPaginationView(items, interaction.user)
        await interaction.followup.send(embed=view.create_embed(), view=view)
        
    except Exception as e:
        await interaction.followup.send(f"❌ Errore: `{e}`")
    finally:
        if conn: cur.close(); conn.close()

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

# Funzione di supporto per pulire il codice (opzionale ma consigliata)
def is_staff(interaction: discord.Interaction):
    return any(role.id == RUOLO_STAFF_ID for role in interaction.user.roles)

# --- COMANDI SOLDI ---

@bot.tree.command(name="aggiungisoldi", description="STAFF - Regala soldi")
async def aggiungisoldi(interaction: Interaction, utente: discord.Member, importo: int):
    if not is_staff(interaction):
        return await interaction.response.send_message("❌ Permessi insufficienti.", ephemeral=True)
    
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("UPDATE users SET wallet = wallet + %s WHERE user_id = %s", (importo, str(utente.id)))
    conn.commit(); cur.close(); conn.close()
    await interaction.response.send_message(f"✅ Admin ha aggiunto **{importo}$** a {utente.mention}")

@bot.tree.command(name="rimuovisoldi", description="STAFF - Togli soldi")
async def rimuovisoldi(interaction: Interaction, utente: discord.Member, importo: int):
    if not is_staff(interaction):
        return await interaction.response.send_message("❌ Permessi insufficienti.", ephemeral=True)
    
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("UPDATE users SET wallet = GREATEST(0, wallet - %s) WHERE user_id = %s", (importo, str(utente.id)))
    conn.commit(); cur.close(); conn.close()
    await interaction.response.send_message(f"✅ Admin ha rimosso **{importo}$** a {utente.mention}")

# --- COMANDI ITEM ---

@bot.tree.command(name="aggiungi_item", description="STAFF - Regala item")
async def aggiungi_item(interaction: Interaction, utente: discord.Member, nome: str, quantita: int = 1):
    if not is_staff(interaction):
        return await interaction.response.send_message("❌ Permessi insufficienti.", ephemeral=True)
    
    await interaction.response.defer()
    nome_e = await cerca_item_smart(interaction, nome, "items")
    if not nome_e: return
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("INSERT INTO inventory (user_id, item_name, quantity) VALUES (%s, %s, %s) ON CONFLICT (user_id, item_name) DO UPDATE SET quantity = inventory.quantity + %s", (str(utente.id), nome_e, quantita, quantita))
    conn.commit(); cur.close(); conn.close()
    await interaction.followup.send(f"✅ Admin ha dato {quantita}x **{nome_e}** a {utente.mention}")

@bot.tree.command(name="rimuovi_item", description="STAFF - Togli item")
async def rimuovi_item(interaction: Interaction, utente: discord.Member, nome: str, quantita: int = 1):
    if not is_staff(interaction):
        return await interaction.response.send_message("❌ Permessi insufficienti.", ephemeral=True)
    
    await interaction.response.defer()
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("UPDATE inventory SET quantity = GREATEST(0, quantity - %s) WHERE user_id = %s AND item_name ILIKE %s", (quantita, str(utente.id), f"%{nome}%"))
    cur.execute("DELETE FROM inventory WHERE quantity <= 0")
    conn.commit(); cur.close(); conn.close()
    await interaction.followup.send(f"✅ Admin ha rimosso {quantita}x **{nome}** a {utente.mention}")

# --- GESTIONE SHOP ---

@bot.tree.command(name="crea_item_shop", description="STAFF - Crea item shop")
async def crea_item_shop(interaction: Interaction, nome: str, descrizione: str, prezzo: int, ruolo: discord.Role = None):
    if not is_staff(interaction):
        return await interaction.response.send_message("❌ Permessi insufficienti.", ephemeral=True)
    
    rid = str(ruolo.id) if ruolo else "None"
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("INSERT INTO items (name, description, price, role_required) VALUES (%s,%s,%s,%s) ON CONFLICT (name) DO UPDATE SET price=EXCLUDED.price, description=EXCLUDED.description, role_required=EXCLUDED.role_required", (nome, descrizione, prezzo, rid))
    conn.commit(); cur.close(); conn.close()
    await interaction.response.send_message(f"✅ Item **{nome}** creato/aggiornato nello shop.")

@bot.tree.command(name="elimina_item_shop", description="STAFF - Elimina definitivamente item dallo shop")
async def elimina_item_shop(interaction: Interaction, nome: str):
    if not is_staff(interaction):
        return await interaction.response.send_message("❌ Permessi insufficienti.", ephemeral=True)
    
    await interaction.response.defer()
    nome_e = await cerca_item_smart(interaction, nome, "items")
    if not nome_e: return
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("DELETE FROM items WHERE name = %s", (nome_e,))
    conn.commit(); cur.close(); conn.close()
    await interaction.followup.send(f"🗑️ L'item **{nome_e}** è stato rimosso dallo shop.")

# --- UTILITY ADMIN ---

@bot.tree.command(name="registra_fazione", description="STAFF - Registra ruolo fazione")
async def registra_fazione(interaction: Interaction, ruolo: discord.Role):
    if not is_staff(interaction):
        return await interaction.response.send_message("❌ Permessi insufficienti.", ephemeral=True)
    
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("INSERT INTO depositi (role_id, money) VALUES (%s, 0) ON CONFLICT DO NOTHING", (str(ruolo.id),))
    conn.commit(); cur.close(); conn.close()
    await interaction.response.send_message(f"✅ Fazione **{ruolo.name}** registrata nel sistema.")

@bot.tree.command(name="wipe_utente", description="STAFF - Reset totale utente")
async def wipe_utente(interaction: Interaction, utente: discord.Member):
    if not is_staff(interaction):
        return await interaction.response.send_message("❌ Permessi insufficienti.", ephemeral=True)
    
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("UPDATE users SET wallet = 500, bank = 0 WHERE user_id = %s", (str(utente.id),))
    cur.execute("DELETE FROM inventory WHERE user_id = %s", (str(utente.id),))
    conn.commit(); cur.close(); conn.close()
    await interaction.response.send_message(f"🧹 Reset totale per **{utente.name}**.")
import discord
from discord.ext import commands

# Decoratore per il controllo del ruolo Polizia
def is_polizia():
    async def predicate(ctx):
        # Verifica se l'utente ha il ruolo specifico
        return any(role.name == "POLIZIA_ROLE_ID" for role in ctx.author.roles)
    return commands.check(predicate)

class PoliziaCittadini(discord.ui.Select):
    def __init__(self, citizens, pool):
        options = [
            discord.SelectOption(label=f"{c['nome']} {c['cognome']}", description=f"ID: {c['user_id']}", value=c['user_id'])
            for c in citizens
        ]
        super().__init__(placeholder="Seleziona un cittadino da controllare...", options=options)
        self.pool = pool

    async def callback(self, interaction: discord.Interaction):
        user_id = self.values[0]
        
        async with self.pool.acquire() as conn:
            # Query per dossier completo
            doc = await conn.fetchrow("SELECT * FROM documenti WHERE user_id = $1", user_id)
            veicoli = await conn.fetch("SELECT modello, targa FROM veicoli WHERE owner_id = $1", user_id)
            multe = await conn.fetch("SELECT motivo, ammontare FROM multe WHERE user_id = $1 ORDER BY data DESC LIMIT 3", user_id)
            arresti = await conn.fetch("SELECT motivo, tempo FROM arresti WHERE user_id = $1 ORDER BY data DESC LIMIT 3", user_id)

        embed = discord.Embed(title=f"📁 Dossier: {doc['nome']} {doc['cognome']}", color=0x0047AB)
        embed.add_field(name="🧬 Info", value=f"**Genere:** {doc['genere']}\n**Altezza:** {doc['altezza']}cm\n**Nato il:** {doc['data_nascita']}", inline=True)
        
        v_list = "\n".join([f"🚘 {v['modello']} ({v['targa']})" for v in veicoli]) or "Nessun veicolo"
        embed.add_field(name="🚘 Veicoli", value=v_list, inline=False)

        m_list = "\n".join([f"📜 {m['motivo']} (${m['ammontare']})" for m in multe]) or "Nessuna multa"
        embed.add_field(name="📜 Ultime Multe", value=m_list, inline=True)

        a_list = "\n".join([f"⚖️ {a['motivo']} ({a['tempo']} min)" for a in arresti]) or "Fedina pulita"
        embed.add_field(name="⚖️ Precedenti", value=a_list, inline=True)

        await interaction.response.send_message(embed=embed, ephemeral=True)

class PoliziaView(discord.ui.View):
    def __init__(self, citizens, pool):
        super().__init__()
        self.add_item(PoliziaCittadini(citizens, pool))

@bot.command(name="centrale")
@is_polizia()
async def centrale(ctx):
    """Mostra la lista dei cittadini e permette il controllo dettagliato"""
    async with bot.db_pool.acquire() as conn:
        # Recuperiamo i primi 25 cittadini per il menu a tendina
        citizens = await conn.fetch("SELECT user_id, nome, cognome FROM documenti ORDER BY cognome ASC LIMIT 25")
        
    if not citizens:
        return await ctx.send("Nessun cittadino registrato nel database.")

    view = PoliziaView(citizens, bot.db_pool)
    await ctx.send("👮 **Database Centrale Polizia**: Seleziona un soggetto per il dossier.", view=view)


# ================= WEB SERVER & START =================
# Lista dei server autorizzati
# Lista dei server autorizzati
ALLOWED_GUILDS = [1383905374092005376, 1233353915559313478, 1392825183915610205]

# Funzione per sincronizzare i comandi all'avvio
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Sincronizzazione completata! Bot loggato come {bot.user}")

@bot.tree.interaction_check
async def check_guild(interaction: discord.Interaction):
    if interaction.guild_id not in ALLOWED_GUILDS:
        await interaction.response.send_message("❌ Questo bot non è autorizzato in questo server.", ephemeral=True)
        return False
    return True

app = Flask("")
@app.route("/")
def home(): return "Bot Online"
def run(): app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
threading.Thread(target=run).start()

bot.run(TOKEN)


