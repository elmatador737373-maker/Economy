import os
import json
import asyncio
import threading
from flask import Flask
import discord
from discord import app_commands
from discord.ext import commands

# ---------------------------------------------------------
# 1. SERVER FLASK INTEGRATO (Keep-Alive)
# ---------------------------------------------------------
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot per Discord Italia Online! 🇮🇹"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = threading.Thread(target=run_flask)
    t.daemon = True
    t.start()

# ---------------------------------------------------------
# 2. CONFIGURAZIONE & COSTANTI
# ---------------------------------------------------------
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

# ---------------------------------------------------------
# 3. DEFINIZIONE DEL BOT (CustomBot)
# ---------------------------------------------------------
class CustomBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        # Aggiunta delle viste persistenti (assicurati che le classi siano definite prima)
        # self.add_view(TicketSelectView())
        # self.add_view(TicketControlView())
        # self.add_view(ClosedTranscriptView())
        # self.add_view(StaffApplicationView())

        # Sincronizzazione dei comandi slash con Discord
        await self.tree.sync()
        print("Albero dei comandi sincronizzato con successo.")

    async def on_ready(self):
        print(f"Logged in as {self.user} (ID: {self.user.id})")

# Inizializzazione dell'istanza del bot
bot = CustomBot()

STAFF_MGMT_ROLE_ID = 1455297916708192373
STAFF_GENERAL_ROLE_ID = 1455297926468468777  # Ruolo taggato all'apertura del ticket
LOG_CHANNEL_ID = 1487393847830122597        # ⚠️ INSERISCI QUI L'ID DEL CANALE LOG CORRETTO (ora usa una variabile pulita)
TICKET_CATEGORY_ID = 1455298169415012547    # Categoria in cui vengono aperti i ticket


import discord
from discord.ext import tasks
import datetime
import pytz

# --- CONFIGURAZIONE PRINCIPALE ---
ID_CANALE_SALUTI = 1455298208413520014  # Inserisci l'ID del canale dove inviare i messaggi

# --- FUSO ORARIO E PERSONALIZZAZIONE ORARI ---
TZ_ITALIA = pytz.timezone("Europe/Rome")

# Personalizza qui l'ora (hour) e i minuti (minute) di invio
ORARIO_BUONGIORNO = datetime.time(hour=8, minute=0, second=0, tzinfo=TZ_ITALIA)
ORARIO_BUONASERA  = datetime.time(hour=21, minute=0, second=0, tzinfo=TZ_ITALIA)

# --- MESSAGGI GIORNALIERI (STYLE DISCORD ITALIA 🇮🇹) ---
MESSAGGI_GIORNI = {
    "Monday": {
        "titolo": "🇮🇹 ☕ Buon Lunedì & GG di inizio settimana!",
        "descrizione": "Il Lunedì è tornato a fare il raid alla nostra pazienza, ma noi non molliamo. Caffè alla mano, accendete i PC e preparatevi a spaccare su **Discord Italia 🇮🇹**!",
        "quote": "🔥 *Nuova settimana, nuove quest da completare.*",
        "colore": "#5865F2"
    },
    "Tuesday": {
        "titolo": "🇮🇹 ⚡ Buon Martedì Community!",
        "descrizione": "Motori caldi e settimana ormai avviata. Passo rapido in voice o chat testuale prima di ripartire? Ci si becca nei canali!",
        "quote": "🎯 *Focus sull'obiettivo e niente tilt oggi.*",
        "colore": "#3ba55c"
    },
    "Wednesday": {
        "titolo": "🇮🇹 🐫 Buon Mercoledì & Mid-Week!",
        "descrizione": "Siamo ufficialmente a metà strada! Il weekend inizia a vedersi all'orizzonte. Chi si fa due chiacchiere o una partita stasera?",
        "quote": "🎮 *La metà della settimana si supera meglio in Voice.*",
        "colore": "#faa61a"
    },
    "Thursday": {
        "titolo": "🇮🇹 🚀 Buon Giovedì GG WP!",
        "descrizione": "Quasi nel weekend, manca pochissimo! Carichi per le ultime cose prima del relax totale?",
        "quote": "⚔️ *Resistere: il fine settimana è alle porte!*",
        "colore": "#eb459e"
    },
    "Friday": {
        "titolo": "🇮🇹 🎉 FINALLY FRIDAY! Buon Venerdì!",
        "descrizione": "Venerdì! Si stacca tutto, si aprono le lobby e ci si gode il weekend. Quali sono i programmi per stasera su Discord Italia 🇮🇹?",
        "quote": "🍕 *Lobby pronte, stasera non si va a dormire presto.*",
        "colore": "#f47b67"
    },
    "Saturday": {
        "titolo": "🇮🇹 🎮 Buon Sabato & Mode: Full Gaming!",
        "descrizione": "Zero pensieri, solo relax, sessioni di gaming, musica ed eventi del server. Godetevi la giornata!",
        "quote": "🕹️ *Sabato = No stress, solo divertimento.*",
        "colore": "#9b59b6"
    },
    "Sunday": {
        "titolo": "🇮🇹 ☀️ Buona Domenica Chill!",
        "descrizione": "Domenica in totale relax. Ricarichiamo le batterie insieme in community prima del riavvio di domani!",
        "quote": "🛋️ *Mood di oggi: chill e chiacchiere in serenità.*",
        "colore": "#e74c3c"
    }
}

