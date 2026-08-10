import os
import re
import datetime
import pytz
import threading
import asyncio
import json
import io
from flask import Flask
import discord
from discord import app_commands
from discord.ext import commands, tasks
import openai
from supabase import create_client, Client
import random
import string
from captcha.image import ImageCaptcha

# ---------------------------------------------------------
# VARIABILE GLOBALE PER ATTIVARE/DISATTIVARE L'IA
# ---------------------------------------------------------
ATTIVA_IA = False  # Impostato su True per testare le nuove funzioni

# ---------------------------------------------------------
# 1. SERVER FLASK INTEGRATO (Keep-Alive)
# ---------------------------------------------------------
app = Flask(__name__)

@app.route('/')
def home():
    return "Global Roleplay Lounge Online! 🌍"

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

STAFF_GENERAL_ROLE_ID = 1536159205289885796  
ID_CANALE_SALUTI = 1536159205289885796
ID_CANALE_WELCOME = 1536159444621205637  # Inserisci qui l'ID del canale welcome separato
LOG_CHANNEL_ID = 1536159424983339109

# ID specifici delle categorie di canali fornite per i ticket
TICKET_IDS = {
    "Generale": 1536159392100253866,
    "Partnership": 1536159394079969354,
    "Blacklist": 1536159388946145331,
    "Bando Staff": 1536159395438657598
}

# Lista dei ruoli da assegnare a verifica completata (sostituisci con i veri ID)
VERIFIED_ROLE_IDS = [1536159207315742750]  


# Nomi dei file locali presenti nella stessa cartella del bot
NOME_FILE_BANNER = "399B3005-E3EB-4438-A080-7079F9F8E462.png"
NOME_FILE_BANNER_VERIFICA = "298087E6-C4DB-42C8-82E9-3A637AD0E4DA.png"

TZ_ZONA = pytz.timezone("Europe/Rome")
ORARIO_BUONGIORNO = datetime.time(hour=8, minute=0, second=0, tzinfo=TZ_ZONA)
ORARIO_BUONASERA  = datetime.time(hour=21, minute=0, second=0, tzinfo=TZ_ZONA)

STAFF_ROLE_IDS = [
    1455297914455986408, 1455297915726598370, 1500051309808582778,
    1531229874046631947, 1500051544551456861, 1500051724877168680,
    1455297916708192373, 1531247431814217828, 1455297933196001411,
]

TARGET_CHANNEL_ID = 0
TARGET_MESSAGE_ID = 0

image_captcha = ImageCaptcha(width=280, height=90)

groq_client = openai.OpenAI(
    api_key=os.environ.get("GROQ_API_KEY"),
    base_url="https://api.groq.com/openai/v1"
)

# --- INIZIALIZZAZIONE SUPABASE ---
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if SUPABASE_URL and SUPABASE_KEY:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
else:
    supabase = None
    print("⚠️ [ATTENZIONE]: Credenziali Supabase mancanti.")

active_captchas = {}

async def db_get_ticket(channel_id: int):
    if not supabase: return None
    try:
        response = await asyncio.to_thread(lambda: supabase.table("ticket_ai_context").select("*").eq("channel_id", channel_id).execute())
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"❌ [ERRORE DB LETTURA]: {e}")
        return None

async def db_upsert_ticket(channel_id: int, stato: dict, history: list):
    if not supabase: return
    try:
        await asyncio.to_thread(lambda: supabase.table("ticket_ai_context").upsert({
            "channel_id": channel_id,
            "stato": stato,
            "history": history
        }).execute())
    except Exception as e:
        print(f"❌ [ERRORE DB SCRITTURA]: {e}")

async def db_delete_ticket(channel_id: int):
    if not supabase: return
    try:
        await asyncio.to_thread(lambda: supabase.table("ticket_ai_context").delete().eq("channel_id", channel_id).execute())
    except Exception as e:
        print(f"❌ [ERRORE DB ELIMINAZIONE]: {e}")

