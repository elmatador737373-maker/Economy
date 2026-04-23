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
RUOLO_STAFF_ID = 1253460150141059198

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
    
# --- AUTOCOMPLETE PER NASCONDERE (Item nell'inventario) ---
async def item_inventario_autocomplete(interaction: discord.Interaction, current: str):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    # Cerca gli item che l'utente ha nell'inventario
    cur.execute("SELECT item_name FROM inventario WHERE user_id = %s AND item_name ILIKE %s", (str(interaction.user.id), f"%{current}%"))
    items = cur.fetchall()
    cur.close(); conn.close()
    return [app_commands.Choice(name=i['item_name'], value=i['item_name']) for i in items][:25]

# --- AUTOCOMPLETE PER RIPRENDERE (Item già nascosti) ---
async def item_nascosti_autocomplete(interaction: discord.Interaction, current: str):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    # Cerca solo tra gli item che l'utente ha nascosto
    cur.execute("SELECT item_name FROM item_nascosti WHERE user_id = %s AND item_name ILIKE %s", (str(interaction.user.id), f"%{current}%"))
    items = cur.fetchall()
    cur.close(); conn.close()
    return [app_commands.Choice(name=i['item_name'], value=i['item_name']) for i in items][:25]

# --- COMANDO NASCONDI ---
@bot.tree.command(name="nascondi", description="Nascondi un oggetto in un punto della mappa")
@app_commands.autocomplete(item=item_inventario_autocomplete)
async def nascondi(interaction: discord.Interaction, item: str, quantita: int, foto: discord.Attachment):
    if quantita <= 0: return await interaction.response.send_message("❌ Quantità non valida.", ephemeral=True)
    
    await interaction.response.defer(ephemeral=True)
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=RealDictCursor)
    
    # Verifica possesso item
    cur.execute("SELECT quantita FROM inventario WHERE user_id = %s AND item_name = %s", (str(interaction.user.id), item))
    inv = cur.fetchone()
    
    if not inv or inv['quantita'] < quantita:
        cur.close(); conn.close()
        return await interaction.followup.send("❌ Non hai abbastanza oggetti di questo tipo.")

    # Rimuovi dall'inventario e metti nel nascondiglio
    cur.execute("UPDATE inventario SET quantita = quantita - %s WHERE user_id = %s AND item_name = %s", (quantita, str(interaction.user.id), item))
    cur.execute("INSERT INTO item_nascosti (user_id, item_name, quantita, foto_nascosto) VALUES (%s, %s, %s, %s)", 
                (str(interaction.user.id), item, quantita, foto.url))
    
    conn.commit(); cur.close(); conn.close()
    
    embed = discord.Embed(title="📦 OGGETTO NASCOSTO", color=discord.Color.dark_grey())
    embed.add_field(name="Item", value=item, inline=True)
    embed.add_field(name="Quantità", value=quantita, inline=True)
    embed.set_image(url=foto.url)
    embed.set_footer(text="Usa /riprendi per recuperarlo fornendo la prova.")
    
    await interaction.followup.send("✅ Hai nascosto l'oggetto con successo!", embed=embed)

# --- COMANDO RIPRENDI ---
@bot.tree.command(name="riprendi", description="Recupera un oggetto che avevi nascosto")
@app_commands.autocomplete(item=item_nascosti_autocomplete)
async def riprendi(interaction: discord.Interaction, item: str, prova_posizione: discord.Attachment):
    await interaction.response.defer(ephemeral=True)
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=RealDictCursor)
    
    # Verifica che l'item sia effettivamente nascosto da quell'utente
    cur.execute("SELECT id, quantita, foto_nascosto FROM item_nascosti WHERE user_id = %s AND item_name = %s", (str(interaction.user.id), item))
    nascosto = cur.fetchone()
    
    if not nascosto:
        cur.close(); conn.close()
        return await interaction.followup.send("❌ Non hai nascosto nessun oggetto con questo nome.")

    quantita = nascosto['quantita']
    
    # Aggiungi all'inventario e rimuovi dai nascosti
    cur.execute("INSERT INTO inventario (user_id, item_name, quantita) VALUES (%s, %s, %s) ON CONFLICT (user_id, item_name) DO UPDATE SET quantita = inventario.quantita + EXCLUDED.quantita", 
                (str(interaction.user.id), item, quantita))
    cur.execute("DELETE FROM item_nascosti WHERE id = %s", (nascosto['id'],))
    
    conn.commit(); cur.close(); conn.close()
    
    # Log per lo staff (opzionale ma consigliato per evitare MG/Abuse)
    embed_log = discord.Embed(title="🔎 OGGETTO RECUPERATO", color=discord.Color.green())
    embed_log.add_field(name="Utente", value=interaction.user.mention)
    embed_log.add_field(name="Item", value=f"{quantita}x {item}")
    embed_log.add_field(name="Foto Originale", value=f"[Link]({nascosto['foto_nascosto']})")
    embed_log.set_image(url=prova_posizione.url)
    
    # Invia la conferma all'utente
    await interaction.followup.send(f"✅ Hai recuperato **{quantita}x {item}**! Inventario aggiornato.", embed=embed_log)
# --- COMANDO INSTAGRAM POST (FOTO & VIDEO) ---
@bot.tree.command(name="instagram", description="Crea un post in stile Instagram (Foto o Video)")
@app_commands.describe(
    titolo="Il titolo del post",
    descrizione="Il testo del post (facoltativo)",
    tag="Tag o Hashtag (facoltativo)",
    media="Allega la foto o il video del post"
)
async def instagram(
    interaction: discord.Interaction, 
    titolo: str, 
    media: discord.Attachment, 
    descrizione: str = None, 
    tag: str = None
):
    # Supportiamo immagini, gif e video
    formati_ammessi = ['image', 'video', 'gif']
    if not media.content_type or not any(x in media.content_type for x in formati_ammessi):
        return await interaction.response.send_message("❌ Puoi allegare solo Foto, GIF o Video!", ephemeral=True)

    await interaction.response.defer()

    # Creazione Embed
    embed = discord.Embed(
        title=f"📸 New Post from {interaction.user.display_name}",
        description=f"### {titolo}",
        color=discord.Color.from_rgb(225, 48, 108)
    )

    if descrizione:
        embed.description += f"\n\n{descrizione}"
    
    if tag:
        embed.add_field(name="📌 Tags", value=tag, inline=False)

    embed.set_footer(text="Instagram • Like to support")
    embed.timestamp = discord.utils.utcnow()

    # GESTIONE MEDIA
    is_video = 'video' in media.content_type or media.filename.endswith(('.mp4', '.mov', '.webm'))

    if is_video:
        # Se è un video, lo mandiamo come content per l'autoplay, l'embed sta sotto
        message = await interaction.followup.send(content=f"{media.url}", embed=embed)
    else:
        # Se è una foto/gif, la mettiamo dentro l'embed
        embed.set_image(url=media.url)
        message = await interaction.followup.send(embed=embed)
    
    # Aggiunta reazione
    await message.add_reaction("❤️")
# --- COMANDO PUBBLICO: 911 (TESTO LIBERO) ---
@bot.tree.command(name="911", description="Effettua una chiamata d'emergenza ai servizi cittadini")
@app_commands.choices(servizio=[
    app_commands.Choice(name="Police (LSPD)", value="police"),
    app_commands.Choice(name="Ambulance (EMS)", value="ambulance"),
    app_commands.Choice(name="Firefighter (VVF)", value="fire")
])
@app_commands.describe(
    servizio="Seleziona il dipartimento da contattare",
    nominativo="Il tuo Nome e Cognome IC",
    motivo="Descrivi brevemente l'emergenza (es: Sparatoria, Incidente)",
    posizione="Via o zona dell'evento",
    messaggio="Ulteriori dettagli per le unità in arrivo"
)
async def chiamata_911(
    interaction: discord.Interaction, 
    servizio: str, 
    nominativo: str, 
    motivo: str, 
    posizione: str, 
    messaggio: str = "Nessun dettaglio aggiuntivo"
):
    await interaction.response.defer(ephemeral=True)

    # Recupero configurazione dal DB
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT canale_id, ruolo_id FROM setup_911 WHERE servizio = %s", (servizio,))
    config = cur.fetchone()
    cur.close(); conn.close()

    if not config:
        return await interaction.followup.send("❌ Servizio non configurato dall'amministrazione.", ephemeral=True)

    canale_dest = interaction.guild.get_channel(int(config['canale_id']))
    ruolo_tag = interaction.guild.get_role(int(config['ruolo_id']))

    if not canale_dest:
        return await interaction.followup.send("❌ Canale di ricezione non trovato.", ephemeral=True)

    # Configurazione Estetica (Loghi e Colori)
    info_servizi = {
        "police": {"colore": discord.Color.blue(), "logo": "URL_LOGO_POLIZIA"},
        "ambulance": {"colore": discord.Color.red(), "logo": "URL_LOGO_EMS"},
        "fire": {"colore": discord.Color.orange(), "logo": "URL_LOGO_VVF"}
    }
    
    data = info_servizi.get(servizio)
    
    # Creazione Embed
    embed = discord.Embed(
        title=f"🚨 RICHIESTA DI INTERVENTO: {servizio.upper()}",
        color=data["colore"],
        timestamp=discord.utils.utcnow()
    )
    
    embed.set_thumbnail(url=data["logo"])
    embed.add_field(name="👤 Segnalante", value=f"**{nominativo}**", inline=True)
    embed.add_field(name="📍 Posizione", value=f"**{posizione}**", inline=True)
    embed.add_field(name="⚠️ Motivo Chiamata", value=f"**{motivo}**", inline=False)
    embed.add_field(name="💬 Info Extra", value=messaggio, inline=False)
    
    embed.set_footer(text="Centrale Operativa 911 • Dispatcher")

    # Invio
    tag_msg = ruolo_tag.mention if ruolo_tag else "@everyone"
    await canale_dest.send(content=f"🔔 **NOTIFICA EMERGENZA** {tag_msg}", embed=embed)

    await interaction.followup.send(f"✅ Chiamata inoltrata con successo a `{servizio.upper()}`.")
