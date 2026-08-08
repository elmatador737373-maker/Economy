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

# ---------------------------------------------------------
# VARIABILE GLOBALE PER ATTIVARE/DISATTIVARE L'IA
# ---------------------------------------------------------
ATTIVA_IA = True  # Impostato su True per testare le nuove funzioni

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

STAFF_GENERAL_ROLE_ID = 1455297926468468777  
TICKET_CATEGORY_ID = 1455298169415012547    
ID_CANALE_SALUTI = 1455298208413520014
LOG_CHANNEL_ID = 1487393847830122597

TZ_ITALIA = pytz.timezone("Europe/Rome")
ORARIO_BUONGIORNO = datetime.time(hour=8, minute=0, second=0, tzinfo=TZ_ITALIA)
ORARIO_BUONASERA  = datetime.time(hour=21, minute=0, second=0, tzinfo=TZ_ITALIA)

STAFF_ROLE_IDS = [
    1455297914455986408, 1455297915726598370, 1500051309808582778,
    1531229874046631947, 1500051544551456861, 1500051724877168680,
    1455297916708192373, 1531247431814217828, 1455297933196001411,
]

TARGET_CHANNEL_ID = 0
TARGET_MESSAGE_ID = 0

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
    print("⚠️ [ATTENZIONE]: Credenziali Supabase mancanti. L'IA non potrà salvare lo storico in modo persistente.")

# Funzioni Helper Database
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
        print(f"🗑️ [SUPABASE]: Dati del ticket {channel_id} eliminati con successo.")
    except Exception as e:
        print(f"❌ [ERRORE DB ELIMINAZIONE]: {e}")

# ---------------------------------------------------------
# 3. SISTEMA UNIFICATO DI CHIUSURA TICKET
# ---------------------------------------------------------
async def chiudi_ticket_definitivo(channel: discord.TextChannel, closed_by_name: str, closed_by_mention: str, guild: discord.Guild):
    print(f"🔒 [TICKET CHIUSO]: Il canale {channel.name} è in fase di chiusura da {closed_by_name}.")

    messages_list = []
    async for msg in channel.history(limit=150, oldest_first=True):
        if msg.author.bot and not msg.webhook_id:
            pass
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
            title="",
            description=f"📦 **Transcript Archiviato: {channel.name}**\n\n**Chiuso da:** {closed_by_mention}\nClicca il bottone sottostante per riaprire automaticamente questo ticket.",
            color=discord.Color.dark_orange()
        )
        await log_channel.send(embed=embed, file=file, view=TranscriptReopenView())

    # Pulizia del database Supabase
    await db_delete_ticket(channel.id)

    try:
        await channel.delete()
    except Exception as e:
        print(f"⚠️ [ERRORE ELIMINAZIONE TICKET]: {e}")


# ---------------------------------------------------------
# 4. DESCRIZIONE UFFICIALE & MOTORE IA CON GROQ (TOOL CALLING)
# ---------------------------------------------------------
DESCRIZIONE_UFFICIALE_DISCORD_ITALIA = (
    "🌟 **Benvenuto su Discord Italia!** 🇮🇹\n\n"
    "Hai finalmente trovato il posto perfetto dove:\n"
    "→ 💬 Rilassarti e chiacchierare\n"
    "→ 🤝 Fare partnership con altri server\n"
    "→ 👥 Conoscere nuove persone\n"
    "→ 🌐 Entrare in una community italiana attiva e accogliente\n\n"
    "---\n\n"
    "🎯 **Questo server è per tutti!**\n"
    "🔗 **Link:** https://discord.gg/discord-talia-1-3k-1348947150641303583"
)