# ---------------------------------------------------------
# FUNZIONI DI LOG E ARCHIVIAZIONE TRAMITE WEBHOOK
# ---------------------------------------------------------
async def log_ticket_apertura(guild: discord.Guild, channel: discord.TextChannel, user: discord.Member, categoria: str):
    log_channel = guild.get_channel(LOG_CHANNEL_ID)
    if log_channel:
        embed = discord.Embed(
            title="📂 Nuovo Ticket Aperto",
            description=f"Un utente ha aperto un nuovo ticket di supporto.",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow()
        )
        embed.add_field(name="Canale", value=channel.mention, inline=True)
        embed.add_field(name="Utente", value=f"{user.mention} (`{user.id}`)", inline=True)
        embed.add_field(name="Categoria", value=f"`{categoria}`", inline=True)
        await log_channel.send(embed=embed)

async def chiudi_ticket_definitivo(channel: discord.TextChannel, closed_by_name: str, closed_by_mention: str, guild: discord.Guild):
    messages_list = []
    async for msg in channel.history(limit=150, oldest_first=True):
        embeds_data = [e.to_dict() for e in msg.embeds]
        messages_list.append({
            "author": msg.author.display_name,
            "avatar_url": str(msg.author.display_avatar.url) if msg.author.display_avatar else None,
            "content": msg.content,
            "embeds": embeds_data
        })

    transcript_data = {
        "ticket_name": channel.name,
        "closed_by": closed_by_name,
        "messages": messages_list
    }

    file_bytes = io.BytesIO(json.dumps(transcript_data, indent=4, ensure_ascii=False).encode("utf-8"))
    file = discord.File(file_bytes, filename=f"transcript-{channel.id}.json")

    log_channel = guild.get_channel(LOG_CHANNEL_ID)
    if log_channel:
        embed = discord.Embed(
            title="🔒 Ticket Chiuso ed Archiviato",
            description=f"Il ticket **`{channel.name}`** è stato chiuso da {closed_by_mention}.\n\n📜 **Cronologia Messaggi Ricostruita (Webhook):**",
            color=discord.Color.dark_orange(),
            timestamp=discord.utils.utcnow()
        )
        await log_channel.send(embed=embed)

        webhooks = await log_channel.webhooks()
        webhook = webhooks[0] if webhooks else await log_channel.create_webhook(name="Global RP Transcript Bot")

        for msg_data in messages_list:
            content = msg_data.get("content", "")
            raw_username = msg_data.get("author", "Utente Sconosciuto")
            username = raw_username.replace("discord", "Utente").replace("Discord", "Utente")
            avatar_url = msg_data.get("avatar_url", None)
            embeds_list = [discord.Embed.from_dict(e) for e in msg_data.get("embeds", [])]

            if content or embeds_list:
                try:
                    await webhook.send(
                        content=content if content else None,
                        username=username,
                        avatar_url=avatar_url,
                        embeds=embeds_list
                    )
                except Exception as e:
                    print(f"⚠️ [ERRORE INVIO WEBHOOK TRANSCRIPT]: {e}")

        final_embed = discord.Embed(
            description="📦 **File JSON di Backup e Ripristino Rapido**",
            color=discord.Color.dark_teal()
        )
        await log_channel.send(embed=final_embed, file=file, view=TranscriptReopenView())

    await db_delete_ticket(channel.id)
    try:
        await channel.delete()
    except Exception as e:
        print(f"⚠️ [ERRORE ELIMINAZIONE TICKET]: {e}")

DESCRIZIONE_UFFICIALE_GLOBAL_RP = (
    "🌍 **Benvenuto su Global Roleplay Lounge!** ✨\n\n"
    "Hai trovato il punto di riferimento definitivo per:\n"
    "→ 🎭 Vivere esperienze di Roleplay immersive e uniche\n"
    "→ 🤝 Creare partnership strategiche tra community\n"
    "→ 👥 Conoscere nuovi giocatori e collaboratori\n"
    "→ 🌐 Entrare in un network globale dinamico e professionale\n\n"
    "---\n\n"
    "🎯 **Unisciti al nostro universo di gioco!**\n"
    "🔗 **Link:** https://discord.gg/globalroleplay"
)