intents = discord.Intents.default()
bot = discord.Client(intents=intents)


# --- EVENTO 1: AVVIO E ATTIVAZIONE TASK ---
@bot.event
async def on_ready():
    if not invia_buongiorno_automatico.is_running():
        invia_buongiorno_automatico.start()
    if not invia_buonasera_automatica.is_running():
        invia_buonasera_automatica.start()
    print(f"✅ Modulo Saluti attivo ed operativo per: {bot.user}")


# --- EVENTO 2: TASK AUTOMATICO BUONGIORNO ---
@tasks.loop(time=ORARIO_BUONGIORNO)
async def invia_buongiorno_automatico():
    canale = bot.get_channel(ID_CANALE_SALUTI)
    if not canale:
        return

    ora_attuale = datetime.datetime.now(TZ_ITALIA)
    nome_giorno = ora_attuale.strftime("%A")
    data_formattata = ora_attuale.strftime("%d/%m/%Y")
    info_giorno = MESSAGGI_GIORNI.get(nome_giorno, MESSAGGI_GIORNI["Monday"])

    embed = discord.Embed(
        title=info_giorno['titolo'],
        description=f"{info_giorno['descrizione']}\n\n{info_giorno['quote']}",
        color=discord.Color.from_str(info_giorno['colore']),
        timestamp=ora_attuale
    )

    if canale.guild.icon:
        embed.set_thumbnail(url=canale.guild.icon.url)

    embed.add_field(name="📅 Data", value=f"`{data_formattata}`", inline=True)
    embed.add_field(name="👥 Squadra Server", value=f"`{canale.guild.member_count}` Membri", inline=True)
    embed.add_field(
        name="📌 Note dalla Community",
        value="Controlla i canali testuali/vocali, rispetta la regolation e unisciti ai match del giorno! 🇮🇹",
        inline=False
    )
    embed.set_footer(text="Discord Italia 🇮🇹 • Make your day awesome!", icon_url=canale.guild.icon.url if canale.guild.icon else None)

    await canale.send(
        content="@everyone",
        embed=embed,
        allowed_mentions=discord.AllowedMentions(everyone=True)
    )


