import os
import json
import asyncio
import threading
import io
import datetime
import pytz
from flask import Flask
import discord
from discord import app_commands
from discord.ext import commands, tasks

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
        # Registra le view per permettere al bot di intercettare i click anche dopo il riavvio
        self.add_view(StaffApplicationView())
        self.add_view(TicketControlView())
        self.add_view(TicketSelectView())
        self.add_view(ClosedTranscriptView())
        self.add_view(BlacklistApprovalView())
        
        # Sincronizzazione dei comandi slash
        await self.tree.sync()
        print("✅ Albero dei comandi e Views persistenti registrati con successo.")

# Inizializzazione dell'istanza del bot
bot = CustomBot()

STAFF_MGMT_ROLE_ID = 1455297916708192373
STAFF_GENERAL_ROLE_ID = 1455297926468468777  
LOG_CHANNEL_ID = 1487393847830122597        
TICKET_CATEGORY_ID = 1455298169415012547    

# Costanti Blacklist
CHAN_BL_UTENTI = 1455298385933504686
CHAN_BL_SERVER = 1455298390173941943
TAG_STAFF_BL = "<@&1455297933196001411> , <@&1455297952133284022>"
EMOJI_V4 = "<:V4:1530942846599827502>"

# Lista ufficiale dei ruoli staff con i tuoi ID originali
STAFF_ROLE_IDS = [
    1455297914455986408,
    1455297915726598370,
    1500051309808582778,
    1531229874046631947,
    1500051544551456861,
    1500051724877168680,
    1455297916708192373,
    1531247431814217828,
    1455297933196001411
]

# Variabili globali per l'aggiornamento automatico della gerarchia staff
TARGET_CHANNEL_ID = 0
TARGET_MESSAGE_ID = 0

# --- CONFIGURAZIONE SALUTI ---
ID_CANALE_SALUTI = 1455298208413520014
TZ_ITALIA = pytz.timezone("Europe/Rome")
ORARIO_BUONGIORNO = datetime.time(hour=8, minute=0, second=0, tzinfo=TZ_ITALIA)
ORARIO_BUONASERA  = datetime.time(hour=21, minute=0, second=0, tzinfo=TZ_ITALIA)

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

# --- TASK AUTOMATICO BUONGIORNO ---
@tasks.loop(time=ORARIO_BUONGIORNO)
async def invia_buongiorno_automatico():
    canale = bot.get_channel(ID_CANALE_SALUTI)
    if not canale: return
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
    if canale.guild.icon: embed.set_thumbnail(url=canale.guild.icon.url)
    embed.add_field(name="📅 Data", value=f"`{data_formattata}`", inline=True)
    embed.add_field(name="👥 Squadra Server", value=f"`{canale.guild.member_count}` Membri", inline=True)
    embed.add_field(name="📌 Note dalla Community", value="Controlla i canali testuali/vocali, rispetta la regulation e unisciti ai match! 🇮🇹", inline=False)
    embed.set_footer(text="Discord Italia 🇮🇹 • Make your day awesome!", icon_url=canale.guild.icon.url if canale.guild.icon else None)

    await canale.send(content="@everyone", embed=embed, allowed_mentions=discord.AllowedMentions(everyone=True))