ai_tools = [
    {
        "type": "function",
        "function": {
            "name": "smista_partnership",
            "description": "Esegui questa funzione NON APENA la descrizione del partner, la categoria scelta e la reciprocità sono tutte confermate.",
            "parameters": {
                "type": "object",
                "properties": {
                    "categoria": {"type": "string", "description": "La categoria scelta."},
                    "nome_server": {"type": "string", "description": "Il nome esatto del server."},
                    "canale_id": {"type": "integer", "description": "ID numerico del canale."}
                },
                "required": ["categoria", "nome_server", "canale_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "close_ticket",
            "description": "Chiude e archivia il ticket.",
            "parameters": {
                "type": "object",
                "properties": {"reason": {"type": "string", "description": "Motivo."}},
                "required": ["reason"]
            }
        }
    }
]

async def genera_risposta_staff(stato: dict, history: list, messaggio_utente: str) -> dict:
    dossier_riassunto = (
        f"STATO DOSSIER:\n"
        f"- Descrizione: {'OK' if stato.get('descrizione_partner') else 'MANCANTE'}\n"
        f"- Link: {stato.get('link') or 'Assente'}\n"
        f"- Server: {stato.get('nome_server') or 'Sconosciuto'}\n"
        f"- Membri: {stato.get('membri') or 'Non calcolati'}\n"
        f"- Categoria: {stato.get('categoria') or 'MANCANTE'}\n"
        f"- Reciprocità: {'OK' if stato.get('reciprocita_confermata') else 'MANCANTE'}"
    )

    system_prompt = f"Sei l'addetto alle partnership di Global Roleplay Lounge 🌍.\n{dossier_riassunto}"

    messages = [{"role": "system", "content": system_prompt}]
    for msg in history[-10:]:
        messages.append(msg)
    messages.append({"role": "user", "content": messaggio_utente})

    try:
        response = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=messages,
            tools=ai_tools,
            tool_choice="auto",
            temperature=0.1,
            max_tokens=300
        )
        message_out = response.choices[0].message
        if message_out.tool_calls:
            for tool_call in message_out.tool_calls:
                func_name = tool_call.function.name
                func_args = json.loads(tool_call.function.arguments)
                if func_name == "close_ticket":
                    return {"testo": "Chiudo il ticket. A presto! 👋", "azione": "chiudi", "args": {}}
                if func_name == "smista_partnership":
                    return {"testo": "Perfetto! Tutti i dati sono verificati. Pubblico subito la partnership! 🚀", "azione": "smista", "args": func_args}
        return {"testo": message_out.content if message_out.content else "Dimmi pure!", "azione": "nessuna", "args": {}}
    except Exception as e:
        print(f"❌ [ERRORE GROQ API]: {e}")
        return {"testo": "Ops, c'è stato un piccolo errore.", "azione": "nessuna", "args": {}}

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
        title="👑 Gerarchia dello Staff - Global Roleplay Lounge",
        description="Elenco aggiornato in tempo reale dello staff.",
        color=discord.Color.from_str("#10b981"),
        timestamp=discord.utils.utcnow(),
    )

    for role in roles:
        members = role_members.get(role.id, [])
        value_text = ", ".join(members) if members else "*Nessun membro*"
        embed.add_field(name=f"➤ {role.mention}", value=value_text, inline=False)

    return embed