# --- EVENTO 3: TASK AUTOMATICO BUONASERA ---
@tasks.loop(time=ORARIO_BUONASERA)
async def invia_buonasera_automatica():
    canale = bot.get_channel(ID_CANALE_SALUTI)
    if not canale:
        return

    ora_attuale = datetime.datetime.now(TZ_ITALIA)
    data_formattata = ora_attuale.strftime("%d/%m/%Y")

    embed = discord.Embed(
        title="🇮🇹 🌙 Good Night & Night Vibes — Discord Italia!",
        description="La giornata volge al termine, ma la notte su Discord Italia 🇮🇹 è appena iniziata! Sessioni di gaming notturno o chiacchiere chill?",
        color=discord.Color.from_str("#2b2d31"),
        timestamp=ora_attuale
    )

    if canale.guild.icon:
        embed.set_thumbnail(url=canale.guild.icon.url)

    embed.add_field(name="🎧 Canali Vocali", value="Entra nelle room vocali per fare due chiacchiere o unirti alle partite in corso!", inline=False)
    embed.add_field(name="✨ Server Stats", value=f"Siamo in **{canale.guild.member_count}** su **{canale.guild.name}** 🇮🇹", inline=True)
    embed.add_field(name="📅 Data", value=f"`{data_formattata}`", inline=True)

    embed.set_footer(text="Discord Italia 🇮🇹 • Buona serata e GG a tutti!", icon_url=canale.guild.icon.url if canale.guild.icon else None)

    await canale.send(
        content="@everyone",
        embed=embed,
        allowed_mentions=discord.AllowedMentions(everyone=True)
    )