# --- TASK AUTOMATICO BUONASERA ---
@tasks.loop(time=ORARIO_BUONASERA)
async def invia_buonasera_automatica():
    canale = bot.get_channel(ID_CANALE_SALUTI)
    if not canale: return
    ora_attuale = datetime.datetime.now(TZ_ITALIA)
    data_formattata = ora_attuale.strftime("%d/%m/%Y")

    embed = discord.Embed(
        title="🇮🇹 🌙 Good Night & Night Vibes — Discord Italia!",
        description="La giornata volge al termine, ma la notte su Discord Italia 🇮🇹 è appena iniziata! Sessioni di gaming notturno o chiacchiere chill?",
        color=discord.Color.from_str("#2b2d31"),
        timestamp=ora_attuale
    )
    if canale.guild.icon: embed.set_thumbnail(url=canale.guild.icon.url)
    embed.add_field(name="🎧 Canali Vocali", value="Entra nelle room vocali per fare due chiacchiere o unirti alle partite!", inline=False)
    embed.add_field(name="✨ Server Stats", value=f"Siamo in **{canale.guild.member_count}** su **{canale.guild.name}** 🇮🇹", inline=True)
    embed.add_field(name="📅 Data", value=f"`{data_formattata}`", inline=True)
    embed.set_footer(text="Discord Italia 🇮🇹 • Buona serata e GG a tutti!", icon_url=canale.guild.icon.url if canale.guild.icon else None)

    await canale.send(content="@everyone", embed=embed, allowed_mentions=discord.AllowedMentions(everyone=True))