# ---------------------------------------------------------
# 5. MODALI E VIEW PERSISTENTI (timeout=None)
# ---------------------------------------------------------
class CaptchaModal(discord.ui.Modal, title="Verifica Anti-Bot (Captcha)"):
    codice_inserito = discord.ui.TextInput(
        label="Digita il codice che vedi sopra nell'immagine",
        placeholder="Es: A3f9K",
        min_length=4,
        max_length=6,
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        user_id = interaction.user.id
        codice_esatto = active_captchas.get(user_id)

        if not codice_esatto:
            return await interaction.response.send_message("❌ Il tuo codice captcha è scaduto o non valido. Clicca nuovamente sul pulsante di verifica nel canale.", ephemeral=True)

        if self.codice_inserito.value.strip().upper() == codice_esatto.upper():
            active_captchas.pop(user_id, None)

            guild = interaction.guild
            member = interaction.user

            roles_to_add = [guild.get_role(r_id) for r_id in VERIFIED_ROLE_IDS if guild.get_role(r_id) is not None]
            
            # INSERISCI QUI L'ID DEL RUOLO SPECIFICO DA RIMUOVERE (es. il ruolo non verificato)
            ID_RUOLO_DA_RIMUOVERE = 1536162317228711936  # Sostituisci 0 con l'ID reale del ruolo da togliere
            ruolo_da_rimuovere = guild.get_role(ID_RUOLO_DA_RIMUOVERE)

            try:
                # Rimuove il ruolo specifico se l'utente ce l'ha e l'ID è valido
                if ruolo_da_rimuovere and ruolo_da_rimuovere in member.roles:
                    await member.remove_roles(ruolo_da_rimuovere, reason="Verifica Captcha completata.")

                # Aggiunge i ruoli verificati
                if roles_to_add:
                    await member.add_roles(*roles_to_add, reason="Verifica Captcha completata con successo.")
                
                await interaction.response.send_message("✅ **Verifica completata con successo!** Ruoli aggiornati e benvenuto su Global Roleplay Lounge.", ephemeral=True)
            except Exception as e:
                await interaction.response.send_message(f"⚠️ Verifica riuscita, ma c'è stato un errore nella gestione dei ruoli: {e}", ephemeral=True)
        else:
            await interaction.response.send_message("❌ **Codice errato!** Riprova cliccando nuovamente sul pulsante.", ephemeral=True)

class VerificationModalButtonView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)

    @discord.ui.button(label="✍️ Inserisci Codice", style=discord.ButtonStyle.primary, custom_id="btn_open_captcha_modal")
    async def open_modal(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CaptchaModal())

class VerificationView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Verificati ora 🛡️", style=discord.ButtonStyle.green, custom_id="btn_start_verification")
    async def verify_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        user_roles_ids = [r.id for r in interaction.user.roles]
        if any(r_id in user_roles_ids for r_id in VERIFIED_ROLE_IDS):
            return await interaction.response.send_message("⚠️ Sei già verificato in questo server!", ephemeral=True)

        codice = "".join(random.choices(string.ascii_uppercase + string.digits, k=5))
        active_captchas[interaction.user.id] = codice

        data = image_captcha.generate(codice)
        file = discord.File(fp=data, filename="captcha.png")

        await interaction.response.send_message(
            content="🔒 **Sistema di Sicurezza Anti-Bot**\nOsserva l'immagine sottostante e clicca il pulsante **'Inserisci Codice'** per digitare i caratteri.",
            file=file,
            view=VerificationModalButtonView(),
            ephemeral=True
        )

class TicketCloseView(discord.ui.View):
    def __init__(self): 
        super().__init__(timeout=None)

    @discord.ui.button(label="🔒 Chiudi ed Elimina", style=discord.ButtonStyle.red, custom_id="btn_ticket_close")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("🔒 Chiusura del ticket in corso...", ephemeral=True)
        await chiudi_ticket_definitivo(interaction.channel, str(interaction.user), interaction.user.mention, interaction.guild)

class TicketControlView(discord.ui.View):
    def __init__(self): 
        super().__init__(timeout=None)
        self.add_item(TicketCloseView().children[0])