# ---------------------------------------------------------
# EVENTO WELCOME (Da inserire prima del blocco di avvio)
# ---------------------------------------------------------
@bot.event
async def on_member_join(member: discord.Member):
    # ⚠️ SOSTITUISCI QUESTO ID CON QUELLO DEL CANALE DI BENVENUTO REALE
    WELCOME_CHANNEL_ID = 1455298181003743394  
    
    channel = member.guild.get_channel(WELCOME_CHANNEL_ID)
    if not channel:
        return

    # Nome del file immagine presente nella stessa repository/cartella del bot
    image_filename = "1A88159A-78B8-4D55-A308-E39A31B4F1D8.png"
    file = discord.File(image_filename, filename="welcome.png")

    embed = discord.Embed(
        title="🇮🇹 Benvenuto su Discord Italia V4!",
        description=f"Ciao {member.mention}, benvenuto nel nostro server ufficiale! Siamo felici di averti qui con noi.",
        color=discord.Color.from_rgb(0, 146, 70)
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_image(url="attachment://welcome.png")
    embed.set_footer(text=f"Utente #{len(member.guild.members)} • Discord Italia 🇮🇹")

    await channel.send(content=f"🎉 Benvenuto {member.mention}!", embed=embed, file=file)

# ---------------------------------------------------------
# 3. MODAL BANDO STAFF
# ---------------------------------------------------------
class StaffApplicationModal(discord.ui.Modal, title="📋 MODULO CANDIDATURA STAFF"):
    info = discord.ui.TextInput(label="👤 Informazioni Personali", style=discord.TextStyle.paragraph, required=True, max_length=500)
    esperienza = discord.ui.TextInput(label="🛡️ Esperienza", style=discord.TextStyle.paragraph, required=True, max_length=500)
    conoscenze = discord.ui.TextInput(label="📚 Conoscenze Discord & Moderazione", style=discord.TextStyle.paragraph, required=True, max_length=1000)
    partnership = discord.ui.TextInput(label="🤝 Esperienza Partnership", style=discord.TextStyle.paragraph, required=True, max_length=500)
    motivazioni = discord.ui.TextInput(label="🎯 Motivazioni", style=discord.TextStyle.paragraph, required=True, max_length=500)

    async def on_submit(self, interaction: discord.Interaction):
        confirm_embed = discord.Embed(
            title="✅ Candidatura inviata!",
            description=f"Grazie! Il tuo bando verrà esaminato da un membro del <@&{STAFF_MGMT_ROLE_ID}>.",
            color=discord.Color.green()
        )
        await interaction.response.send_message(embed=confirm_embed, ephemeral=True)

        app_embed = discord.Embed(title=f"📋 Bando Staff - {interaction.user.display_name}", color=discord.Color.blue())
        app_embed.set_thumbnail(url=interaction.user.display_avatar.url)
        app_embed.add_field(name="👤 Informazioni", value=self.info.value, inline=False)
        app_embed.add_field(name="🛡️ Esperienza", value=self.esperienza.value, inline=False)
        app_embed.add_field(name="📚 Conoscenze", value=self.conoscenze.value, inline=False)
        app_embed.add_field(name="🤝 Partnership", value=self.partnership.value, inline=False)
        app_embed.add_field(name="🎯 Motivazioni", value=self.motivazioni.value, inline=False)
        app_embed.set_footer(text=f"ID Utente: {interaction.user.id}")

        await interaction.channel.send(content=f"<@&{STAFF_MGMT_ROLE_ID}> Nuova candidatura ricevuta!", embed=app_embed)

class StaffApplicationView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="📝 Compila Modulo", style=discord.ButtonStyle.primary, custom_id="open_staff_modal_btn")
    async def open_modal(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(StaffApplicationModal())

# ---------------------------------------------------------
# 4. VIEW PERSISTENTE NEL CANALE LOG (Riapertura automatica da allegato JSON)
# ---------------------------------------------------------
class ClosedTranscriptView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔓 Riapri Ticket da Transcript", style=discord.ButtonStyle.green, custom_id="btn_reopen_from_log")
    async def reopen_from_log(self, interaction: discord.Interaction, button: discord.ui.Button):
        staff_role = interaction.guild.get_role(STAFF_GENERAL_ROLE_ID)
        if staff_role not in interaction.user.roles and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Solo i membri dello Staff possono riaprire i ticket.", ephemeral=True)
            return

        message = interaction.message
        if not message.attachments:
            await interaction.response.send_message("❌ Errore: Il file JSON del transcript non è allegato a questo messaggio di log.", ephemeral=True)
            return

        attachment = message.attachments[0]
        if not attachment.filename.endswith(".json"):
            await interaction.response.send_message("❌ Errore: L'allegato non è un file JSON valido.", ephemeral=True)
            return

        await interaction.response.send_message("🔄 Estrazione dati, ricreazione canale e ricostruzione chat in corso...", ephemeral=True)

        try:
            file_bytes = await attachment.read()
            data = json.loads(file_bytes.decode("utf-8"))
        except Exception as e:
            await interaction.followup.send(f"❌ Errore nella lettura del file JSON: {e}", ephemeral=True)
            return

        guild = interaction.guild
        channel_name = data.get("channel_name", "ticket-riaperto")
        owner_id = data.get("owner_id")
        messages = data.get("messages", [])

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }

        owner_member = guild.get_member(owner_id) if owner_id else None
        if owner_member:
            overwrites[owner_member] = discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True)

        if staff_role:
            overwrites[staff_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True)

        category = guild.get_channel(TICKET_CATEGORY_ID)

        new_channel = await guild.create_text_channel(
            name=f"reopen-{channel_name}", 
            overwrites=overwrites,
            category=category if isinstance(category, discord.CategoryChannel) else None
        )

        webhook = await new_channel.create_webhook(name="Transcript Replicator")

        header_embed = discord.Embed(
            title="🔄 RICOSTRUZIONE CHAT DA TRANSCRIPT",
            description=f"Ticket riaperto da {interaction.user.mention} tramite il pannello log.",
            color=discord.Color.green()
        )
        await new_channel.send(embed=header_embed)

        for msg in messages:
            try:
                attachments_text = "\n".join(msg["attachments"]) if msg["attachments"] else ""
                msg_text = msg["content"] if msg["content"] else ""
                final_content = f"{msg_text}\n{attachments_text}".strip()

                if not final_content:
                    continue

                await webhook.send(
                    content=final_content,
                    username=f"{msg['author_name']} (ID: {msg['author_id']})",
                    avatar_url=msg["author_avatar"]
                )
                await asyncio.sleep(0.3)
            except Exception as e:
                print(f"Errore durante l'invio via Webhook: {e}")

        await webhook.delete()
        await new_channel.send("⚙️ **Pannello Gestione Ticket:**", view=TicketControlView())
        await interaction.followup.send(f"✅ Canale ricreato con successo: {new_channel.mention}", ephemeral=True)