# --- EVENTO WELCOME ---
@bot.event
async def on_member_join(member: discord.Member):
    WELCOME_CHANNEL_ID = 1455298181003743394  
    channel = member.guild.get_channel(WELCOME_CHANNEL_ID)
    if not channel: return

    image_filename = "1A88159A-78B8-4D55-A308-E39A31B4F1D8.png"
    file = discord.File(image_filename, filename="welcome.png") if os.path.exists(image_filename) else None

    embed = discord.Embed(
        title="🇮🇹 Benvenuto su Discord Italia V4!",
        description=f"Ciao {member.mention}, benvenuto nel nostro server ufficiale! Siamo felici di averti qui con noi.",
        color=discord.Color.from_rgb(0, 146, 70)
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    if file: embed.set_image(url="attachment://welcome.png")
    embed.set_footer(text=f"Utente #{len(member.guild.members)} • Discord Italia 🇮🇹")

    if file:
        await channel.send(content=f"🎉 Benvenuto {member.mention}!", embed=embed, file=file)
    else:
        await channel.send(content=f"🎉 Benvenuto {member.mention}!", embed=embed)

# ---------------------------------------------------------
# GESTIONE GERARCHIA STAFF (Il nostro comando personalizzato)
# ---------------------------------------------------------
async def genera_embed_staff(guild: discord.Guild) -> discord.Embed:
    roles = [guild.get_role(r_id) for r_id in STAFF_ROLE_IDS]
    roles = [r for r in roles if r is not None]
    roles.sort(key=lambda r: r.position, reverse=True)

    role_members = {r.id: [] for r in roles}

    async for member in guild.fetch_members(limit=None):
        if member.bot: continue
        user_staff_roles = [r for r in member.roles if r.id in STAFF_ROLE_IDS]
        if user_staff_roles:
            user_staff_roles.sort(key=lambda r: r.position, reverse=True)
            highest_role = user_staff_roles[0]
            if highest_role.id in role_members:
                role_members[highest_role.id].append(member.mention)

    embed = discord.Embed(
        title="👑 Gerarchia dello Staff",
        color=discord.Color.blue(),
        timestamp=discord.utils.utcnow()
    )

    for role in roles:
        members = role_members.get(role.id, [])
        value_text = ", ".join(members) if members else "*Nessun membro*"
        embed.add_field(name=f"➤ {role.name}", value=value_text, inline=False)

    return embed

@tasks.loop(minutes=10)
async def aggiorna_staff_automatico():
    global TARGET_CHANNEL_ID, TARGET_MESSAGE_ID
    if TARGET_CHANNEL_ID == 0 or TARGET_MESSAGE_ID == 0: return
    for guild in bot.guilds:
        try:
            channel = guild.get_channel(TARGET_CHANNEL_ID)
            if channel:
                message = await channel.fetch_message(TARGET_MESSAGE_ID)
                await message.edit(embed=await genera_embed_staff(guild))
        except Exception:
            pass

@bot.tree.command(name="staff", description="Invia la gerarchia dello staff con aggiornamento in tempo reale")
@app_commands.checks.has_permissions(administrator=True)
async def comando_staff(interaction: discord.Interaction):
    global TARGET_CHANNEL_ID, TARGET_MESSAGE_ID
    await interaction.response.defer(thinking=True)
    embed = await genera_embed_staff(interaction.guild)
    msg = await interaction.followup.send(embed=embed)
    TARGET_CHANNEL_ID = interaction.channel.id
    TARGET_MESSAGE_ID = msg.id
    await interaction.followup.send("✅ Pannello gerarchia staff avviato con successo!", ephemeral=True)

# ---------------------------------------------------------
# MODAL BANDO STAFF & TICKET SYSTEM
# ---------------------------------------------------------
class StaffApplicationModal(discord.ui.Modal, title="📋 MODULO CANDIDATURA STAFF"):
    info = discord.ui.TextInput(label="👤 Informazioni Personali", style=discord.TextStyle.paragraph, required=True, max_length=500)
    esperienza = discord.ui.TextInput(label="🛡️ Esperienza", style=discord.TextStyle.paragraph, required=True, max_length=500)
    conoscenze = discord.ui.TextInput(label="📚 Conoscenze Discord & Moderazione", style=discord.TextStyle.paragraph, required=True, max_length=1000)
    partnership = discord.ui.TextInput(label="🤝 Esperienza Partnership", style=discord.TextStyle.paragraph, required=True, max_length=500)
    motivazioni = discord.ui.TextInput(label="🎯 Motivazioni", style=discord.TextStyle.paragraph, required=True, max_length=500)

    async def on_submit(self, interaction: discord.Interaction):
        confirm_embed = discord.Embed(title="✅ Candidatura inviata!", description=f"Grazie! Il tuo bando verrà esaminato da un membro del <@&{STAFF_MGMT_ROLE_ID}>.", color=discord.Color.green())
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
# GESTIONE RICHIESTA BLACKLIST
# ---------------------------------------------------------
class BlacklistRequestModal(discord.ui.Modal, title="📋 RICHIESTA BLACKLIST"):
    tipo = discord.ui.TextInput(label="📲 TIPO (UTENTE/SERVER)", style=discord.TextStyle.short, required=True)
    nome_id = discord.ui.TextInput(label="🆔️ NOME UTENTE / SERVER", style=discord.TextStyle.short, required=True)
    motivo = discord.ui.TextInput(label="❓️ MOTIVO", style=discord.TextStyle.paragraph, required=True)
    prove = discord.ui.TextInput(label="🖇️ PROVE", style=discord.TextStyle.paragraph, required=True)

    async def on_submit(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title=f"{EMOJI_V4} RICHIESTA BLACKLIST {EMOJI_V4}",
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="📲 | TIPO", value=self.tipo.value, inline=False)
        embed.add_field(name="🆔️ | NOME UTENTE / SERVER", value=self.nome_id.value, inline=False)
        embed.add_field(name="❓️ | MOTIVO", value=self.motivo.value, inline=False)
        embed.add_field(name="🖇️ | PROVE", value=self.prove.value, inline=False)
        embed.set_footer(text=f"Richiesto da {interaction.user.display_name}", icon_url=interaction.user.display_avatar.url)

        await interaction.response.send_message("✅ Richiesta inviata con successo allo staff!", ephemeral=True)
        await interaction.channel.send(embed=embed, view=BlacklistApprovalView())

class BlacklistApprovalView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Accetta come Utente", style=discord.ButtonStyle.green, custom_id="btn_bl_accept_user")
    async def accept_user(self, interaction: discord.Interaction, button: discord.ui.Button):
        staff_role = interaction.guild.get_role(STAFF_GENERAL_ROLE_ID)
        if staff_role not in interaction.user.roles and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Solo lo Staff può gestire questa richiesta.", ephemeral=True)
            return

        message = interaction.message
        embed_original = message.embeds[0] if message.embeds else None
        
        nome_val = "N/A"
        motivo_val = "N/A"
        prove_val = "N/A"

        if embed_original:
            for field in embed_original.fields:
                if "NOME" in field.name: nome_val = field.value
                elif "MOTIVO" in field.name: motivo_val = field.value
                elif "PROVE" in field.name: prove_val = field.value

        chan = interaction.guild.get_channel(CHAN_BL_UTENTI)
        if not chan:
            await interaction.response.send_message("❌ Canale Blacklist Utenti non trovato!", ephemeral=True)
            return

        final_embed = discord.Embed(
            title=f"{EMOJI_V4} MODULO BLACKLIST UTENTE {EMOJI_V4}",
            color=discord.Color.red()
        )
        final_embed.add_field(name="👤| USERNAME UTENTE:", value=f"> {nome_val}", inline=False)
        final_embed.add_field(name="🆔️| ID UTENTE:", value=">\n> (Inserire ID)", inline=False)
        final_embed.add_field(name="❓️| MOTIVO BLACKLIST:", value=f"> {motivo_val}", inline=False)
        final_embed.add_field(name="🔗| PROVE:", value=f"> {prove_val}", inline=False)

        await chan.send(content=TAG_STAFF_BL, embed=final_embed)
        await interaction.response.send_message("✅ Approvato e inviato nel canale Blacklist Utenti!", ephemeral=True)
        await message.edit(view=None) # Disattiva i bottoni dopo l'uso

    @discord.ui.button(label="Accetta come Server", style=discord.ButtonStyle.blurple, custom_id="btn_bl_accept_server")
    async def accept_server(self, interaction: discord.Interaction, button: discord.ui.Button):
        staff_role = interaction.guild.get_role(STAFF_GENERAL_ROLE_ID)
        if staff_role not in interaction.user.roles and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Solo lo Staff può gestire questa richiesta.", ephemeral=True)
            return

        message = interaction.message
        embed_original = message.embeds[0] if message.embeds else None
        
        nome_val = "N/A"
        motivo_val = "N/A"
        prove_val = "N/A"

        if embed_original:
            for field in embed_original.fields:
                if "NOME" in field.name: nome_val = field.value
                elif "MOTIVO" in field.name: motivo_val = field.value
                elif "PROVE" in field.name: prove_val = field.value

        chan = interaction.guild.get_channel(CHAN_BL_SERVER)
        if not chan:
            await interaction.response.send_message("❌ Canale Blacklist Server non trovato!", ephemeral=True)
            return

        final_embed = discord.Embed(
            title=f"{EMOJI_V4} MODULO BLACKLIST SERVER {EMOJI_V4}",
            color=discord.Color.red()
        )
        final_embed.add_field(name="👥| NOME SERVER:", value=f"> {nome_val}", inline=False)
        final_embed.add_field(name="🆔️| ID SERVER:", value=">\n> (Inserire ID)", inline=False)
        final_embed.add_field(name="❓️| MOTIVO BLACKLIST:", value=f"> {motivo_val}", inline=False)
        final_embed.add_field(name="🔗| PROVE:", value=f"> {prove_val}", inline=False)

        await chan.send(content=TAG_STAFF_BL, embed=final_embed)
        await interaction.response.send_message("✅ Approvato e inviato nel canale Blacklist Server!", ephemeral=True)
        await message.edit(view=None) # Disattiva i bottoni dopo l'uso

# ---------------------------------------------------------
# GESTIONE TRANSCRIPT & CONTROLLO TICKET
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
            await interaction.response.send_message("❌ Errore: Il file JSON del transcript non è allegato.", ephemeral=True)
            return

        attachment = message.attachments[0]
        await interaction.response.send_message("🔄 Ricreazione canale in corso...", ephemeral=True)

        try:
            file_bytes = await attachment.read()
            data = json.loads(file_bytes.decode("utf-8"))
        except Exception as e:
            await interaction.followup.send(f"❌ Errore lettura JSON: {e}", ephemeral=True)
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
        if owner_member: overwrites[owner_member] = discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True)
        if staff_role: overwrites[staff_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True)

        category = guild.get_channel(TICKET_CATEGORY_ID)
        new_channel = await guild.create_text_channel(name=f"reopen-{channel_name}", overwrites=overwrites, category=category if isinstance(category, discord.CategoryChannel) else None)
        webhook = await new_channel.create_webhook(name="Transcript Replicator")

        await new_channel.send(embed=discord.Embed(title="🔄 RICOSTRUZIONE CHAT", description=f"Riaperto da {interaction.user.mention}", color=discord.Color.green()))

        for msg in messages:
            try:
                attachments_text = "\n".join(msg["attachments"]) if msg["attachments"] else ""
                msg_text = msg["content"] if msg["content"] else ""
                final_content = f"{msg_text}\n{attachments_text}".strip()
                if not final_content: continue
                await webhook.send(content=final_content, username=f"{msg['author_name']} (ID: {msg['author_id']})", avatar_url=msg["author_avatar"])
                await asyncio.sleep(0.3)
            except Exception: pass

        await webhook.delete()
        await new_channel.send("⚙️ **Pannello Gestione Ticket:**", view=TicketControlView())
        await interaction.followup.send(f"✅ Canale ricreato: {new_channel.mention}", ephemeral=True)

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
            if msg.author.bot and msg.components: continue
            messages_data.append({
                "author_name": msg.author.display_name,
                "author_id": msg.author.id,
                "author_avatar": msg.author.display_avatar.url,
                "content": msg.content,
                "attachments": [att.url for att in msg.attachments]
            })

        transcript_payload = {"channel_name": channel.name, "owner_id": owner_id, "messages": messages_data}
        filename = f"transcript-{channel.id}.json"
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(transcript_payload, f, ensure_ascii=False, indent=4)

        log_channel = interaction.guild.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            embed_log = discord.Embed(title=f"📦 Transcript Archiviato: {channel.name}", description=f"**Chiuso da:** {interaction.user.mention}", color=discord.Color.red())
            await log_channel.send(embed=embed_log, file=discord.File(filename), view=ClosedTranscriptView())

        if os.path.exists(filename): os.remove(filename)
        await channel.delete()

    @discord.ui.button(label="🙋‍♂️ Reclama", style=discord.ButtonStyle.green, custom_id="btn_ticket_claim")
    async def claim_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        staff_role = interaction.guild.get_role(STAFF_GENERAL_ROLE_ID)
        if staff_role not in interaction.user.roles and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Solo lo Staff può reclamare i ticket.", ephemeral=True)
            return
        button.disabled = True
        button.label = f"Reclamato da {interaction.user.display_name}"
        await interaction.message.edit(view=self)
        await interaction.response.send_message(embed=discord.Embed(description=f"📌 Preso in carico da {interaction.user.mention}.", color=discord.Color.gold()))

    @discord.ui.button(label="⏸️ Metti in Attesa", style=discord.ButtonStyle.secondary, custom_id="btn_ticket_hold")
    async def hold_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        staff_role = interaction.guild.get_role(STAFF_GENERAL_ROLE_ID)
        if staff_role not in interaction.user.roles and not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("❌ Solo lo Staff può mettere in attesa i ticket.", ephemeral=True)
            return
        await interaction.response.send_message(embed=discord.Embed(title="⏸️ Ticket in Attesa", description="Questo ticket è in attesa.", color=discord.Color.orange()))

class TicketSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Ticket Generale", description="Assistenza generica", emoji="📩", value="generale"),
            discord.SelectOption(label="Partnership", description="Richieste partnership", emoji="🤝", value="partnership"),
            discord.SelectOption(label="Bando Staff", description="Candidati per lo staff", emoji="📋", value="staff"),
            discord.SelectOption(label="Richiesta Blacklist", description="Segnala utente o server", emoji="🚫", value="blacklist"),
            discord.SelectOption(label="Amministrazione", description="Supporto direttivo", emoji="👑", value="admin"),
            discord.SelectOption(label="Grafiche & Bot", description="Richieste grafiche o bot", emoji="🎨", value="grafiche_bot"),
        ]
        super().__init__(placeholder="Scegli la categoria del Ticket...", min_values=1, max_values=1, options=options, custom_id="select_ticket_category")

    async def callback(self, interaction: discord.Interaction):
        category_type = self.values[0]
        guild = interaction.guild
        user = interaction.user

        if category_type == "blacklist":
            await interaction.response.send_modal(BlacklistRequestModal())
            return

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            user: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        staff_role = guild.get_role(STAFF_GENERAL_ROLE_ID)
        if staff_role: overwrites[staff_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True)

        category = guild.get_channel(TICKET_CATEGORY_ID)
        ticket_channel = await guild.create_text_channel(name=f"ticket-{category_type}-{user.name}", overwrites=overwrites, category=category if isinstance(category, discord.CategoryChannel) else None)

        await interaction.response.send_message(f"✅ Ticket creato: {ticket_channel.mention}", ephemeral=True)
        tag_message = f"<@&{STAFF_GENERAL_ROLE_ID}> | {user.mention}"

        if category_type == "staff":
            embed_staff = discord.Embed(title="📋 MODULO CANDIDATURA STAFF", description="> Clicca sul pulsante sottostante per compilare il modulo.", color=discord.Color.orange())
            await ticket_channel.send(content=tag_message, embed=embed_staff, view=StaffApplicationView())
            await ticket_channel.send("⚙️ **Pannello Gestione Ticket:**", view=TicketControlView())
        else:
            embed_gen = discord.Embed(title=f"🎫 Ticket {category_type.capitalize()}", description=f"Ciao {user.mention}, descrivi la tua richiesta.", color=discord.Color.green())
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
        description="Seleziona dal menu a tendina la categoria desiderata:\n\n📩 **Generale**\n🤝 **Partnership**\n📋 **Bando Staff**\n🚫 **Richiesta Blacklist**\n👑 **Amministrazione**\n🎨 **Grafiche & Bot**",
        color=discord.Color.from_rgb(0, 146, 70)
    )
    embed.set_footer(text="Discord Italia 🇮🇹 • Sistema di Supporto")
    await interaction.channel.send(embed=embed, view=TicketSelectView())
    await interaction.response.send_message("Pannello inviato!", ephemeral=True)