# --- FUNZIONE DI AUTOCOMPLETE PER I BOTTONI ---
async def bottoni_autocomplete(interaction: Interaction, current: str):
    # Recuperiamo l'ID del messaggio dal parametro già inserito nel comando (se presente)
    msg_id = interaction.namespace.id_messaggio
    if not msg_id:
        return []

    try:
        canale = interaction.channel
        messaggio = await canale.fetch_message(int(msg_id))
        
        choices = []
        if messaggio.components:
            for riga in messaggio.components:
                for comp in riga.children:
                    # Filtra i bottoni in base a ciò che l'utente sta scrivendo
                    if current.lower() in comp.label.lower():
                        choices.append(app_commands.Choice(name=comp.label, value=comp.label))
        return choices
    except:
        return []

# --- 4. COMANDO ELIMINA BOTTONE SINGOLO (Solo Admin) ---
@bot.tree.command(name="elimina_bottone", description="Scegli un bottone specifico da rimuovere")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.autocomplete(nome_bottone=bottoni_autocomplete)
async def elimina_bottone(interaction: Interaction, id_messaggio: str, nome_bottone: str):
    canale = interaction.channel
    messaggio = await canale.fetch_message(int(id_messaggio))
    
    if not messaggio.components:
        return await interaction.response.send_message("❌ Questo messaggio non ha bottoni.", ephemeral=True)

    nuova_view = View()
    trovato = False

    # Ricostruiamo la View escludendo il bottone selezionato
    for riga in messaggio.components:
        for comp in riga.children:
            if comp.label == nome_bottone:
                trovato = True
                continue  # Salta il bottone da eliminare
            
            nuova_view.add_item(Button(
                label=comp.label, 
                url=comp.url, 
                emoji=comp.emoji
            ))

    if trovato:
        # Se non rimangono bottoni, passiamo None, altrimenti la nuova view
        await messaggio.edit(view=nuova_view if len(nuova_view.children) > 0 else None)
        await interaction.response.send_message(f"✅ Bottone '{nome_bottone}' rimosso!", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ Bottone '{nome_bottone}' non trovato.", ephemeral=True)

# --- GESTIONE ERRORI ---
@elimina_bottone.error
async def elimina_error(interaction: Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("❌ Permessi insufficienti.", ephemeral=True)

# --- COMANDO ADMIN: SETUP 911 ---
@bot.tree.command(name="setup_911", description="[ADMIN] Configura i dettagli per i servizi d'emergenza")
@app_commands.choices(servizio=[
    app_commands.Choice(name="Police", value="police"),
    app_commands.Choice(name="Ambulance", value="ambulance"),
    app_commands.Choice(name="Firefighter", value="fire")
])
@app_commands.describe(
    servizio="Il dipartimento da configurare",
    canale="Il canale dove arriveranno le chiamate per questo servizio",
    ruolo="Il ruolo da taggare alla ricezione di una chiamata",
    logo_url="Link (URL) del logo della fazione (es. da Imgur)"
)
async def setup_911(
    interaction: discord.Interaction, 
    servizio: str, 
    canale: discord.TextChannel, 
    ruolo: discord.Role,
    logo_url: str
):
    # Controllo permessi amministratore
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ Non hai i permessi per configurare il sistema.", ephemeral=True)

    await interaction.response.defer(ephemeral=True)

    conn = get_db_connection()
    cur = conn.cursor()
    
    # Assicurati che la tabella abbia la colonna logo_url (esegui la query SQL se necessario)
    # ALTER TABLE setup_911 ADD COLUMN IF NOT EXISTS logo_url TEXT;
    
    cur.execute("""
        INSERT INTO setup_911 (servizio, canale_id, ruolo_id, logo_url) 
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (servizio) 
        DO UPDATE SET 
            canale_id = EXCLUDED.canale_id, 
            ruolo_id = EXCLUDED.ruolo_id,
            logo_url = EXCLUDED.logo_url
    """, (servizio, str(canale.id), str(ruolo.id), logo_url))
    
    conn.commit()
    cur.close()
    conn.close()

    embed = discord.Embed(title="⚙️ CONFIGURAZIONE 911 COMPLETATA", color=discord.Color.green())
    embed.add_field(name="Dipartimento", value=servizio.upper(), inline=False)
    embed.add_field(name="Canale", value=canale.mention, inline=True)
    embed.add_field(name="Ruolo", value=ruolo.mention, inline=True)
    embed.set_thumbnail(url=logo_url)
    
    await interaction.followup.send(embed=embed)

# --- 1. COMANDO CREA ---
@bot.tree.command(name="crea", description="Invia l'embed base con immagine")
@discord.app_commands.checks.has_permissions(administrator=True)
async def crea(interaction: discord.Interaction, testo: str, url_immagine: str):
    embed = discord.Embed(description=testo, color=0x2b2d31)
    embed.set_image(url=url_immagine)
    await interaction.response.send_message(embed=embed)
    
    
    
# --- HELPER: RECUPERO MEDIA DAL DB ---
def get_media(tipo):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT media_url FROM media_stati WHERE tipo_stato = %s", (tipo,))
    res = cur.fetchone()
    cur.close(); conn.close()
    return res['media_url'] if res else None

# --- HELPER: CONTROLLO PERMESSI RUOLO ---
async def check_stato_permission(interaction: Interaction, tipo):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT role_id FROM permessi_stati WHERE tipo_stato = %s", (tipo,))
    res = cur.fetchone()
    cur.close(); conn.close()
    if not res: return False
    return any(role.id == int(res['role_id']) for role in interaction.user.roles)

# --- COMANDI ADMIN CONFIGURAZIONE ---

@bot.tree.command(name="set_permessi_stato", description="[ADMIN] Imposta quale ruolo può usare i comandi stato")
@app_commands.choices(tipo=[
    app_commands.Choice(name="Whitelist", value="whitelist"),
    app_commands.Choice(name="Assistenza", value="assistenza"),
    app_commands.Choice(name="Bandi", value="bandi")
])
async def set_permessi_stato(interaction: Interaction, tipo: str, ruolo: discord.Role):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ Solo un admin può farlo.", ephemeral=True)
    
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("""
        INSERT INTO media_stati (tipo_stato, media_url) VALUES ('dummy', 'dummy') 
        ON CONFLICT DO NOTHING; -- Assicura che la tabella esista
    """) # Nota: Assicurati di aver creato le tabelle manualmente via SQL come indicato prima
    
    cur.execute("""
        INSERT INTO permessi_stati (tipo_stato, role_id) VALUES (%s, %s)
        ON CONFLICT (tipo_stato) DO UPDATE SET role_id = EXCLUDED.role_id
    """, (tipo, str(ruolo.id)))
    conn.commit(); cur.close(); conn.close()
    await interaction.response.send_message(f"✅ Permessi `{tipo}` impostati per: {ruolo.mention}", ephemeral=True)

@bot.tree.command(name="set_media_stato", description="[ADMIN] Carica la GIF/Media per uno stato")
@app_commands.choices(tipo=[
    app_commands.Choice(name="Whitelist Online", value="whitelist_on"),
    app_commands.Choice(name="Whitelist Offline", value="whitelist_off"),
    app_commands.Choice(name="Assistenza Online", value="assistenza_on"),
    app_commands.Choice(name="Assistenza Offline", value="assistenza_off"),
    app_commands.Choice(name="Bandi Aperti", value="bandi_on"),
    app_commands.Choice(name="Bandi Chiusi", value="bandi_off")
])
async def set_media_stato(interaction: Interaction, tipo: str, file: discord.Attachment):
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ Solo un admin può farlo.", ephemeral=True)
    
    await interaction.response.defer(ephemeral=True)

    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("""
        INSERT INTO media_stati (tipo_stato, media_url) VALUES (%s, %s)
        ON CONFLICT (tipo_stato) DO UPDATE SET media_url = EXCLUDED.media_url
    """, (tipo, file.url))
    conn.commit(); cur.close(); conn.close()
    
    await interaction.followup.send(f"✅ Media per `{tipo}` salvato correttamente!")

# --- COMANDI STATO (UTILIZZABILI DAI RUOLI CONFIGURATI) ---

async def invia_embed_stato(interaction, tipo_chiave, titolo, descrizione, colore):
    # Controllo permessi
    if not await check_stato_permission(interaction, tipo_chiave.split('_')[0]):
        return await interaction.response.send_message("❌ Non hai il ruolo autorizzato.", ephemeral=True)

    await interaction.response.defer()

    url_media = get_media(tipo_chiave)
    if not url_media:
        return await interaction.followup.send(f"❌ Nessun media impostato. Usa `/set_media_stato`.")

    embed = discord.Embed(title=titolo, description=descrizione, color=colore, timestamp=discord.utils.utcnow())
    embed.set_image(url=url_media)
    await interaction.followup.send(embed=embed)

@bot.tree.command(name="stato_whitelist", description="Cambia stato Whitelist")
@app_commands.choices(stato=[app_commands.Choice(name="Online", value="on"), app_commands.Choice(name="Offline", value="off")])
async def stato_whitelist(interaction: Interaction, stato: str):
    if stato == "on":
        await invia_embed_stato(interaction, "whitelist_on", "🟢 WHITELIST ONLINE", "Le Whitelist sono ora **APERTE**!", discord.Color.green())
    else:
        await invia_embed_stato(interaction, "whitelist_off", "🔴 WHITELIST OFFLINE", "Le Whitelist sono ora **CHIUSE**.", discord.Color.red())

@bot.tree.command(name="stato_assistenza", description="Cambia stato Assistenza")
@app_commands.choices(stato=[app_commands.Choice(name="Online", value="on"), app_commands.Choice(name="Offline", value="off")])
async def stato_assistenza(interaction: Interaction, stato: str):
    if stato == "on":
        await invia_embed_stato(interaction, "assistenza_on", "🛠️ ASSISTENZA ATTIVA", "Lo staff è disponibile nei vocali!", discord.Color.blue())
    else:
        await invia_embed_stato(interaction, "assistenza_off", "💤 ASSISTENZA CHIUSA", "Al momento l'assistenza è chiusa.", discord.Color.dark_grey())

@bot.tree.command(name="stato_bandi", description="Cambia stato Bandi")
@app_commands.choices(stato=[app_commands.Choice(name="Aperti", value="on"), app_commands.Choice(name="Chiusi", value="off")])
async def stato_bandi(interaction: Interaction, stato: str):
    if stato == "on":
        await invia_embed_stato(interaction, "bandi_on", "📝 BANDI APERTI", "Inviate la vostra candidatura!", discord.Color.gold())
    else:
        await invia_embed_stato(interaction, "bandi_off", "🚫 BANDI CHIUSI", "Le candidature sono terminate.", discord.Color.dark_red())

    
# --- 1. SETUP ADMIN PER I RUOLI LAVORATORI ---
@bot.tree.command(name="setup_documenti", description="[ADMIN] Imposta i ruoli che possono usare i comandi documenti")
@app_commands.checks.has_permissions(administrator=True)
async def setup_documenti(interaction: discord.Interaction, 
                           ruolo_patenti: discord.Role, 
                           ruolo_medico: discord.Role, 
                           ruolo_porto_armi: discord.Role, 
                           ruolo_registrazione_armi: discord.Role):
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("""
        INSERT INTO docs_config (guild_id, role_id_patenti, role_id_medico, role_id_porto_armi, role_id_registro_armi) 
        VALUES (%s, %s, %s, %s, %s) ON CONFLICT (guild_id) DO UPDATE SET 
        role_id_patenti=EXCLUDED.role_id_patenti, role_id_medico=EXCLUDED.role_id_medico, 
        role_id_porto_armi=EXCLUDED.role_id_porto_armi, role_id_registro_armi=EXCLUDED.role_id_registro_armi
    """, (str(interaction.guild.id), str(ruolo_patenti.id), str(ruolo_medico.id), str(ruolo_porto_armi.id), str(ruolo_registrazione_armi.id)))
    conn.commit(); cur.close(); conn.close()
    await interaction.response.send_message("✅ Ruoli lavoratori configurati con successo!", ephemeral=True)

# --- 2. LOGICA DI REGISTRAZIONE ---
async def execute_doc_registration(interaction, cittadino, titolo, dettagli, costo, motivo, config_key, colore, emoji):
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM docs_config WHERE guild_id = %s", (str(interaction.guild.id),))
    config = cur.fetchone(); cur.close(); conn.close()

    if not config or int(config[config_key]) not in [r.id for r in interaction.user.roles]:
        return await interaction.response.send_message(f"❌ Non hai il ruolo autorizzato per registrare questo documento.", ephemeral=True)

    embed = discord.Embed(
        title=f"{emoji} {titolo}",
        description=f"Documentazione ufficiale registrata per il cittadino {cittadino.mention}.",
        color=colore,
        timestamp=discord.utils.utcnow()
    )
    embed.add_field(name="👤 Soggetto", value=cittadino.mention, inline=True)
    embed.add_field(name="👔 Operatore", value=interaction.user.mention, inline=True)
    embed.add_field(name="💰 Costo", value=f"**{costo}**", inline=True)
    embed.add_field(name="📋 Info", value=dettagli, inline=False)
    embed.add_field(name="📝 Motivo", value=motivo, inline=False)
    
    embed.set_thumbnail(url=cittadino.display_avatar.url)
    embed.set_footer(text=f"Sistema Documentale Evren City")

    # Il bot risponde pubblicamente nel canale menzionando l'utente
    await interaction.response.send_message(content=f"📑 Registrazione completata per {cittadino.mention}", embed=embed)

# --- 3. COMANDI LAVORATORI ---
@bot.tree.command(name="give_money", description="[STAFF] Accredita soldi a un cittadino")
@app_commands.choices(tipo=[
    app_commands.Choice(name="Contanti", value="wallet"),
    app_commands.Choice(name="Banca", value="bank")
])
async def give_money(interaction: Interaction, utente: discord.Member, importo: int, tipo: str):
    # Controllo Ruolo Staff
    if not any(role.id == RUOLO_STAFF_ID for role in interaction.user.roles):
        return await interaction.response.send_message("❌ Permessi insufficienti: non sei un membro dello Staff.", ephemeral=True)
    
    if importo <= 0:
        return await interaction.response.send_message("❌ Inserisci un importo superiore a 0.", ephemeral=True)

    # Aggiornamento Database
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(f"UPDATE users SET {tipo} = {tipo} + %s WHERE user_id = %s", (importo, str(utente.id)))
    conn.commit()
    cur.close()
    conn.close()
    
    await interaction.response.send_message(f"✅ Accreditati **{importo}$** in **{tipo}** a {utente.mention}.")
    
    # Log Finanziario
    emb = discord.Embed(title="🎁 ACCREDITO STAFF", color=discord.Color.purple(), timestamp=discord.utils.utcnow())
    emb.add_field(name="Staffer", value=interaction.user.mention)
    emb.add_field(name="Ricevente", value=utente.mention)
    emb.add_field(name="Importo", value=f"{importo}$ ({tipo})")
    await invia_log_finanziario(interaction.guild, emb)


@bot.tree.command(name="remove_money", description="[STAFF] Rimuovi soldi a un cittadino")
@app_commands.choices(tipo=[
    app_commands.Choice(name="Contanti", value="wallet"),
    app_commands.Choice(name="Banca", value="bank")
])
async def remove_money(interaction: Interaction, utente: discord.Member, importo: int, tipo: str):
    # Controllo Ruolo Staff
    if not any(role.id == RUOLO_STAFF_ID for role in interaction.user.roles):
        return await interaction.response.send_message("❌ Permessi insufficienti: non sei un membro dello Staff.", ephemeral=True)
    
    if importo <= 0:
        return await interaction.response.send_message("❌ Inserisci un importo superiore a 0.", ephemeral=True)

    # Aggiornamento Database
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(f"UPDATE users SET {tipo} = {tipo} - %s WHERE user_id = %s", (importo, str(utente.id)))
    conn.commit()
    cur.close()
    conn.close()
    
    await interaction.response.send_message(f"⚠️ Rimossi **{importo}$** dai **{tipo}** di {utente.mention}.")
    
    # Log Finanziario
    emb = discord.Embed(title="🚫 RIMOZIONE STAFF", color=discord.Color.dark_grey(), timestamp=discord.utils.utcnow())
    emb.add_field(name="Staffer", value=interaction.user.mention)
    emb.add_field(name="Soggetto", value=utente.mention)
    emb.add_field(name="Importo", value=f"{importo}$ ({tipo})")
    await invia_log_finanziario(interaction.guild, emb)

@bot.tree.command(name="patente", description="Registra una patente a un cittadino")
async def patente(interaction: discord.Interaction, cittadino: discord.Member, tipo: str, costo: str, motivo: str):
    await execute_doc_registration(interaction, cittadino, "Patente di Guida", 
                                  f"**Categoria:** {tipo}", costo, motivo, 
                                  'role_id_patenti', discord.Color.blue(), "🪪")

@bot.tree.command(name="certificato", description="Rilascia certificato medico a un cittadino")
async def certificato(interaction: discord.Interaction, cittadino: discord.Member, esito: str, costo: str, motivo: str):
    await execute_doc_registration(interaction, cittadino, "Certificato Medico", 
                                  f"**Esito:** {esito}", costo, motivo, 
                                  'role_id_medico', discord.Color.red(), "⚕️")

@bot.tree.command(name="porto_darmi", description="Registra licenza porto d'armi")
async def porto_darmi(interaction: discord.Interaction, cittadino: discord.Member, tipo_licenza: str, costo: str, motivo: str):
    await execute_doc_registration(interaction, cittadino, "Porto d'Armi", 
                                  f"**Licenza:** {tipo_licenza}", costo, motivo, 
                                  'role_id_porto_armi', discord.Color.dark_grey(), "🔫")

@bot.tree.command(name="registra_arma", description="Registra matricola arma a un cittadino")
async def registra_arma(interaction: discord.Interaction, cittadino: discord.Member, modello: str, matricola: str, costo: str, motivo: str):
    await execute_doc_registration(interaction, cittadino, "Registrazione Arma", 
                                  f"**Modello:** {modello}\n**Matricola:** `{matricola}`", 
                                  costo, motivo, 'role_id_registro_armi', discord.Color.dark_red(), "⚙️")

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

import discord
from discord import app_commands, Interaction

# --- MODAL PER LA MODIFICA DELL'IMPORTO ---
class ModificaBottinoModal(discord.ui.Modal, title="Modifica Bottino Rapina"):
    nuovo_importo = discord.ui.TextInput(label="Nuovo Ammontare (€)", placeholder="Inserisci la cifra...", required=True)
    
    def __init__(self, user_id, luogo, msg_utente_id, canale_utente_id):
        super().__init__()
        self.user_id = user_id
        self.luogo = luogo
        self.msg_utente_id = msg_utente_id
        self.canale_utente_id = canale_utente_id

    async def on_submit(self, interaction: discord.Interaction):
        try:
            valore = int(self.nuovo_importo.value)
            
            # Aggiornamento Database
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("UPDATE users SET wallet = wallet + %s WHERE user_id = %s", (valore, str(self.user_id)))
            conn.commit()
            cur.close(); conn.close()
            
            # 1. Aggiorna Embed Utente nel canale rapina
            await self.aggiorna_messaggio_utente(interaction, valore, "⚠️ **BOTTINO MODIFICATO**", discord.Color.orange())
            
            # 2. Invia DM all'utente
            await self.invia_dm_esito(interaction, f"⚠️ Lo staff ha modificato e approvato il tuo bottino per la rapina a **{self.luogo}**. Ricevuti: **{valore}€**")

            await interaction.response.edit_message(content=f"✍️ **BOTTINO MODIFICATO**: Accreditati **{valore}€** a <@{self.user_id}>.", embed=None, view=None)
        except ValueError:
            await interaction.response.send_message("❌ Inserisci un numero valido!", ephemeral=True)

    async def aggiorna_messaggio_utente(self, interaction, valore, esito_testo, colore):
        try:
            canale = interaction.guild.get_channel(self.canale_utente_id)
            msg = await canale.fetch_message(self.msg_utente_id)
            embed = msg.embeds[0]
            embed.color = colore
            embed.set_field_at(0, name="Stato", value=esito_testo)
            embed.add_field(name="Importo Finale", value=f"**{valore}€**", inline=False)
            await msg.edit(embed=embed)
        except: pass

    async def invia_dm_esito(self, interaction, testo):
        try:
            user = await interaction.guild.fetch_member(int(self.user_id))
            if user: await user.send(testo)
        except: pass


# --- VIEW PER LO STAFF ---
class RapinaStaffView(discord.ui.View):
    def __init__(self, user_id, ammontare, luogo, msg_utente_id, canale_utente_id):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.ammontare = ammontare
        self.luogo = luogo
        self.msg_utente_id = msg_utente_id
        self.canale_utente_id = canale_utente_id

    async def aggiorna_originale(self, interaction, esito, colore, finale=None):
        """Helper per aggiornare l'embed che vede il cittadino"""
        try:
            canale = interaction.guild.get_channel(self.canale_utente_id)
            msg = await canale.fetch_message(self.msg_utente_id)
            embed = msg.embeds[0]
            embed.color = colore
            embed.set_field_at(0, name="Stato", value=esito)
            if finale:
                embed.add_field(name="Importo Ricevuto", value=f"**{finale}€**", inline=False)
            await msg.edit(embed=embed)
        except: pass

    async def notificami(self, interaction, testo):
        """Helper per inviare il DM"""
        try:
            user = await interaction.guild.fetch_member(int(self.user_id))
            if user: await user.send(testo)
        except: pass

    @discord.ui.button(label="Conferma", style=discord.ButtonStyle.success)
    async def conferma(self, interaction: discord.Interaction, button: discord.ui.Button):
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("UPDATE users SET wallet = wallet + %s WHERE user_id = %s", (self.ammontare, str(self.user_id)))
        conn.commit()
        cur.close(); conn.close()
        
        await self.aggiorna_originale(interaction, "✅ **BOTTINO APPROVATO**", discord.Color.green(), self.ammontare)
        await self.notificami(interaction, f"✅ Il tuo bottino per la rapina a **{self.luogo}** è stato approvato! Ricevuti: **{self.ammontare}€**")

        await interaction.response.edit_message(content=f"✅ **APPROVATA**: {self.ammontare}€ a <@{self.user_id}>.", embed=None, view=None)

    @discord.ui.button(label="Annulla", style=discord.ButtonStyle.danger)
    async def annulla(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.aggiorna_originale(interaction, "❌ **RAPINA ANNULLATA**", discord.Color.red())
        await self.notificami(interaction, f"❌ La tua rapina a **{self.luogo}** è stata annullata dallo staff.")

        await interaction.response.edit_message(content=f"❌ **RIFIUTATA**: Colpo di <@{self.user_id}> invalidato.", embed=None, view=None)

    @discord.ui.button(label="Modifica Importo", style=discord.ButtonStyle.secondary)
    async def modifica(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Passiamo tutti i dati necessari al Modal
        await interaction.response.send_modal(ModificaBottinoModal(self.user_id, self.luogo, self.msg_utente_id, self.canale_utente_id))


# --- ESEMPIO DI INVIO NEL COMANDO RAPINA ---
# Quando invii il messaggio all'utente nel comando:
# embed.add_field(name="Stato", value="⌛ In attesa di approvazione staff...")
# msg_utente = await interaction.followup.send(embed=embed)
# 
# view_staff = RapinaStaffView(
#     user_id=str(interaction.user.id),
#     ammontare=paga_casuale,
#     luogo=luogo,
#     msg_utente_id=msg_utente.id,
#     canale_utente_id=interaction.channel.id
# )
# await canale_staff.send(embed=embed_staff, view=view_staff)

# --- COMANDO SETTAGGIO CANALE (SOLO ADMIN) ---
# --- SISTEMA ECONOMICO UNIFICATO CON LOGGING ---

# Funzione Helper per inviare i log finanziari nel canale settato
async def invia_log_finanziario(guild, embed):
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT setting_value FROM server_settings WHERE setting_name = 'log_finanze'")
        res = cur.fetchone()
        cur.close(); conn.close()
        if res:
            canale = guild.get_channel(int(res['setting_value']))
            if canale: await canale.send(embed=embed)
    except Exception as e:
        print(f"Errore log finanziario: {e}")

# --- COMANDI AMMINISTRATIVI ---

@bot.tree.command(name="set_log_finanze", description="[ADMIN] Imposta il canale per i log economici del server")
@app_commands.checks.has_permissions(administrator=True)
async def set_log_finanze(interaction: Interaction, canale: discord.TextChannel):
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("""
        INSERT INTO server_settings (setting_name, setting_value) 
        VALUES ('log_finanze', %s) 
        ON CONFLICT (setting_name) DO UPDATE SET setting_value = EXCLUDED.setting_value
    """, (str(canale.id),))
    conn.commit(); cur.close(); conn.close()
    await interaction.response.send_message(f"✅ Canale log finanziari impostato su {canale.mention}", ephemeral=True)

# --- ECONOMIA PERSONALE (PORTAFOGLIO E BANCA) ---

@bot.tree.command(name="deposita", description="Sposta i tuoi contanti in banca")
async def deposita(interaction: Interaction, importo: int):
    u = get_user_data(interaction.user.id)
    if importo <= 0 or u['wallet'] < importo:
        return await interaction.response.send_message("❌ Importo non valido o contanti insufficienti.")
    
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("UPDATE users SET wallet = wallet - %s, bank = bank + %s WHERE user_id = %s", (importo, importo, str(interaction.user.id)))
    conn.commit(); cur.close(); conn.close()
    
    await interaction.response.send_message(f"🏦 **{interaction.user.display_name}** ha depositato **{importo}$** in banca.")
    
    emb = discord.Embed(title="📥 LOG DEPOSITO PERSONALE", color=discord.Color.light_grey(), timestamp=discord.utils.utcnow())
    emb.add_field(name="Utente", value=interaction.user.mention); emb.add_field(name="Importo", value=f"{importo}$")
    await invia_log_finanziario(interaction.guild, emb)

@bot.tree.command(name="preleva", description="Preleva soldi dal tuo conto bancario")
async def preleva(interaction: Interaction, importo: int):
    u = get_user_data(interaction.user.id)
    if importo <= 0 or u['bank'] < importo:
        return await interaction.response.send_message("❌ Importo non valido o fondi bancari insufficienti.")
    
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("UPDATE users SET bank = bank - %s, wallet = wallet + %s WHERE user_id = %s", (importo, importo, str(interaction.user.id)))
    conn.commit(); cur.close(); conn.close()
    
    await interaction.response.send_message(f"💸 **{interaction.user.display_name}** ha prelevato **{importo}$**.")
    
    emb = discord.Embed(title="📤 LOG PRELIEVO PERSONALE", color=discord.Color.orange(), timestamp=discord.utils.utcnow())
    emb.add_field(name="Utente", value=interaction.user.mention); emb.add_field(name="Importo", value=f"{importo}$")
    await invia_log_finanziario(interaction.guild, emb)

@bot.tree.command(name="paga", description="Consegna contanti a un altro cittadino (mano a mano)")
async def paga(interaction: Interaction, utente: discord.Member, importo: int):
    if utente.id == interaction.user.id: return await interaction.response.send_message("❌ Non puoi pagare te stesso.")
    u = get_user_data(interaction.user.id)
    if importo <= 0 or u['wallet'] < importo: return await interaction.response.send_message("❌ Non hai abbastanza contanti.")
    
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("UPDATE users SET wallet = wallet - %s WHERE user_id = %s", (importo, str(interaction.user.id)))
    cur.execute("UPDATE users SET wallet = wallet + %s WHERE user_id = %s", (importo, str(utente.id)))
    conn.commit(); cur.close(); conn.close()
    
    await interaction.response.send_message(f"🤝 **{interaction.user.display_name}** ha consegnato **{importo}$** a **{utente.mention}**.")
    
    emb = discord.Embed(title="💵 LOG SCAMBIO CONTANTI", color=discord.Color.green(), timestamp=discord.utils.utcnow())
    emb.add_field(name="Mittente", value=interaction.user.mention); emb.add_field(name="Destinatario", value=utente.mention); emb.add_field(name="Importo", value=f"{importo}$")
    await invia_log_finanziario(interaction.guild, emb)

@bot.tree.command(name="bonifico", description="Invia un bonifico bancario a un altro cittadino")
async def bonifico(interaction: Interaction, utente: discord.Member, importo: int):
    if utente.id == interaction.user.id: return await interaction.response.send_message("❌ Non puoi fare un bonifico a te stesso.")
    u = get_user_data(interaction.user.id)
    if importo <= 0 or u['bank'] < importo: return await interaction.response.send_message("❌ Fondi bancari insufficienti per il bonifico.")
    
    conn = get_db_connection(); cur = conn.cursor()
    cur.execute("UPDATE users SET bank = bank - %s WHERE user_id = %s", (importo, str(interaction.user.id)))
    cur.execute("UPDATE users SET bank = bank + %s WHERE user_id = %s", (importo, str(utente.id)))
    conn.commit(); cur.close(); conn.close()
    
    await interaction.response.send_message(f"🏛️ Bonifico bancario di **{importo}$** inviato con successo a **{utente.display_name}**.")
    
    emb = discord.Embed(title="🏛️ LOG BONIFICO BANCARIO", color=discord.Color.blue(), timestamp=discord.utils.utcnow())
    emb.add_field(name="Mittente", value=interaction.user.mention); emb.add_field(name="Destinatario", value=utente.mention); emb.add_field(name="Importo", value=f"{importo}$")
    await invia_log_finanziario(interaction.guild, emb)

# --- ECONOMIA FAZIONI E AZIENDE ---

@bot.tree.command(name="deposita_soldi_fazione", description="Deposita contanti nel fondo della fazione")
async def deposita_soldi_fazione(interaction: Interaction, importo: int):
    await interaction.response.defer()
    miei_ruoli = await get_miei_ruoli_fazione(interaction)
    if not miei_ruoli: return await interaction.followup.send("❌ Non fai parte di nessuna fazione autorizzata.")
    u = get_user_data(interaction.user.id)
    if importo <= 0 or u['wallet'] < importo: return await interaction.followup.send("❌ Non hai abbastanza contanti nel portafoglio.")

    async def procedi(inter, rid):
        conn = get_db_connection(); cur = conn.cursor()
        cur.execute("UPDATE users SET wallet = wallet - %s WHERE user_id = %s", (importo, str(inter.user.id)))
        cur.execute("UPDATE depositi SET money = money + %s WHERE role_id = %s", (importo, rid))
        conn.commit(); cur.close(); conn.close()
        r_obj = inter.guild.get_role(int(rid))
        await inter.followup.send(f"✅ Hai depositato **{importo}$** nel fondo di: **{r_obj.name}**.")
        
        emb = discord.Embed(title="🏢 LOG DEPOSITO FAZIONE", color=discord.Color.dark_green(), timestamp=discord.utils.utcnow())
        emb.add_field(name="Utente", value=inter.user.mention); emb.add_field(name="Fazione", value=r_obj.name); emb.add_field(name="Importo", value=f"{importo}$")
        await invia_log_finanziario(inter.guild, emb)

    if len(miei_ruoli) == 1: await procedi(interaction, str(miei_ruoli[0].id))
    else:
        view = discord.ui.View()
        sel = discord.ui.Select(options=[discord.SelectOption(label=r.name, value=str(r.id)) for r in miei_ruoli])
        async def call(i): await i.response.defer(); await procedi(i, sel.values[0])
        sel.callback = call; view.add_item(sel)
        await interaction.followup.send("In quale fazione desideri depositare?", view=view, ephemeral=True)

@bot.tree.command(name="preleva_soldi_fazione", description="Preleva soldi dal fondo della fazione")
async def preleva_soldi_fazione(interaction: Interaction, importo: int):
    await interaction.response.defer()
    miei_ruoli = await get_miei_ruoli_fazione(interaction)
    if not miei_ruoli: return await interaction.followup.send("❌ Non hai i permessi fazione necessari.")

    async def procedi(inter, rid):
        conn = get_db_connection(); cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT money FROM depositi WHERE role_id = %s", (rid,))
        res = cur.fetchone()
        if not res or res['money'] < importo: return await inter.followup.send("❌ Il fondo fazione non dispone di tale cifra.")
        cur.execute("UPDATE depositi SET money = money - %s WHERE role_id = %s", (importo, rid))
        cur.execute("UPDATE users SET wallet = wallet + %s WHERE user_id = %s", (importo, str(inter.user.id)))
        conn.commit(); cur.close(); conn.close()
        r_obj = inter.guild.get_role(int(rid))
        await inter.followup.send(f"💸 Hai prelevato **{importo}$** dal fondo di: **{r_obj.name}**.")
        
        emb = discord.Embed(title="🏢 LOG PRELIEVO FAZIONE", color=discord.Color.dark_red(), timestamp=discord.utils.utcnow())
        emb.add_field(name="Utente", value=inter.user.mention); emb.add_field(name="Fazione", value=r_obj.name); emb.add_field(name="Importo", value=f"{importo}$")
        await invia_log_finanziario(inter.guild, emb)

    if len(miei_ruoli) == 1: await procedi(interaction, str(miei_ruoli[0].id))
    else:
        view = discord.ui.View()
        sel = discord.ui.Select(options=[discord.SelectOption(label=r.name, value=str(r.id)) for r in miei_ruoli])
        async def call(i): await i.response.defer(); await procedi(i, sel.values[0])
        sel.callback = call; view.add_item(sel)
        await interaction.followup.send("Da quale fazione desideri prelevare?", view=view, ephemeral=True)

# --- PAGAMENTO SANZIONI E FATTURE ---

@bot.tree.command(name="pagamulta", description="Saldare l'ultima multa pendente")
async def pagamulta(interaction: Interaction):
    await interaction.response.defer(ephemeral=True)
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM multe WHERE user_id = %s LIMIT 1", (str(interaction.user.id),))
    m = cur.fetchone()
    if not m: return await interaction.followup.send("✅ Non risultano multe pendenti a tuo carico.")
    
    cur.execute("SELECT wallet FROM users WHERE user_id = %s", (str(interaction.user.id),))
    w = cur.fetchone()
    if not w or w['wallet'] < m['ammontare']: return await interaction.followup.send(f"❌ Contanti insufficienti. La multa è di {m['ammontare']}$.")

    cur.execute("UPDATE users SET wallet = wallet - %s WHERE user_id = %s", (m['ammontare'], str(interaction.user.id)))
    cur.execute("INSERT INTO depositi (role_id, money) VALUES (%s, %s) ON CONFLICT (role_id) DO UPDATE SET money = depositi.money + EXCLUDED.money", (m['id_azienda'], m['ammontare']))
    cur.execute("DELETE FROM multe WHERE id_multa = %s", (m['id_multa'],))
    conn.commit(); cur.close(); conn.close()

    await interaction.followup.send(f"✅ Hai pagato la sanzione di **{m['ammontare']}$**. I fondi sono stati trasferiti al dipartimento.")
    
    emb = discord.Embed(title="⚖️ LOG PAGAMENTO MULTA", color=discord.Color.red(), timestamp=discord.utils.utcnow())
    emb.add_field(name="Cittadino", value=interaction.user.mention); emb.add_field(name="Importo", value=f"{m['ammontare']}$")
    await invia_log_finanziario(interaction.guild, emb)

class PagaFatturaView(discord.ui.View):
    def __init__(self, user_id, fatture):
        super().__init__(timeout=180)
        self.user_id = user_id
        options = [discord.SelectOption(label=f"Fattura {f['id_fattura']}", description=f"Importo: {f['prezzo']}$", value=f"{f['id_fattura']}|{f['prezzo']}|{f['id_azienda']}") for f in fatture]
        self.select = discord.ui.Select(placeholder="Scegli la fattura da saldare...", options=options)
        self.select.callback = self.select_callback
        self.add_item(self.select)

    async def select_callback(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)
        id_f, prezzo, id_az = self.select.values[0].split('|')
        conn = get_db_connection(); cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT wallet FROM users WHERE user_id = %s", (str(interaction.user.id),))
        u_wallet = cur.fetchone()
        
        if not u_wallet or u_wallet['wallet'] < int(prezzo): return await interaction.followup.send("❌ Non hai abbastanza contanti nel portafoglio.", ephemeral=True)

        cur.execute("UPDATE users SET wallet = wallet - %s WHERE user_id = %s", (int(prezzo), str(interaction.user.id)))
        cur.execute("INSERT INTO depositi (role_id, money) VALUES (%s, %s) ON CONFLICT (role_id) DO UPDATE SET money = depositi.money + EXCLUDED.money", (id_az, int(prezzo)))
        cur.execute("UPDATE fatture SET stato = 'Pagata' WHERE id_fattura = %s", (id_f,))
        conn.commit(); cur.close(); conn.close()

        await interaction.edit_original_response(content=f"✅ Fattura `{id_f}` di **{prezzo}$** saldata correttamente.", view=None)
        
        emb = discord.Embed(title="🧾 LOG PAGAMENTO FATTURA", color=discord.Color.gold(), timestamp=discord.utils.utcnow())
        emb.add_field(name="Cliente", value=interaction.user.mention); emb.add_field(name="Importo", value=f"{prezzo}$"); emb.add_field(name="Azienda ID", value=id_az)
        await invia_log_finanziario(interaction.guild, emb)

@bot.tree.command(name="pagafattura", description="Visualizza e paga le fatture aziendali in sospeso")
async def pagafattura(interaction: Interaction):
    await interaction.response.defer(ephemeral=True)
    conn = get_db_connection(); cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM fatture WHERE id_cliente = %s AND stato = 'Pendente'", (str(interaction.user.id),))
    f = cur.fetchall()
    cur.close(); conn.close()
    if not f: return await interaction.followup.send("✅ Non hai fatture pendenti da pagare.", ephemeral=True)
    await interaction.followup.send("Seleziona la fattura da saldare:", view=PagaFatturaView(interaction.user.id, f), ephemeral=True)

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

# --- COMANDO ADMIN: CREA CONFIGURAZIONE RAPINA ---
@bot.tree.command(name="crea_rapina", description="Configura una nuova rapina (Solo Admin)")
@app_commands.describe(
    nome="Nome del luogo (es: Banca, Market)", 
    tempo="Secondi necessari per lo scasso", 
    paga_min="Guadagno minimo", 
    paga_max="Guadagno massimo"
)
async def crea_rapina(interaction: discord.Interaction, nome: str, tempo: int, paga_min: int, paga_max: int):
    # Controllo permessi Admin/Staff
    if not any(role.id == RUOLO_STAFF_ID for role in interaction.user.roles):
        return await interaction.response.send_message("❌ Permessi insufficienti per configurare rapine.", ephemeral=True)

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Inserisce o aggiorna se il nome esiste già (ON CONFLICT)
        cur.execute("""
            INSERT INTO rapine_config (nome, tempo_scasso, paga_min, paga_max)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (nome) DO UPDATE SET 
            tempo_scasso = EXCLUDED.tempo_scasso, 
            paga_min = EXCLUDED.paga_min, 
            paga_max = EXCLUDED.paga_max
        """, (nome.lower(), tempo, paga_min, paga_max))
        
        conn.commit()
        cur.close()
        conn.close()
        
        await interaction.response.send_message(
            f"✅ Configurazione completata!\n"
            f"📍 Luogo: **{nome.upper()}**\n"
            f"⏳ Tempo: `{tempo}s`\n"
            f"💰 Range: `{paga_min}€` - `{paga_max}€`"
        )
    except Exception as e:
        await interaction.response.send_message(f"❌ Errore durante il salvataggio nel Database: {e}", ephemeral=True)



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
    ID_RUOLO_STAFF =  1253460150141059198 # tuo ID ruolo staff
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
# --- LOGICA PER NOTIFICA DM E COMANDO SLASH CON AUTOCOMPLETE ---

YOUR_USER_ID =  1191824316376043580 #Inserisci il tuo ID

# 1. Evento Notifica DM
@bot.event
async def on_guild_join(guild):
    user = await bot.fetch_user(YOUR_USER_ID)
    if user:
        link = "Nessun permesso per l'invito"
        for channel in guild.text_channels:
            if channel.permissions_for(guild.me).create_instant_invite:
                inv = await channel.create_invite(max_age=300)
                link = inv.url
                break
        await user.send(f"✅ **Nuovo Server**: {guild.name}\n🔗 **Link**: {link}")

# 2. Autocomplete per la lista dei server
async def server_autocomplete(interaction: discord.Interaction, current: str):
    # Mostra solo i server che contengono il testo scritto dall'utente
    return [
        discord.app_commands.Choice(name=guild.name, value=str(guild.id))
        for guild in bot.guilds
        if current.lower() in guild.name.lower()
    ][:25] # Massimo 25 suggerimenti consentiti da Discord

# 3. Comando Slash per uscire
@bot.tree.command(name="lascia_server", description="Fa uscire il bot da un server specifico")
@discord.app_commands.autocomplete(server_id=server_autocomplete)
async def lascia_server(interaction: discord.Interaction, server_id: str):
    # Controllo sicurezza: Solo tu puoi eseguire il comando
    if interaction.user.id != YOUR_USER_ID:
        return await interaction.response.send_message("❌ Non hai i permessi!", ephemeral=True)

    guild = bot.get_guild(int(server_id))
    if guild:
        await guild.leave()
        await interaction.response.send_message(f"✅ Ho lasciato il server: **{guild.name}**", ephemeral=True)
    else:
        await interaction.response.send_message("❌ Server non trovato.", ephemeral=True)

# Ricordati di sincronizzare i comandi slash nel tuo evento on_ready:
# await bot.tree.sync()
import random

import random
import discord

import random
import discord

# --- COMANDO ADMIN: AGGIUNGI TRAMITE ALLEGATO ---
@bot.tree.command(name="peter_add", description="Aggiunge una GIF caricando un file (Solo Admin)")
@app_commands.checks.has_permissions(administrator=True)
async def peter_add(interaction: discord.Interaction, file: discord.Attachment):
    # Controllo tipo file
    if not file.content_type or not any(x in file.content_type for x in ["image", "video"]):
        return await interaction.response.send_message("❌ Carica un file valido (GIF, PNG, MP4)!", ephemeral=True)

    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor()
            # Inseriamo l'URL dell'allegato nella tabella peter_gifs
            cur.execute("INSERT INTO peter_gifs (url) VALUES (%s)", (file.url,))
            conn.commit()
            cur.close()
            conn.close()
            await interaction.response.send_message(f"✅ GIF aggiunta al database PostgreSQL!", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Errore database: {e}", ephemeral=True)
    else:
        await interaction.response.send_message("❌ Errore connessione al database!", ephemeral=True)


@bot.tree.command(name="petergriffin", description="Invia una gif casuale di Peter")
async def petergriffin(interaction: discord.Interaction):
    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("SELECT url FROM peter_gifs")
            rows = cur.fetchall()
            cur.close()
            conn.close()

            if not rows:
                return await interaction.response.send_message("⚠️ Il database è vuoto!", ephemeral=True)

            # Scegliamo l'URL dal database
            gif_url = random.choice(rows)[0]
            
            # Creiamo l'Embed
            embed = discord.Embed(color=discord.Color.from_rgb(255, 255, 255))
            
            # TRUCCO: Se l'URL è un link diretto del CDN di Discord, 
            # lo impostiamo come immagine dell'embed. 
            # Se il file è un formato compatibile, Discord nasconderà l'URL.
            embed.set_image(url=gif_url)
            embed.set_footer(text="Ringraziate Killer")
            
            await interaction.response.send_message(embed=embed)
            
        except Exception as e:
            await interaction.response.send_message(f"❌ Errore: {e}", ephemeral=True)
    else:
        await interaction.response.send_message("❌ Errore connessione DB!", ephemeral=True)

# Ho inserito i tuoi link originali. 
@bot.tree.command(name="clear", description="Elimina un numero specifico di messaggi da questo canale")
@app_commands.describe(quantita="Numero di messaggi da eliminare (max 100)")
async def clear(interaction: discord.Interaction, quantita: int):
    # ID del ruolo autorizzato
    ID_RUOLO_AUTORIZZATO = 1253460150141059198
    
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


# --- 1. VIEW PER IL BACKGROUND (ESITO STAFF) ---
class BackgroundStaffView(discord.ui.View):
    def __init__(self, user_id=None, psn_id=None):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.psn_id = psn_id

    @discord.ui.button(label="ACCETTA", style=discord.ButtonStyle.success, emoji="✅", custom_id="bg_accept_fixed")
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        
        # Se il bot è stato riavviato, recuperiamo l'ID dal footer e il PSN dal campo specifico
        try:
            u_id = self.user_id or int(interaction.message.embeds[0].footer.text.split(": ")[1])
            # Cerchiamo il PSN ID nel secondo campo dell'embed (🎮 PSN ID)
            p_id = self.psn_id or interaction.message.embeds[0].fields[1].value.replace("`", "")
            
            member = await interaction.guild.fetch_member(u_id)
            
            # 1. Invio DM (Esito)
            embed_dm = discord.Embed(
                title="✅ Background Accettato!",
                description=f"Il tuo background per **Evren City** è stato approvato.\nIl tuo nick è stato impostato su: `{p_id}`.",
                color=discord.Color.green()
            )
            try: await member.send(embed=embed_dm)
            except: pass # DM Chiusi

            # 2. Cambio Nickname
            try: await member.edit(nick=p_id)
            except: pass # Permessi insufficienti

            await interaction.edit_original_response(content=f"✅ Accettato da {interaction.user.mention}", view=None)
        except Exception as e:
            await interaction.edit_original_response(content=f"❌ Errore: Utente non trovato o dati persi. ({e})", view=None)

    @discord.ui.button(label="RIFIUTA", style=discord.ButtonStyle.danger, emoji="❌", custom_id="bg_reject_fixed")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        try:
            u_id = self.user_id or int(interaction.message.embeds[0].footer.text.split(": ")[1])
            member = await interaction.guild.fetch_member(u_id)
            
            embed_dm = discord.Embed(
                title="❌ Background Rifiutato",
                description="Il tuo background non è stato approvato. Riprova seguendo meglio il regolamento.",
                color=discord.Color.red()
            )
            try: await member.send(embed=embed_dm)
            except: pass

            await interaction.edit_original_response(content=f"❌ Rifiutato da {interaction.user.mention}", view=None)
        except:
            await interaction.edit_original_response(content="❌ Errore nell'invio del rifiuto.", view=None)

# --- 2. VIEW PER LA VERIFICA ---
class VerificaView(discord.ui.View):
    def __init__(self, role_id=None):
        super().__init__(timeout=None)
        self.role_id = role_id

    @discord.ui.button(label="Verificati", style=discord.ButtonStyle.primary, emoji="✅", custom_id="btn_verifica_persist")
    async def verifica(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Se role_id è None (post-riavvio), lo cerchiamo nel DB
        if not self.role_id:
            conn = get_db_connection()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("SELECT role_id FROM verifica_config WHERE guild_id = %s", (str(interaction.guild.id),))
            res = cur.fetchone()
            cur.close(); conn.close()
            if res: self.role_id = int(res['role_id'])

        role = interaction.guild.get_role(self.role_id)
        if role:
            await interaction.user.add_roles(role)
            await interaction.response.send_message("✅ Ti sei verificato!", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Ruolo non configurato correttamente.", ephemeral=True)

# --- 3. COMANDO SETUP BACKGROUND (ADMIN) ---
@bot.tree.command(name="setup_background", description="[ADMIN] Configura il sistema Background")
@app_commands.checks.has_permissions(administrator=True)
async def setup_background(interaction: discord.Interaction, canale_staff: discord.TextChannel, ruolo_richiesto: discord.Role):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO background_config (guild_id, staff_channel_id, required_role_id) 
        VALUES (%s, %s, %s) 
        ON CONFLICT (guild_id) DO UPDATE SET 
        staff_channel_id = EXCLUDED.staff_channel_id, 
        required_role_id = EXCLUDED.required_role_id
    """, (str(interaction.guild.id), str(canale_staff.id), str(ruolo_richiesto.id)))
    conn.commit()
    cur.close(); conn.close()
    await interaction.response.send_message(f"✅ Background configurato: {canale_staff.mention}", ephemeral=True)

# --- 4. COMANDO BACKGROUND (UTENTI) ---
@bot.tree.command(name="background", description="Invia il tuo background PG")
async def background(interaction: discord.Interaction, nome: str, eta: str, psn_id: str, esperienze: str, storia: str, paure: str, obiettivi: str, regolamento: str):
    await interaction.response.defer(ephemeral=True)

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM background_config WHERE guild_id = %s", (str(interaction.guild.id),))
    config = cur.fetchone()
    cur.close(); conn.close()

    if not config:
        return await interaction.followup.send("❌ Sistema non configurato.", ephemeral=True)

    # Controllo Ruolo
    role_req = interaction.guild.get_role(int(config['required_role_id']))
    if role_req not in interaction.user.roles:
        return await interaction.followup.send(f"❌ Devi avere il ruolo {role_req.mention}!", ephemeral=True)

    # Embed Integrale
    embed = discord.Embed(title="📩 Richiesta Background", color=discord.Color.orange(), description=f"**📖 STORIA:**\n{storia}")
    embed.add_field(name="👤 Dati", value=f"Nome: {nome}\nEtà: {eta}", inline=True)
    embed.add_field(name="🎮 PSN ID", value=f"`{psn_id}`", inline=True)
    embed.add_field(name="📚 Esperienze", value=esperienze, inline=False)
    embed.add_field(name="😨 Paure/Obiettivi", value=f"P: {paure}\nO: {obiettivi}", inline=False)
    embed.set_footer(text=f"ID Utente: {interaction.user.id}") # FONDAMENTALE PER PERSISTENZA

    # Invio Staff
    staff_chan = interaction.guild.get_channel(int(config['staff_channel_id']))
    if staff_chan:
        view = BackgroundStaffView(user_id=interaction.user.id, psn_id=psn_id)
        await staff_chan.send(embed=embed, view=view)
        
        # Invio copia DM all'utente
        try: await interaction.user.send(content="**Ecco una copia del tuo background:**", embed=embed)
        except: pass

        await interaction.followup.send("✅ Background inviato! Hai ricevuto una copia integrale in DM.", ephemeral=True)
    else:
        await interaction.followup.send("❌ Errore: Canale staff non trovato.", ephemeral=True)

# --- 5. REGISTRAZIONE OBBLIGATORIA IN ON_READY ---
@bot.event
async def on_ready():
    # Questo permette ai bottoni vecchi di funzionare dopo il riavvio
    bot.add_view(BackgroundStaffView())
    bot.add_view(VerificaView())
    print(f"Bot online come {bot.user}")
    await bot.tree.sync()

# --- COMANDI RP LEGA/SLEGA (SOLO TESTUALI) ---
@bot.tree.command(name="lega", description="Azione RP: Lega un utente")
async def lega(interaction: discord.Interaction, utente: discord.Member):
    embed = discord.Embed(description=f"⛓️ **{interaction.user.display_name}** ha legato **{utente.mention}**.", color=discord.Color.dark_gray())
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="slega", description="Azione RP: Slega un utente")
async def slega(interaction: discord.Interaction, utente: discord.Member):
    embed = discord.Embed(description=f"🔓 **{interaction.user.display_name}** ha slegato **{utente.mention}**.", color=discord.Color.green())
    await interaction.response.send_message(embed=embed)

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
    ID_RUOLO_STAFF = 1253460150141059198
     
    
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
@app_commands.checks.has_role( 1253707509399683202)
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

POLIZIA_ROLE_ID = 1363487988570521670

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

@bot.tree.command(name="arresto", description="Registra un arresto nel database e annuncialo in chat")
@app_commands.describe(
    utente="Il cittadino da arrestare",
    tempo_minuti="Durata della pena in minuti",
    motivo="Il reato commesso"
)
async def arresto(interaction: discord.Interaction, utente: discord.Member, tempo_minuti: int, motivo: str):
    # Controllo se l'utente è un poliziotto
    if not any(role.id ==  1363487988570521670 for role in interaction.user.roles):

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
@bot.tree.command(name="ricerca_cittadino", description="Ricerca avanzata nel database statale")
@app_commands.describe(
    cittadino="Tagga l'utente (opzionale)",
    nome="Nome o parte del nome (opzionale)",
    cognome="Cognome o parte del cognome (opzionale)"
)
async def ricerca(interaction: discord.Interaction, cittadino: discord.Member = None, nome: str = None, cognome: str = None):
    # Controllo Ruolo Polizia (Sostituisci POLIZIA_ROLE_ID con la tua variabile o ID)
    if not any(role.id == POLIZIA_ROLE_ID for role in interaction.user.roles):
        return await interaction.response.send_message("❌ Accesso negato: Solo le forze dell'ordine possono consultare il database.", ephemeral=True)
    
    await interaction.response.defer()

    try:
        conn = get_db_connection()
        from psycopg2.extras import RealDictCursor
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # 1. Ricerca diretta tramite Tag
        if cittadino:
            cur.close(); conn.close()
            return await mostra_fascicolo(interaction, str(cittadino.id))

        # 2. Ricerca tramite Nome/Cognome
        if nome or cognome:
            search_nome = f"%{nome}%" if nome else "%"
            search_cognome = f"%{cognome}%" if cognome else "%"

            cur.execute("""
                SELECT user_id, nome, cognome FROM documenti 
                WHERE nome ILIKE %s AND cognome ILIKE %s
                LIMIT 25
            """, (search_nome, search_cognome))
            
            results = cur.fetchall()
            cur.close(); conn.close()

            if not results:
                return await interaction.followup.send("❌ Nessun cittadino trovato con questi dati.")
            
            if len(results) == 1:
                return await mostra_fascicolo(interaction, results[0]['user_id'])
            
            # Menu a tendina per risultati multipli
            options = [
                discord.SelectOption(
                    label=f"{r['nome']} {r['cognome']}", 
                    description=f"ID: {r['user_id']}", 
                    value=r['user_id']
                ) for r in results
            ]
            
            view = CitizenView(options, interaction) # Assicurati che CitizenView sia definita
            await interaction.followup.send("🔎 Trovati più profili. Seleziona quello corretto:", view=view)
        else:
            return await interaction.followup.send("⚠️ Specifica un cittadino (Tag) o un Nome/Cognome.")

    except Exception as e:
        print(f"Errore ricerca: {e}")
        await interaction.followup.send("❌ Errore critico durante la ricerca nel database.")

# --- FUNZIONE HELPER PER MOSTRARE IL FASCICOLO INTEGRALE ---
async def mostra_fascicolo(interaction, target_id, original_interaction=None):
    ctx = interaction if not original_interaction else original_interaction
    
    try:
        conn = get_db_connection()
        from psycopg2.extras import RealDictCursor
        cur = conn.cursor(cursor_factory=RealDictCursor)

        # QUERY DATI BASE
        cur.execute("SELECT * FROM documenti WHERE user_id = %s", (target_id,))
        doc = cur.fetchone()
        cur.execute("SELECT targa, modello, sequestrato FROM veicoli WHERE owner_id = %s", (target_id,))
        veicoli = cur.fetchall()
        cur.execute("SELECT * FROM multe WHERE user_id = %s", (target_id,))
        multe = cur.fetchall()
        cur.execute("SELECT * FROM arresti WHERE user_id = %s ORDER BY id_arresto DESC LIMIT 5", (target_id,))
        arresti = cur.fetchall()

        # QUERY NUOVE REGISTRAZIONI (PATENTI, MEDICI, ARMI)
        cur.execute("SELECT tipo, costo FROM patenti_registrate WHERE user_id = %s", (target_id,))
        patenti = cur.fetchall()
        cur.execute("SELECT esito, costo FROM certificati_medici WHERE user_id = %s", (target_id,))
        certificati = cur.fetchall()
        cur.execute("SELECT tipo, motivo FROM licenze_armi WHERE user_id = %s", (target_id,))
        licenze = cur.fetchall()
        cur.execute("SELECT modello, matricola, motivo FROM registro_armi WHERE user_id = %s", (target_id,))
        armi = cur.fetchall()

        cur.close(); conn.close()

        target_member = ctx.guild.get_member(int(target_id))
        nome_display = f"{doc['nome']} {doc['cognome']}" if doc else "Soggetto Ignoto"
        
        embed = discord.Embed(title=f"📁 FASCICOLO STATALE: {nome_display}", color=discord.Color.dark_blue())
        if target_member:
            embed.set_thumbnail(url=target_member.display_avatar.url)
        
        # --- ANAGRAFICA ---
        if doc:
            embed.add_field(name="🪪 Anagrafica", value=f"Nascita: {doc['data_nascita']} ({doc['luogo_nascita']})\nGenere: {doc['genere']} | Altezza: {doc['altezza']}cm", inline=False)
        
        # --- LICENZE E CERTIFICATI (INTEGRATI) ---
        lic_list = []
        if patenti: [lic_list.append(f"• **Patente {p['tipo']}** (Pagato: {p['costo']})") for p in patenti]
        if certificati: [lic_list.append(f"• **Cert. Medico:** {c['esito']} (Pagato: {c['costo']})") for c in certificati]
        if licenze: [lic_list.append(f"• **Porto d'Armi:** {l['tipo']} (Motivo: {l['motivo']})") for l in licenze]
        
        if lic_list:
            embed.add_field(name="📜 Licenze e Abilitazioni", value="\n".join(lic_list), inline=False)

        # --- REGISTRO ARMI E MATRICOLE ---
        if armi:
            armi_list = "\n".join([f"• `{a['matricola']}` | {a['modello']} (Motivo: {a['motivo']})" for a in armi])
            embed.add_field(name="⚙️ Registro Matricole Armi", value=armi_list, inline=False)

        # --- VEICOLI ---
        if veicoli:
            v_list = "\n".join([f"• `{v['targa']}` - {v['modello']} {'(🚫 Sequestrato)' if v['sequestrato'] else ''}" for v in veicoli])
            embed.add_field(name="🚘 Parco Veicoli", value=v_list, inline=False)
        
        # --- FEDINA PENALE (MULTE + ARRESTI) ---
        fedina = []
        if multe: [fedina.append(f"• Multe: {m['ammontare']}€ - {m['motivo']}") for m in multe]
        if arresti: [fedina.append(f"• Arresto: {a['data']} - {a['motivo']}") for a in arresti]
        
        if fedina:
            embed.add_field(name="⚖️ Precedenti e Sanzioni", value="\n".join(fedina), inline=False)

        # Invio Risposta
        if original_interaction:
            await interaction.response.send_message(embed=embed)
        else:
            await ctx.followup.send(embed=embed)

    except Exception as e:
        print(f"Errore mostra_fascicolo: {e}")
        error_msg = "❌ Errore durante il recupero del fascicolo."
        if original_interaction: await interaction.response.send_message(error_msg, ephemeral=True)
        else: await ctx.followup.send(error_msg)




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
@bot.tree.command(name="passa", description="Passa un oggetto dal tuo inventario a un altro utente")
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