# ---------------------------------------------------------
# 5. PANNELLO DI CONTROLLO TICKET (PERMANENTE)
# ---------------------------------------------------------
class TicketControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🔒 Chiudi ed Elimina", style=discord.ButtonStyle.red, custom_id="btn_ticket_close")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = interaction.channel
        await interaction.response.defer(thinking=True, ephemeral=True)

        owner_id = None
        for overwrite_target, overwrite_perms in channel.overwrites.items():
            if isinstance(overwrite_target, discord.Member) and not overwrite_target.bot:
                owner_id = overwrite_target.id
                break

        messages_data = []
        async for msg in channel.history(limit=500, oldest_first=True):
            if msg.author.bot and msg.components:
                continue

            messages_data.append({
                "author_name": msg.author.display_name,
                "author_id": msg.author.id,
                "author_avatar": msg.author.display_avatar.url,
                "content": msg.content,
                "attachments": [att.url for att in msg.attachments]
            })

        transcript_payload = {
            "channel_name": channel.name,
            "owner_id": owner_id,
            "messages": messages_data
        }

        filename = f"transcript-{channel.id}.json"
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(transcript_payload, f, ensure_ascii=False, indent=4)

        log_channel = interaction.guild.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            embed_log = discord.Embed(
                title=f"📦 Transcript Archiviato: {channel.name}",
                description=f"**Chiuso da:** {interaction.user.mention}\nClicca il bottone sottostante per riaprire automaticamente questo ticket.",
                color=discord.Color.red()
            )
            await log_channel.send(embed=embed_log, file=discord.File(filename), view=ClosedTranscriptView())

        if os.path.exists(filename):
            os.remove(filename)

        await channel.delete()

    @discord.ui.button(label="🙋‍♂️ Reclama", style=discord.ButtonStyle.green, custom_id="btn_ticket_claim")
    async def claim_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        staff_role = interaction.guild.get_role(STAFF_GENERAL_ROLE_ID)
        if staff_role not in interaction.user.roles and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Solo i membri dello Staff possono reclamare i ticket.", ephemeral=True)
            return

        embed = discord.Embed(
            description=f"📌 Questo ticket è stato preso in carico da {interaction.user.mention}.",
            color=discord.Color.gold()
        )
        button.disabled = True
        button.label = f"Reclamato da {interaction.user.display_name}"
        await interaction.message.edit(view=self)
        await interaction.response.send_message(embed=embed)

    @discord.ui.button(label="⏸️ Metti in Attesa", style=discord.ButtonStyle.secondary, custom_id="btn_ticket_hold")
    async def hold_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        staff_role = interaction.guild.get_role(STAFF_GENERAL_ROLE_ID)
        if staff_role not in interaction.user.roles and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Solo lo Staff può mettere in attesa i ticket.", ephemeral=True)
            return

        embed = discord.Embed(
            title="⏸️ Ticket in Attesa",
            description="Questo ticket è stato inserito nello stato di **attesa**. Lo staff ti risponderà non appena possibile.",
            color=discord.Color.orange()
        )
        await interaction.response.send_message(embed=embed)