ticket_group = app_commands.Group(name="ticket", description="Comandi per gestire i ticket esistenti")

@ticket_group.command(name="add", description="Aggiungi un utente al ticket")
@app_commands.checks.has_permissions(manage_channels=True)
async def ticket_add(interaction: discord.Interaction, member: discord.Member):
    await interaction.channel.set_permissions(member, read_messages=True, send_messages=True)
    await interaction.response.send_message(f"✅ {member.mention} aggiunto al ticket.")

@ticket_group.command(name="remove", description="Rimuovi un utente dal ticket")
@app_commands.checks.has_permissions(manage_channels=True)
async def ticket_remove(interaction: discord.Interaction, member: discord.Member):
    await interaction.channel.set_permissions(member, overwrite=None)
    await interaction.response.send_message(f"🚫 {member.mention} rimosso dal ticket.")

@ticket_group.command(name="rename", description="Rinomina il ticket")
@app_commands.checks.has_permissions(manage_channels=True)
async def ticket_name(interaction: discord.Interaction, new_name: str):
    await interaction.channel.edit(name=f"ticket-{new_name}")
    await interaction.response.send_message(f"✏️ Ticket rinominato.")

bot.tree.add_command(ticket_group)

# ---------------------------------------------------------
# AVVIO FINALE
# ---------------------------------------------------------
if __name__ == "__main__":
    keep_alive()
    TOKEN = os.environ.get("DISCORD_TOKEN")
    if TOKEN:
        bot.run(TOKEN)
    else:
        print("❌ Inserisci il DISCORD_TOKEN nelle variabili d'ambiente!")