# Definizione del Tool per l'IA
ai_tools = [
    {
        "type": "function",
        "function": {
            "name": "smista_partnership",
            "description": "Esegui questa funzione NON APENA la descrizione del partner, la categoria scelta e la reciprocità sono tutte confermate. Estrae i dati corretti e invia la partnership.",
            "parameters": {
                "type": "object",
                "properties": {
                    "categoria": {
                        "type": "string",
                        "description": "La categoria scelta: Shop, PC, Community, Xbox o PlayStation."
                    },
                    "nome_server": {
                        "type": "string",
                        "description": "Il nome esatto del server partner."
                    },
                    "canale_id": {
                        "type": "integer",
                        "description": "L'ID numerico esatto del canale di destinazione in base alle fasce membri o 0 se Shop/PC."
                    }
                },
                "required": ["categoria", "nome_server", "canale_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "close_ticket",
            "description": "Chiude e archivia il ticket. Usalo se l'utente richiede esplicitamente di chiudere o se il lavoro è terminato.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "Motivo della chiusura."
                    }
                },
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
        f"- Categoria: {stato.get('categoria') or 'MANCANTE (Shop, PC, Community, Xbox, PlayStation)'}\n"
        f"- Reciprocità: {'OK' if stato.get('reciprocita_confermata') else 'MANCANTE'}"
    )

    system_prompt = (
        "Sei l'addetto alle partnership di Discord Italia 🇮🇹.\n\n"
        "REGOLE CRUCIALI:\n"
        "1. RISPOSTE BREVI: Scrivi frasi corte, dirette e amichevoli. Niente poemi o elenchi puntati lunghi.\n"
        "2. ZERO RIPETIZIONI: Non chiedere mai dati che risultano già 'OK' nel dossier.\n"
        "3. CHIAMA IL TOOL: Appena Descrizione, Categoria e Reciprocità sono TUTTE 'OK', usa subito il tool 'smista_partnership'.\n"
        "4. Se l'utente vuole chiudere, usa il tool 'close_ticket'.\n\n"
        "=== DATABASE CANALI (PER IL TOOL) ===\n"
        "- Shop/PC: canale_id = 0\n"
        "- Community: 0-600 (`1455298333366292512`), 600-1500 (`1505914982443778157`), 1500-2300 (`1455298340588879954`), 2300-5000 (`1459223502107181180`), 5000+ (`1497864519433846845`)\n"
        "- Xbox: 0-600 (`1506366880842252299`), 600-1500 (`1506366972726874182`), 1500-2300 (`1460365011171151882`), 2300-5000 (`1487403274658381864`), 5000+ (`1455298295680204932`)\n"
        "- PlayStation: 0-600 (`1457119066043977973`), 600-1500 (`1455298305041895604`), 1500-2300 (`1455298300315046042`), 2300-5000 (`1485211001719619624`), 5000+ (`1489956038362009630`)\n\n"
        f"{dossier_riassunto}"
    )

    messages = [{"role": "system", "content": system_prompt}]
    for msg in history[-10:]:
        messages.append(msg)
    messages.append({"role": "user", "content": messaggio_utente})

    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=messages,
            tools=ai_tools,
            tool_choice="auto",
            temperature=0.1,
            max_tokens=300  # Token ridotti per costringere l'IA a risposte brevi e repentine
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
        return {"testo": "Ops, c'è stato un piccolo errore. Riprova tra un attimo!", "azione": "nessuna", "args": {}}



async def genera_embed_staff(guild: discord.Guild) -> discord.Embed:
    roles = [guild.get_role(r_id) for r_id in STAFF_ROLE_IDS]
    roles = [r for r in roles if r is not None]
    roles.sort(key=lambda r: r.position, reverse=True)

    role_members = {r.id: [] for r in roles}

    async for member in guild.fetch_members(limit=None):
        if member.bot:
            continue
        user_staff_roles = [r for r in member.roles if r.id in STAFF_ROLE_IDS]
        if user_staff_roles:
            user_staff_roles.sort(key=lambda r: r.position, reverse=True)
            highest_role = user_staff_roles[0]
            if highest_role.id in role_members:
                role_members[highest_role.id].append(member.mention)

    embed = discord.Embed(
        title="👑 Gerarchia dello Staff",
        description="Elenco aggiornato in tempo reale dello staff suddiviso per ruolo principale.",
        color=discord.Color.blue(),
        timestamp=discord.utils.utcnow(),
    )

    for role in roles:
        members = role_members.get(role.id, [])
        value_text = ", ".join(members) if members else "*Nessun membro*"
        embed.add_field(name=f"➤ {role.mention}", value=value_text, inline=False)

    return embed

# ---------------------------------------------------------
# 5. FUNZIONE GESTIONE DESTINAZIONE PARTNERSHIP
# ---------------------------------------------------------
async def gestisci_destinazione_partnership(guild: discord.Guild, nome_partner: str, categoria_scelta: str, membri_totali: int, descrizione_partner: str, canale_id_indicato: int):
    categoria_pulita = categoria_scelta.upper()
    if "SHOP" in categoria_pulita or "PC" in categoria_pulita:
        nome_formattato = nome_partner.strip().replace(" ", "-")
        prefix = "🛍️⎱" if "SHOP" in categoria_pulita else "💻⎱"
        nome_canale = f"{prefix}{nome_formattato}"
        categoria_server = discord.utils.get(guild.categories, name="PARTNERSHIPS")
        try:
            nuovo_canale = await guild.create_text_channel(
                name=nome_canale,
                category=categoria_server or discord.utils.get(guild.categories, id=TICKET_CATEGORY_ID),
                reason=f"Partnership ratificata: {categoria_scelta} ({membri_totali} membri)"
            )
            await nuovo_canale.send(content=descrizione_partner)
            return nuovo_canale
        except Exception as e:
            print(f"❌ [ERRORE CREAZIONE CANALE]: {e}")
            return None
    else:
        target_channel = guild.get_channel(canale_id_indicato)
        if target_channel:
            await target_channel.send(content=descrizione_partner)
            return target_channel
        return None

# ---------------------------------------------------------
# 6. DEFINIZIONE DEL BOT & VIEW PERSISTENTI
# ---------------------------------------------------------
class CustomBot(commands.Bot):
  def __init__(self):
    super().__init__(command_prefix="!", intents=intents)

  async def setup_hook(self):
    self.add_view(TicketControlView())
    self.add_view(TicketSelectView())
    self.add_view(TranscriptReopenView())
    self.add_view(TicketCloseView())

    if not invia_buongiorno_automatico.is_running(): invia_buongiorno_automatico.start()
    if not invia_buonasera_automatica.is_running(): invia_buonasera_automatica.start()
    if not aggiorna_messaggio_automatico.is_running(): aggiorna_messaggio_automatico.start()

    await self.tree.sync()
    print("🚀 [BOT READY]: Bot avviato, viste persistenti registrate e comandi sincronizzati.")

bot = CustomBot()

class TicketControlView(discord.ui.View):
    def __init__(self): 
        super().__init__(timeout=None)
        self.add_item(TicketCloseView().children[0])

class TranscriptReopenView(discord.ui.View):
  def __init__(self): super().__init__(timeout=None)

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
    category = message.channel.category  
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True, manage_webhooks=True),
    }

    new_channel = await guild.create_text_channel(name=f"riaperto-{ticket_data.get('ticket_name', 'ticket')}", category=category, overwrites=overwrites)
    webhooks = await new_channel.webhooks()
    webhook = webhooks[0] if webhooks else await new_channel.create_webhook(name="Ticket Reopen Simulator")

    messages = ticket_data.get("messages", [])
    for msg_data in messages:
      content = msg_data.get("content", "")
      username = msg_data.get("author", "Utente Sconosciuto")
      avatar_url = msg_data.get("avatar_url", None)
      if content or msg_data.get("embeds"):
        await webhook.send(
            content=content if content else None,
            username=username,
            avatar_url=avatar_url,
            embeds=[discord.Embed.from_dict(e) for e in msg_data.get("embeds", [])]
        )

    await interaction.followup.send(f"✅ Ticket riaperto con successo in {new_channel.mention}!", ephemeral=True)