# ---------------------------------------------------------
# 6. SELEZIONE CATEGORIA TICKET (PERMANENTE)
# ---------------------------------------------------------
class TicketSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Ticket Generale", description="Assistenza generica per il server", emoji="📩", value="generale"),
            discord.SelectOption(label="Partnership", description="Richieste di partnership e collaborazioni", emoji="🤝", value="partnership"),
            discord.SelectOption(label="Bando Staff", description="Candidati per entrare nello staff", emoji="📋", value="staff"),
            discord.SelectOption(label="Amministrazione", description="Supporto direttivo e segnalazioni gravi", emoji="👑", value="admin"),
            discord.SelectOption(label="Grafiche & Bot", description="Richieste grafiche o supporto bot custom", emoji="🎨", value="grafiche_bot"),
        ]
        super().__init__(placeholder="Scegli la categoria del Ticket...", min_values=1, max_values=1, options=options, custom_id="select_ticket_category")

    async def callback(self, interaction: discord.Interaction):
        category_type = self.values[0]
        guild = interaction.guild
        user = interaction.user

        channel_name = f"ticket-{category_type}-{user.name}"

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            user: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }

        staff_role = guild.get_role(STAFF_GENERAL_ROLE_ID)
        if staff_role:
            overwrites[staff_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True)

        category = guild.get_channel(TICKET_CATEGORY_ID)

        ticket_channel = await guild.create_text_channel(
            name=channel_name, 
            overwrites=overwrites,
            category=category if isinstance(category, discord.CategoryChannel) else None
        )

        await interaction.response.send_message(f"✅ Ticket creato: {ticket_channel.mention}", ephemeral=True)

        tag_message = f"<@&{STAFF_GENERAL_ROLE_ID}> | {user.mention}"

        if category_type == "staff":
            embed_staff = discord.Embed(
                title="📋 MODULO CANDIDATURA STAFF",
                description="> Benvenuto! Clicca sul pulsante sottostante per iniziare a compilare il modulo.",
                color=discord.Color.orange()
            )
            await ticket_channel.send(content=tag_message, embed=embed_staff, view=StaffApplicationView())
            await ticket_channel.send("⚙️ **Pannello Gestione Ticket:**", view=TicketControlView())
        else:
            embed_gen = discord.Embed(
                title=f"🎫 Ticket {category_type.capitalize()}",
                description=f"Ciao {user.mention}, grazie per aver aperto un ticket!\nDescrivi la tua richiesta e uno staffer ti assisterà a breve.",
                color=discord.Color.green()
            )
            await ticket_channel.send(content=tag_message, embed=embed_gen, view=TicketControlView())

class TicketSelectView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketSelect())

@bot.tree.command(name="setup_ticket", description="Invia il pannello principale dei Ticket (Solo Admin)")
@app_commands.checks.has_permissions(administrator=True)
async def setup_ticket(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🇮🇹 Assistenza & Supporto - Discord Italia",
        description=(
            "Benvenuto nel centro supporto del server!\n\n"
            "Seleziona dal menu a tendina la categoria desiderata:\n\n"
            "📩 **Ticket Generale:** Domande e supporto generale.\n"
            "🤝 **Partnership:** Proposte di collaborazione.\n"
            "📋 **Bando Staff:** Candidature per lo Staff.\n"
            "👑 **Amministrazione:** Problemi gravi o direttivi.\n"
            "🎨 **Grafiche & Bot:** Richieste grafiche e sviluppo Bot."
        ),
        color=discord.Color.from_rgb(0, 146, 70)
    )
    embed.set_footer(text="Discord Italia 🇮🇹 • Sistema di Supporto")
    await interaction.channel.send(embed=embed, view=TicketSelectView())
    await interaction.response.send_message("Pannello inviato!", ephemeral=True)

ticket_group = app_commands.Group(name="ticket", description="Comandi per gestire i ticket esistenti")

@ticket_group.command(name="add", description="Aggiungi un utente al ticket attuale")
@app_commands.checks.has_permissions(manage_channels=True)
async def ticket_add(interaction: discord.Interaction, member: discord.Member):
    await interaction.channel.set_permissions(member, read_messages=True, send_messages=True)
    await interaction.response.send_message(f"✅ {member.mention} è stato aggiunto al ticket.")

@ticket_group.command(name="remove", description="Rimuovi un utente dal ticket attuale")
@app_commands.checks.has_permissions(manage_channels=True)
async def ticket_remove(interaction: discord.Interaction, member: discord.Member):
    await interaction.channel.set_permissions(member, overwrite=None)
    await interaction.response.send_message(f"🚫 {member.mention} è stato rimosso dal ticket.")

@ticket_group.command(name="rename", description="Rinomina il ticket attuale")
@app_commands.checks.has_permissions(manage_channels=True)
async def ticket_name(interaction: discord.Interaction, new_name: str):
    await interaction.channel.edit(name=f"ticket-{new_name}")
    await interaction.response.send_message(f"✏️ Ticket rinominato in `ticket-{new_name}`.")