class TranscriptReopenView(discord.ui.View):
    def __init__(self): 
        super().__init__(timeout=None)

    @discord.ui.button(label="Riapri Ticket da Transcript", style=discord.ButtonStyle.green, custom_id="btn_reopen_transcript")
    async def reopen_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        message = interaction.message
        if not message.attachments: return await interaction.followup.send("❌ File di transcript non trovato.", ephemeral=True)
        
        attachment = message.attachments[0]
        if not attachment.filename.endswith(".json"): return await interaction.followup.send("❌ Il file allegato non è un transcript valido.", ephemeral=True)
        
        try:
            file_bytes = await attachment.read()
            ticket_data = json.loads(file_bytes.decode("utf-8"))
        except Exception as e:
            return await interaction.followup.send(f"❌ Errore nella lettura del transcript: {e}", ephemeral=True)

        guild = interaction.guild
        
        # Cerca la categoria originale tramite il nome del ticket o usa la prima disponibile
        target_category_id = TICKET_IDS.get("Generale")
        category = guild.get_channel(target_category_id)
        
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True, manage_webhooks=True),
        }
        staff_role = guild.get_role(STAFF_GENERAL_ROLE_ID)
        if staff_role:
            overwrites[staff_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

        new_channel = await guild.create_text_channel(
            name=f"riaperto-{ticket_data.get('ticket_name', 'ticket')}", 
            category=category if isinstance(category, discord.CategoryChannel) else None, 
            overwrites=overwrites
        )
        
        webhooks = await new_channel.webhooks()
        webhook = webhooks[0] if webhooks else await new_channel.create_webhook(name="Ticket Reopen Simulator")

        messages = ticket_data.get("messages", [])
        for msg_data in messages:
            content = msg_data.get("content", "")
            raw_username = msg_data.get("author", "Utente Sconosciuto")
            username = raw_username.replace("discord", "Utente").replace("Discord", "Utente")
            avatar_url = msg_data.get("avatar_url", None)
            if content or msg_data.get("embeds"):
                await webhook.send(
                    content=content if content else None,
                    username=username,
                    avatar_url=avatar_url,
                    embeds=[discord.Embed.from_dict(e) for e in msg_data.get("embeds", [])]
                )

        await interaction.followup.send(f"✅ Ticket riaperto con successo in {new_channel.mention}!", ephemeral=True)

class TicketSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Generale", description="Assistenza generica", emoji="📩", value="Generale"),
            discord.SelectOption(label="Partnership", description="Richieste partnership", emoji="🤝", value="Partnership"),
            discord.SelectOption(label="Bando Staff", description="Candidati per lo staff", emoji="📋", value="Bando Staff"),
            discord.SelectOption(label="Blacklist", description="Richieste o ricorsi blacklist", emoji="⛔", value="Blacklist"),
        ]
        super().__init__(placeholder="Scegli la categoria del Ticket...", min_values=1, max_values=1, options=options, custom_id="select_ticket_category")

    async def callback(self, interaction: discord.Interaction):
        category_type = self.values[0]
        guild = interaction.guild
        user = interaction.user
        
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            user: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }
        staff_role = guild.get_role(STAFF_GENERAL_ROLE_ID)
        if staff_role: overwrites[staff_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True)
        
        # Recupera l'ID specifico della categoria in base all'opzione selezionata
        target_category_id = TICKET_IDS.get(category_type)
        category = guild.get_channel(target_category_id) if target_category_id else None

        ticket_channel = await guild.create_text_channel(
            name=f"ticket-{category_type.lower().replace(' ', '-')}-{user.name}", 
            overwrites=overwrites, 
            category=category if isinstance(category, discord.CategoryChannel) else None
        )

        await interaction.response.send_message(f"✅ Ticket creato: {ticket_channel.mention}", ephemeral=True)
        
        await log_ticket_apertura(guild, ticket_channel, user, category_type)
        
        stato_iniziale = {
            "descrizione_partner": None, "link": None, "nome_server": None, "membri": None, "categoria": category_type, "reciprocita_confermata": False
        }
        
        await db_upsert_ticket(ticket_channel.id, stato_iniziale, [])

        descrizioni_embed = {
            "Generale": "Hai aperto un ticket di **Assistenza Generale**. Esponi il tuo problema o la tua domanda, lo staff ti risponderà il prima possibile.",
            "Partnership": "Hai avviato una richiesta di **Partnership** 🤝.\nSegui le indicazioni per procedere con l'accordo tra community.",
            "Bando Staff": "Hai scelto di candidarti per il **Bando Staff** 📋.\nRaccontaci le tue esperienze e perché vorresti entrare a far parte del nostro team.",
            "Blacklist": "Hai aperto un ticket per la **Blacklist** ⛔.\nEsponi la tua situazione o richiedi chiarimenti in merito."
        }

        embed = discord.Embed(
            title=f"🌍 Ticket: {category_type} — Global RP",
            description=descrizioni_embed.get(category_type, "Benvenuto nel supporto."),
            color=discord.Color.from_str("#10b981")
        )
        
        await ticket_channel.send(content=f"<@&{STAFF_GENERAL_ROLE_ID}> | {user.mention}", embed=embed, view=TicketControlView())
        
        if category_type == "Partnership":
            await ticket_channel.send(content=DESCRIZIONE_UFFICIALE_GLOBAL_RP)
            if ATTIVA_IA:
                risposta_iniziale = await genera_risposta_staff(stato_iniziale, [], "Apertura ticket partnership.")
                msg_sent = await ticket_channel.send(content=risposta_iniziale["testo"])
                history_iniziale = [
                    {"role": "user", "content": "Apertura ticket partnership."},
                    {"role": "assistant", "content": msg_sent.content}
                ]
                await db_upsert_ticket(ticket_channel.id, stato_iniziale, history_iniziale)
            else:
                await ticket_channel.send(content="🤖 L'assistente IA per le partnership è disattivato. Uno staffer ti risponderà a breve.")
        else:
            await ticket_channel.send(content=f"💬 Ciao {user.mention}, descrivi in modo dettagliato la tua richiesta per il reparto **{category_type}**. Un membro dello staff ti assisterà a breve.")