class TicketCloseView(discord.ui.View):
  def __init__(self): super().__init__(timeout=None)

  @discord.ui.button(label="🔒 Chiudi ed Elimina", style=discord.ButtonStyle.red, custom_id="btn_ticket_close")
  async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
    await interaction.response.send_message("🔒 Chiusura del ticket in corso...", ephemeral=True)
    await chiudi_ticket_definitivo(interaction.channel, str(interaction.user), interaction.user.mention, interaction.guild)

class TicketSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Ticket Generale", description="Assistenza generica", emoji="📩", value="Generale"),
            discord.SelectOption(label="Partnership", description="Richieste partnership", emoji="🤝", value="Partnership"),
            discord.SelectOption(label="Bando Staff", description="Candidati per lo staff", emoji="📋", value="Staff"),
            discord.SelectOption(label="Amministrazione", description="Supporto direttivo", emoji="👑", value="Amministrazione"),
            discord.SelectOption(label="Grafiche & Bot", description="Richieste grafiche o bot", emoji="🎨", value="Grafiche & Bot"),
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
        
        category = guild.get_channel(TICKET_CATEGORY_ID)
        ticket_channel = await guild.create_text_channel(name=f"ticket-{category_type.lower()}-{user.name}", overwrites=overwrites, category=category if isinstance(category, discord.CategoryChannel) else None)

        await interaction.response.send_message(f"✅ Ticket creato: {ticket_channel.mention}", ephemeral=True)
        
        stato_iniziale = {
            "descrizione_partner": None, "link": None, "nome_server": None, "membri": None, "categoria": None, "reciprocita_confermata": False
        }
        
        await db_upsert_ticket(ticket_channel.id, stato_iniziale, [])

        embed = discord.Embed(
            title="🇮🇹 Benvenuto - Desk Partnership",
            description="Il nostro staff è stato notificato. Segui le indicazioni dell'assistente.",
            color=discord.Color.from_rgb(0, 146, 70)
        )
        await ticket_channel.send(content=f"<@&{STAFF_GENERAL_ROLE_ID}> | {user.mention}", embed=embed, view=TicketControlView())
        await ticket_channel.send(content=DESCRIZIONE_UFFICIALE_DISCORD_ITALIA)

        if ATTIVA_IA:
            risposta_iniziale = await genera_risposta_staff(stato_iniziale, [], "Apertura ticket.")
            msg_sent = await ticket_channel.send(content=risposta_iniziale["testo"])
            
            # Inizializza History
            history_iniziale = [
                {"role": "user", "content": "Apertura ticket."},
                {"role": "assistant", "content": msg_sent.content}
            ]
            await db_upsert_ticket(ticket_channel.id, stato_iniziale, history_iniziale)
        else:
            await ticket_channel.send(content="🤖 L'assistente IA è disattivato. Uno staffer ti risponderà a breve.")