bot.tree.add_command(ticket_group)

ID_CANALE_JSON = 1533471957939654758  # Sostituisci con l'ID numerico del canale di backup


@bot.tree.command(name="gerarchia", description="Invia il pannello gerarchia e salva la configurazione JSON.")
@app_commands.checks.has_permissions(administrator=True)
async def comando_gerarchia(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    canale_json = interaction.guild.get_channel(ID_CANALE_JSON)
    if not canale_json:
        await interaction.followup.send("❌ Canale JSON non trovato. Verifica l'ID inserito nel codice.", ephemeral=True)
        return

    # Salvataggio ID canale principale e canale backup
    data_store["main_channel_id"] = interaction.channel_id
    data_store["json_backup_channel_id"] = ID_CANALE_JSON

    # Rilevamento automatico ID ruoli
    data_store["roles_map"] = {
        item["name"]: discord.utils.get(interaction.guild.roles, name=item["name"]).id
        for item in RUOLI_GERARCHIA if discord.utils.get(interaction.guild.roles, name=item["name"])
    }

    # Assegnazione membro solo al ruolo più alto
    utenti_processati = set()
    mappa_membri = {item["name"]: [] for item in RUOLI_GERARCHIA}

    for item in RUOLI_GERARCHIA:
        role_id = data_store["roles_map"].get(item["name"])
        if role_id:
            role = interaction.guild.get_role(role_id)
            if role:
                for member in role.members:
                    if member.id not in utenti_processati and not member.bot:
                        mappa_membri[item["name"]].append(member.mention)
                        utenti_processati.add(member.id)

    # Costruzione testo
    descrizione = ""
    for item in RUOLI_GERARCHIA:
        membri = mappa_membri.get(item["name"], [])
        lista = ", ".join(membri) if membri else "*Nessuno*"
        descrizione += f"{item['label']} : {lista}\n\n"

    embed = discord.Embed(title="👑 GERARCHIA STAFF", description=descrizione, color=discord.Color.from_str("#2b2d31"))
    msg = await interaction.channel.send(embed=embed)
    data_store["main_message_id"] = msg.id

    # Salvataggio ed invio file JSON sul canale specificato nel codice
    with open("hierarchy_data.json", "w", encoding="utf-8") as f:
        json.dump(data_store, f, indent=4, ensure_ascii=False)

    buffer = io.BytesIO(json.dumps(data_store, indent=4, ensure_ascii=False).encode('utf-8'))
    await canale_json.send("📦 **Backup Configurazione Gerarchia (JSON)**", file=discord.File(buffer, filename="hierarchy_data.json"))

    await interaction.followup.send(f"✅ Gerarchia inviata ed attivata!\n📦 Backup salvato in: {canale_json.mention}", ephemeral=True)


@comando_gerarchia.error
async def gerarchia_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        await interaction.response.send_message("❌ Solo gli **Amministratori** possono usare questo comando.", ephemeral=True)


@bot.event
async def on_member_update(before: discord.Member, after: discord.Member):
    if before.roles != after.roles:
        await aggiorna_messaggio(after.guild)

@bot.event
async def on_member_remove(member: discord.Member):
    await aggiorna_messaggio(member.guild)

# ---------------------------------------------------------
# 7. COMANDI SLASH (SETUP)
# ---------------------------------------------------------
@bot.event
async def on_ready():
    print(f"✅ Bot operativo come {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"🔄 Sincronizzati {len(synced)} comandi Slash.")
    except Exception as e:
        print(f"❌ Errore sync: {e}")


# ---------------------------------------------------------
# 8. AVVIO
# ---------------------------------------------------------
if __name__ == "__main__":
    keep_alive()
    TOKEN = os.environ.get("DISCORD_TOKEN")
    if TOKEN:
        bot.run(TOKEN)
    else:
        print("❌ Inserisci il DISCORD_TOKEN nelle variabili d'ambiente!")