class TicketSelectView(discord.ui.View):
    def __init__(self): 
        super().__init__(timeout=None)
        self.add_item(TicketSelect())

# ---------------------------------------------------------
# 6. DEFINIZIONE DEL BOT & REGISTRAZIONE VIEW PERSISTENTI
# ---------------------------------------------------------
class CustomBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        # Registrazione di tutte le view persistenti
        self.add_view(VerificationView())
        self.add_view(TicketSelectView())
        self.add_view(TicketControlView())
        self.add_view(TicketCloseView())
        self.add_view(TranscriptReopenView())

        if not invia_buongiorno_automatico.is_running(): invia_buongiorno_automatico.start()
        if not invia_buonasera_automatica.is_running(): invia_buonasera_automatica.start()
        if not aggiorna_messaggio_automatico.is_running(): aggiorna_messaggio_automatico.start()

        await self.tree.sync()
        print("🚀 [BOT READY]: Bot avviato con tutte le view persistenti registrate correttamente.")

bot = CustomBot()

@bot.event
async def on_member_join(member: discord.Member):
    canale = member.guild.get_channel(ID_CANALE_WELCOME)
    if canale:
        embed = discord.Embed(
            title="🌍 Benvenuto su Global Roleplay Lounge!",
            description=f"Ciao {member.mention}, un caloroso benvenuto nella nostra community! 🎉\n\n"
                        f"Ricordati di dare un'occhiata ai canali informativi e preparati a vivere fantastiche avventure di Roleplay insieme a noi!",
            color=discord.Color.from_str("#10b981"),
            timestamp=datetime.datetime.now(TZ_ZONA)
        )
        file_banner = None
        if os.path.exists(NOME_FILE_BANNER):
            file_banner = discord.File(NOME_FILE_BANNER, filename="banner.gif")
            embed.set_image(url="attachment://banner.gif")
            
        await canale.send(content=f"{member.mention}", embed=embed, file=file_banner)

# Aggiungi questa costante in cima al codice insieme alle altre (es. vicino a NOME_FILE_BANNER)
NOME_FILE_BANNER_TICKET = "C4A8FA6E-8FC0-455E-88B1-6FD6600A2327.png"  # Sostituisci con il nome del file del tuo banner per i ticket

@bot.tree.command(name="setup_ticket", description="Invia il pannello principale avanzato dei Ticket")
@app_commands.checks.has_permissions(administrator=True)
async def setup_ticket(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🌍 Global Roleplay Lounge — Assistenza & Supporto Ufficiale",
        description=(
            "Hai bisogno di aiuto o desideri metterti in contatto con lo staff?\n"
            "Seleziona la categoria più adatta alle tue esigenze nel menu a tendina sottostante.\n\n"
            "📋 **Categorie Disponibili:**\n"
            "📩 **Generale** — Per qualsiasi domanda, dubbio o assistenza generale.\n"
            "🤝 **Partnership** — Per avviare una collaborazione o accordo tra community.\n"
            "📋 **Bando Staff** — Per candidarti ed entrare a far parte del nostro team.\n"
            "⛔ **Blacklist** — Per richiedere chiarimenti, revisioni o presentare un ricorso.\n\n"
            "⚠️ *Ti chiediamo di aprire un solo ticket alla volta e di mantenere un comportamento educato.*"
        ), 
        color=discord.Color.from_str("#10b981")
    )
    embed.set_footer(text="Global Roleplay Lounge — Sistema Ticket")
    
    file_banner = None
    if os.path.exists(NOME_FILE_BANNER_TICKET):
        file_banner = discord.File(NOME_FILE_BANNER_TICKET, filename="ticket_banner.png")
        embed.set_image(url="attachment://ticket_banner.png")

    if file_banner:
        await interaction.channel.send(embed=embed, file=file_banner, view=TicketSelectView())
    else:
        await interaction.channel.send(embed=embed, view=TicketSelectView())
        
    await interaction.response.send_message("✅ Pannello dei ticket inviato con successo!", ephemeral=True)