class TicketSelectView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None); self.add_item(TicketSelect())

@bot.tree.command(name="setup_ticket", description="Invia il pannello principale avanzato dei Ticket")
@app_commands.checks.has_permissions(administrator=True)
async def setup_ticket(interaction: discord.Interaction):
    await interaction.response.send_message("✅ Pannello inviato", ephemeral=True)
    embed = discord.Embed(
        title="🇮🇹 Assistenza & Supporto Ufficiale - Discord Italia",
        description="Seleziona la categoria di assistenza.", color=discord.Color.from_rgb(0, 146, 70)
    )
    await interaction.channel.send(embed=embed, view=TicketSelectView())

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
# 7. GESTIONE MESSAGGI (CORE AI) E AGGIORNAMENTO DB
# ---------------------------------------------------------
    # Elaborazione IA (se attiva)
    if ATTIVA_IA:
        risultato_ia = await genera_risposta_staff(stato, history, message.content)
        
        # 1. Se l'IA vuole chiudere il ticket
        if risultato_ia["azione"] == "chiudi":
            await message.channel.send(content=risultato_ia["testo"])
            await asyncio.sleep(2)
            await chiudi_ticket_definitivo(message.channel, "AI_Assistant", "L'Assistente IA🤖", message.guild)
            return

        # 2. Se l'IA ha attivato il tool di smistamento partnership
        if risultato_ia["azione"] == "smista" and stato.get("reciprocita_confermata") and stato.get("descrizione_partner"):
            args = risultato_ia["args"]
            cat = args.get("categoria")
            nome = args.get("nome_server")
            canale_id_destinazione = int(args.get("canale_id", 0))
            
            # Esegue lo smistamento reale nei canali
            await gestisci_destinazione_partnership(message.guild, nome, cat, stato.get("membri", 0), stato["descrizione_partner"], canale_id_destinazione)
            
            await message.channel.send(content=risultato_ia["testo"])
            
            embed_log = discord.Embed(title="📋 Log Finale Partnership - Ticket Chiuso", description="Partnership completata e pubblicata con successo.", color=discord.Color.green())
            await message.channel.send(content="✅ **Partnership pubblicata nel canale di destinazione!**", embed=embed_log)
            
            await asyncio.sleep(5)
            await chiudi_ticket_definitivo(message.channel, "AI_Sistema_Partnership", "L'Assistente IA🤖", message.guild)
            return
        
        # 3. Risposta normale interlocutoria dell'IA
        msg_ia = await message.channel.send(content=risultato_ia["testo"])
        history.append({"role": "assistant", "content": msg_ia.content})

    # Salva stato e history su Supabase
    await db_upsert_ticket(channel_id, stato, history)


# ---------------------------------------------------------
# 8. TASK AUTOMATICI
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
    if canale: await canale.send(content="@everyone", embed=discord.Embed(title="🇮🇹 ☕ Buon Inizio Giornata!", description="Un caffè e si parte su Discord Italia 🇮🇹!", color=discord.Color.from_str("#5865F2"), timestamp=datetime.datetime.now(TZ_ITALIA)), allowed_mentions=discord.AllowedMentions(everyone=True))

@tasks.loop(time=ORARIO_BUONASERA)
async def invia_buonasera_automatica():
    canale = bot.get_channel(ID_CANALE_SALUTI)
    if canale: await canale.send(content="@everyone", embed=discord.Embed(title="🇮🇹 🌙 Buonasera Community!", description="La serata su Discord Italia è nel vivo!", color=discord.Color.from_str("#2b2d31"), timestamp=datetime.datetime.now(TZ_ITALIA)), allowed_mentions=discord.AllowedMentions(everyone=True))

# ---------------------------------------------------------
# AVVIO FINALE
# ---------------------------------------------------------
if __name__ == "__main__":
    keep_alive()
    TOKEN = os.environ.get("DISCORD_TOKEN")
    if TOKEN: bot.run(TOKEN)
    else: print("❌ [ERRORE CRITICO]: Inserisci il DISCORD_TOKEN!")