@bot.tree.command(name="setup_verifica", description="Invia il pannello di verifica con Captcha nel canale corrente")
@app_commands.checks.has_permissions(administrator=True)
async def setup_verifica(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🛡️ Verifica della Community — Global Roleplay Lounge",
        description="Per accedere a tutti i canali del server e sbloccare l'accesso alla community, devi completare la verifica anti-bot cliccando sul pulsante sottostante.",
        color=discord.Color.from_str("#10b981")
    )
    embed.set_footer(text="Sistema di sicurezza automatico")
    
    file_verifica = None
    if os.path.exists(NOME_FILE_BANNER_VERIFICA):
        file_verifica = discord.File(NOME_FILE_BANNER_VERIFICA, filename="verifica.png")
        embed.set_image(url="attachment://verifica.png")

    if file_verifica:
        await interaction.channel.send(embed=embed, file=file_verifica, view=VerificationView())
    else:
        await interaction.channel.send(embed=embed, view=VerificationView())
        
    await interaction.response.send_message("✅ Pannello di verifica inviato con successo!", ephemeral=True)

@bot.tree.command(name="staff", description="Invia la gerarchia dello staff")
@app_commands.default_permissions(administrator=True)
async def staff_command(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    embed = await genera_embed_staff(interaction.guild)
    msg = await interaction.followup.send(embed=embed)
    global TARGET_CHANNEL_ID, TARGET_MESSAGE_ID
    TARGET_CHANNEL_ID, TARGET_MESSAGE_ID = interaction.channel.id, msg.id
    await interaction.followup.send("✅ Gerarchia generata!", ephemeral=True)

# ---------------------------------------------------------
# 7. TASK AUTOMATICI
# ---------------------------------------------------------
@tasks.loop(minutes=10)
async def aggiorna_messaggio_automatico():
    if not bot.is_ready() or TARGET_CHANNEL_ID == 0: return
    for guild in bot.guilds:
        try:
            channel = guild.get_channel(TARGET_CHANNEL_ID)
            if channel:
                message = await channel.fetch_message(TARGET_MESSAGE_ID)
                await message.edit(embed=await genera_embed_staff(guild))
        except: pass

@tasks.loop(time=ORARIO_BUONGIORNO)
async def invia_buongiorno_automatico():
    canale = bot.get_channel(ID_CANALE_SALUTI)
    if canale:
        embed = discord.Embed(
            title="🌍 ☕ Buon Inizio Giornata, Roleplayers!",
            description="Preparate i vostri personaggi: una nuova giornata ricca di storie ha inizio su Global Roleplay Lounge!",
            color=discord.Color.from_str("#10b981"),
            timestamp=datetime.datetime.now(TZ_ZONA)
        )
        await canale.send(content="@everyone", embed=embed, allowed_mentions=discord.AllowedMentions(everyone=True))

@tasks.loop(time=ORARIO_BUONASERA)
async def invia_buonasera_automatica():
    canale = bot.get_channel(ID_CANALE_SALUTI)
    if canale:
        embed = discord.Embed(
            title="🌍 🌙 Buonasera Community!",
            description="Le luci della città si accendono... Il Roleplay serale su Global Roleplay Lounge entra nel vivo!",
            color=discord.Color.from_str("#0f172a"),
            timestamp=datetime.datetime.now(TZ_ZONA)
        )
        await canale.send(content="@everyone", embed=embed, allowed_mentions=discord.AllowedMentions(everyone=True))

# ---------------------------------------------------------
# AVVIO FINALE
# ---------------------------------------------------------
if __name__ == "__main__":
    keep_alive()
    TOKEN = os.environ.get("DISCORD_TOKEN")
    if TOKEN: bot.run(TOKEN)
    else: print("❌ [ERRORE CRITICO]: Inserisci il DISCORD_TOKEN!")
