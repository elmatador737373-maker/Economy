import os
import re
import datetime
import pytz
import threading
import asyncio
import openai
from flask import Flask
import discord
from discord import app_commands
from discord.ext import commands, tasks

# ---------------------------------------------------------
# VARIABILE GLOBALE PER ATTIVARE/DISATTIVARE L'IA
# ---------------------------------------------------------
ATTIVA_IA = False  # Imposta su False per disattivare completamente l'IA

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

memoria_ticket = {}

STAFF_GENERAL_ROLE_ID = 1455297926468468777  
TICKET_CATEGORY_ID = 1455298169415012547    
ID_CANALE_SALUTI = 1455298208413520014
TZ_ITALIA = pytz.timezone("Europe/Rome")
ORARIO_BUONGIORNO = datetime.time(hour=8, minute=0, second=0, tzinfo=TZ_ITALIA)
ORARIO_BUONASERA  = datetime.time(hour=21, minute=0, second=0, tzinfo=TZ_ITALIA)

STAFF_ROLE_IDS = [
    1455297914455986408,
    1455297915726598370,
    1500051309808582778,
    1531229874046631947,
    1500051544551456861,
    1500051724877168680,
    1455297916708192373,
    1531247431814217828,
    1455297933196001411,
]

TARGET_CHANNEL_ID = 0
TARGET_MESSAGE_ID = 0

groq_client = openai.OpenAI(
    api_key=os.environ.get("GROQ_API_KEY"),
    base_url="https://api.groq.com/openai/v1"
)

# ---------------------------------------------------------
# 3. DESCRIZIONE UFFICIALE & MOTORE IA CON GROQ
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
    "→ 🎮 Gamer | 📚 Studenti | 🎨 Artisti | 🎥 Content Creator | 🧑‍🤝‍🧑 E chiunque voglia stare in compagnia\n\n"
    "🔹 **Cosa troverai da noi?**\n"
    "→ ✨ Canali organizzati per ogni interesse\n"
    "→ 🤝 Sezioni dedicate a partnership e community\n"
    "→ 🎮 Stanze gaming sempre attive\n"
    "→ 🎵 Musica 24/7 con bot\n"
    "→ 🛠️ Staff disponibile e pronto ad aiutarti\n"
    "→ 🎨 Spazio creativo (arte, scrittura, video)\n"
    "→ 🎁 Eventi, giveaway e tante attività\n"
    "→ 🚀 Accesso semplice e veloce\n\n"
    "🔗 **Link:** https://discord.gg/discord-talia-1-3k-1348947150641303583"
)

async def genera_risposta_staff(stato: dict, messaggio_utente: str) -> str:
    dossier_riassunto = (
        f"STATO ATTUALE DEL DOSSIER:\n"
        f"- Descrizione Partnership Ricevuta: {'SÌ' if stato['descrizione_partner'] else 'MANCANTE (Chiedi all\'utente di incollare qui la descrizione/messaggio di partnership del suo server che contiene il link d\'invito)'}\n"
        f"- Link Server Estratto: {stato['link'] or 'Non ancora estratto dalla descrizione'}\n"
        f"- Nome Server: {stato['nome_server'] or 'Sconosciuto'}\n"
        f"- Membri Totali: {stato['membri'] or 'Non calcolati'}\n"
        f"- Categoria Scelta: {stato['categoria'] or 'MANCANTE (Chiedi se Shop, PC, Community, Xbox o PlayStation)'}\n"
        f"- Reciprocità Confermata: {'SÌ' if stato['reciprocita_confermata'] else 'NO (Chiedi la prova o la conferma della pubblicazione)'}"
    )

    system_prompt = (
        "SEI IL RESPONSABILE DI DIREZIONE E DESK DELLE PARTNERSHIPS DI 'DISCORD ITALIA 🇮🇹'.\n"
        "Il tuo tono è formale, autorevole, impeccabile, estremamente professionale ma umano ed elastico.\n"
        "REGOLE RIGIDE PER NON RIPETERE LE COSE:\n"
        "1. Guarda attentamente il DOSSIER ATTUALE. Se un dato è già presente, NON chiederlo mai più.\n"
        "2. Chiedi esclusivamente ciò che risulta MANCANTE (es. se manca la descrizione di partnership col link, chiedi di inviarla; se manca la categoria, chiedila; se manca la conferma di reciprocità, chiedila).\n"
        "3. Non reinviare mai la descrizione ufficiale del nostro server (è già stata inviata all'inizio).\n\n"

        "=== DATABASE CANALI E FASCE (SMISTAMENTO AUTOMATICO) ===\n"
        "- **SHOP:** Canale ID `1455298162813046854` (Crea un canale dedicato)\n"
        "- **PC:** Canale ID `1455298158748897413` (Crea un canale dedicato)\n"
        "- **COMMUNITY:** \n"
        "  • 0-600 (`1455298333366292512`) | 600-1500 (`1505914982443778157`) | 1500-2300 (`1455298340588879954`) | 2300-5000 (`1459223502107181180`) | 5k+ (`1497864519433846845`)\n"
        "- **XBOX:** \n"
        "  • 0-600 (`1506366880842252299`) | 600-1500 (`1506366972726874182`) | 1500-2300 (`1460365011171151882`) | 2300-5000 (`1487403274658381864`) | 5000+ (`1455298295680204932`)\n"
        "- **PLAYSTATION:** \n"
        "  • 0-600 (`1457119066043977973`) | 600-1500 (`1455298305041895604`) | 1500-2300 (`1455298300315046042`) | 2300-5000 (`1485211001719619624`) | 5000+ (`1489956038362009630`)\n\n"

        "=== COMANDO FINALE ===\n"
        "Quando la Descrizione (con link), la Categoria e la Reciprocità sono tutte confermate, concludi la risposta inserendo obbligatoriamente:\n"
        "`[GESTISCI_PARTNERSHIP: Categoria=X, Nome=Y, CanaleID=Z]`\n"
        "(Nota per Z: se la categoria è Shop o PC inserisci l'ID base del canale o lascia 0 perché verrà creato un canale apposito; se è Community, Xbox o PlayStation, calcola l'ID corretto della fascia in base al numero di membri totale)."
    )

    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"{dossier_riassunto}\n\nMessaggio utente: {messaggio_utente}"}
            ],
            temperature=0.5,
            max_tokens=600
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"❌ [ERRORE GROQ API]: {e}")
        return "Vi è stato un piccolo problema tecnico. Ti chiedo di ripetere."

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
# 4. FUNZIONE GESTIONE DESTINAZIONE PARTNERSHIP
# ---------------------------------------------------------
async def gestisci_destinazione_partnership(guild: discord.Guild, nome_partner: str, categoria_scelta: str, membri_totali: int, descrizione_partner: str, canale_id_indicato: int):
    categoria_pulita = categoria_scelta.upper()
    
    # Se Shop o PC, creiamo un canale dedicato
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
            print(f"✅ [CANALE CREATO & MESSAGGIO INVIATO]: Canale '{nome_canale}' generato e descrizione pubblicata.")
            return nuovo_canale
        except Exception as e:
            print(f"❌ [ERRORE CREAZIONE CANALE]: {e}")
            return None
    else:
        # Per Community, Xbox o PlayStation, inviamo direttamente nel canale della fascia membri stabilito
        target_channel = guild.get_channel(canale_id_indicato)
        if target_channel:
            await target_channel.send(content=descrizione_partner)
            print(f"✅ [MESSAGGIO INVIATO IN FASCIA]: Descrizione pubblicata con successo nel canale ID {canale_id_indicato}.")
            return target_channel
        else:
            print(f"⚠️ [ERRORE CANALE FASCIA]: Impossibile trovare il canale con ID {canale_id_indicato}.")
            return None

# ---------------------------------------------------------
# 5. DEFINIZIONE DEL BOT & VIEW PERSISTENTI
# ---------------------------------------------------------
class CustomBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        self.add_view(TicketControlView())
        self.add_view(TicketSelectView())
        
        if not invia_buongiorno_automatico.is_running():
            invia_buongiorno_automatico.start()
        if not invia_buonasera_automatica.is_running():
            invia_buonasera_automatica.start()
        if not aggiorna_messaggio_automatico.is_running():
            aggiorna_messaggio_automatico.start()

        await self.tree.sync()
        print("🚀 [BOT READY]: Bot avviato, viste persistenti registrate e comandi sincronizzati.")

bot = CustomBot()

class TicketControlView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)

import io
import json
import discord

# Configura l'ID del canale in cui inviare i log dei ticket chiusi
LOG_CHANNEL_ID = 1487393847830122597  # Sostituisci con l'ID del canale log


class TranscriptReopenView(discord.ui.View):

  def __init__(self):
    super().__init__(timeout=None)

  @discord.ui.button(
      label="Riapri Ticket da Transcript",
      style=discord.ButtonStyle.green,
      custom_id="btn_reopen_transcript",
  )
  async def reopen_ticket(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    await interaction.response.defer(ephemeral=True)

    # Cerca il file JSON allegato al messaggio di log
    message = interaction.message
    if not message.attachments:
      return await interaction.followup.send(
          "❌ File di transcript non trovato.", ephemeral=True
      )

    attachment = message.attachments[0]
    if not attachment.filename.endswith(".json"):
      return await interaction.followup.send(
          "❌ Il file allegato non è un transcript valido.", ephemeral=True
      )

    try:
      file_bytes = await attachment.read()
      ticket_data = json.loads(file_bytes.decode("utf-8"))
    except Exception as e:
      return await interaction.followup.send(
          f"❌ Errore nella lettura del transcript: {e}", ephemeral=True
      )

    # Crea un nuovo canale per il ticket riaperto
    guild = interaction.guild
    category = message.channel.category  
    # Fallback se il canale dei log non è nella stessa categoria
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        interaction.user: discord.PermissionOverwrite(
            view_channel=True, send_messages=True, read_message_history=True
        ),
        guild.me: discord.PermissionOverwrite(
            view_channel=True,
            send_messages=True,
            manage_channels=True,
            manage_webhooks=True,
        ),
    }

    new_channel = await guild.create_text_channel(
        name=f"riaperto-{ticket_data.get('ticket_name', 'ticket')}",
        category=category,
        overwrites=overwrites,
    )

    # Crea o recupera un webhook nel nuovo canale per simulare gli utenti
    webhooks = await new_channel.webhooks()
    webhook = webhooks[0] if webhooks else await new_channel.create_webhook(name="Ticket Reopen Simulator")

    # Invia i messaggi salvati simulando gli autori originali tramite webhook
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

    await interaction.followup.send(
        f"✅ Ticket riaperto con successo in {new_channel.mention}!", ephemeral=True
    )


class TicketCloseView(discord.ui.View):

  def __init__(self):
    super().__init__(timeout=None)

  @discord.ui.button(
      label="🔒 Chiudi ed Elimina",
      style=discord.ButtonStyle.red,
      custom_id="btn_ticket_close",
  )
  async def close_ticket(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    print(
        f"🔒 [TICKET CHIUSO]: Il canale {interaction.channel.name} è stato"
        f" chiuso da {interaction.user}."
    )

    if interaction.channel.id in memoria_ticket:
      del memoria_ticket[interaction.channel.id]

    # Raccogli la cronologia dei messaggi per il transcript
    messages_list = []
    async for message in interaction.channel.history(limit=150, oldest_first=True):
      if message.author.bot and not message.webhook_id:
        # Salva anche i messaggi del bot se necessario, o saltali
        pass
      
      embeds_data = [e.to_dict() for e in message.embeds]
      messages_list.append({
          "author": message.author.display_name,
          "avatar_url": str(message.author.display_avatar.url) if message.author.display_avatar else None,
          "content": message.content,
          "embeds": embeds_data
      })

    # Prepara i dati JSON del transcript
    transcript_data = {
        "ticket_name": interaction.channel.name,
        "closed_by": str(interaction.user),
        "messages": messages_list
    }

    file_bytes = io.BytesIO(json.dumps(transcript_data, indent=4, ensure_ascii=False).encode("utf-8"))
    file = discord.File(file_bytes, filename=f"transcript-{interaction.channel.id}.json")

    # Invia il log nel canale apposito
    log_channel = interaction.guild.get_channel(LOG_CHANNEL_ID)
    if log_channel:
      embed = discord.Embed(
          title="",
          description=f"📦 **Transcript Archiviato: {interaction.channel.name}**\n\n**Chiuso da:** {interaction.user.mention}\nClicca il bottone sottostante per riaprire automaticamente questo ticket.",
          color=discord.Color.dark_orange() # O il colore rosso/arancione della tua UI
      )
      await log_channel.send(
          embed=embed,
          file=file,
          view=TranscriptReopenView()
      )

    await interaction.channel.delete()

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
        ticket_channel = await guild.create_text_channel(
            name=f"ticket-{category_type.lower()}-{user.name}", 
            overwrites=overwrites, 
            category=category if isinstance(category, discord.CategoryChannel) else None
        )

        print(f"🎫 [APERTURA TICKET]: Creato canale #{ticket_channel.name} (ID: {ticket_channel.id}) per l'utente {user}")
        await interaction.response.send_message(f"✅ Ticket creato: {ticket_channel.mention}", ephemeral=True)
        
        memoria_ticket[ticket_channel.id] = {
            "descrizione_partner": None,
            "link": None,
            "nome_server": None,
            "membri": None,
            "categoria": None,
            "reciprocita_confermata": False
        }

        # 1. EMBED DI BENVENUTO NEL TICKET
        embed = discord.Embed(
            title="🇮🇹 Benvenuto - Desk Partnership",
            description="Il nostro staff è stato notificato. Segui le indicazioni dell'assistente.",
            color=discord.Color.from_rgb(0, 146, 70)
        )
        await ticket_channel.send(content=f"<@&{STAFF_GENERAL_ROLE_ID}> | {user.mention}", embed=embed, view=TicketControlView())

        # 2. INVIO DELLA DESCRIZIONE UFFICIALE DI DISCORD ITALIA ALL'APERTURA DEL TICKET
        await ticket_channel.send(content=DESCRIZIONE_UFFICIALE_DISCORD_ITALIA)

        # 3. PRIMO MESSAGGIO DELL'IA (Se attiva)
        if ATTIVA_IA:
            risposta_iniziale = await genera_risposta_staff(memoria_ticket[ticket_channel.id], "Apertura ticket.")
            await ticket_channel.send(content=risposta_iniziale)
        else:
            await ticket_channel.send(content="🤖 L'assistente IA è attualmente disattivato. Uno staffer ti risponderà al più presto.")

class TicketSelectView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None); self.add_item(TicketSelect())

@bot.tree.command(name="setup_ticket", description="Invia il pannello principale avanzato dei Ticket (Solo Admin)")
@app_commands.checks.has_permissions(administrator=True)
async def setup_ticket(interaction: discord.Interaction):
    await interaction.response.send_message("✅ Pannello avanzato in invio...", ephemeral=True)
    
    embed = discord.Embed(
        title="🇮🇹 Assistenza & Supporto Ufficiale - Discord Italia",
        description=(
            "Benvenuto nel centro assistenza di **Discord Italia**. "
            "Se hai bisogno di supporto, vuoi proporre una partnership o candidarti nello staff, "
            "puoi aprire un ticket dedicato selezionando l'opzione corretta dal menu sottostante.\n\n"
            "### 📌 Categorie Disponibili:\n"
            "📩 **Ticket Generale**\n"
            "└ *Per qualsiasi dubbio, domanda generale o assistenza sul server.*\n\n"
            "🤝 **Partnership**\n"
            "└ *Per richiedere una partnership ufficiale con il tuo server Discord.*\n\n"
            "📋 **Bando Staff**\n"
            "└ *Per inviare la tua candidatura ed entrare a far parte del nostro team.*\n\n"
            "👑 **Amministrazione**\n"
            "└ *Per questioni urgenti, importanti o comunicazioni dirette con i vertici.*\n\n"
            "🎨 **Grafiche & Bot**\n"
            "└ *Per richieste inerenti a grafiche personalizzate, banner o supporto bot.*\n\n"
            "⚠️ **Nota Importante:**\n"
            "• Apri un ticket solo se strettamente necessario.\n"
            "• Mantieni sempre un comportamento educato e rispettoso con lo staff."
        ),
        color=discord.Color.from_rgb(0, 146, 70)
    )
    embed.set_footer(text="Discord Italia • Sistema di Supporto Automatico", icon_url=interaction.guild.icon.url if interaction.guild.icon else None)
    
    await interaction.channel.send(embed=embed, view=TicketSelectView())
    print(f"📢 [PANNELLO INVIATO]: Pannello avanzato dei ticket pubblicato da {interaction.user} in #{interaction.channel.name}")


@bot.tree.command(name="staff", description="Invia la gerarchia dello staff e avvia l'aggiornamento in tempo reale.")
@app_commands.default_permissions(administrator=True)
async def staff_command(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    guild = interaction.guild
    embed = await genera_embed_staff(guild)
    msg = await interaction.followup.send(embed=embed)

    global TARGET_CHANNEL_ID, TARGET_MESSAGE_ID
    TARGET_CHANNEL_ID = interaction.channel.id
    TARGET_MESSAGE_ID = msg.id

    await interaction.followup.send(
        "✅ Gerarchia generata con successo! Questo messaggio si aggiornerà automaticamente in tempo reale.",
        ephemeral=True,
    )

# ---------------------------------------------------------
# 6. GESTIONE MESSAGGI & LOG DETTAGLIATI DEL DOSSIER TICKET
# ---------------------------------------------------------
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.channel.name.startswith("ticket-"): return
    
    channel_id = message.channel.id
    if channel_id not in memoria_ticket:
        memoria_ticket[channel_id] = {
            "descrizione_partner": None, "link": None, "nome_server": None, "membri": None, "categoria": None, "reciprocita_confermata": False
        }
    
    stato = memoria_ticket[channel_id]
    
    link_match = re.search(r"discord\.gg\/([a-zA-Z0-9]+)|discord\.com\/invite\/([a-zA-Z0-9]+)", message.content)
    if link_match and not stato["link"]:
        url_trovato = link_match.group(0)
        url_completo = f"https://{url_trovato}" if not url_trovato.startswith("http") else url_trovato
        try:
            invite = await message.bot.fetch_invite(url_completo, with_counts=True)
            stato["link"] = url_completo
            stato["nome_server"] = invite.guild.name
            stato["membri"] = invite.approximate_member_count
            stato["descrizione_partner"] = message.content
            print(f"🔗 [LOG TICKET - DESCRIZIONE & LINK TROVATI]: Server '{invite.guild.name}' ({invite.approximate_member_count} membri) | URL: {url_completo}")
        except Exception as e:
            print(f"⚠️ [LOG TICKET - ERRORE FETCH INVITE]: Impossibile analizzare il link {url_completo}: {e}")

    testo_utente = message.content.lower()
    
    if any(w in testo_utente for w in ["shop", "negozio", "store"]):
        stato["categoria"] = "Shop"
        print(f"📂 [LOG TICKET - CATEGORIA]: Rilevata e impostata su 'Shop'")
    elif any(w in testo_utente for w in ["pc", "computer", "hardware"]):
        stato["categoria"] = "PC"
        print(f"📂 [LOG TICKET - CATEGORIA]: Rilevata e impostata su 'PC'")
    elif any(w in testo_utente for w in ["community", "generale", "chill"]):
        stato["categoria"] = "Community"
        print(f"📂 [LOG TICKET - CATEGORIA]: Rilevata e impostata su 'Community'")
    elif any(w in testo_utente for w in ["xbox", "microsoft"]):
        stato["categoria"] = "Xbox"
        print(f"📂 [LOG TICKET - CATEGORIA]: Rilevata e impostata su 'Xbox'")
    elif any(w in testo_utente for w in ["playstation", "ps4", "ps5", "sony"]):
        stato["categoria"] = "PlayStation"
        print(f"📂 [LOG TICKET - CATEGORIA]: Rilevata e impostata su 'PlayStation'")
        
    if any(p in testo_utente for p in ["fatto", "pubblicato", "postato", "screen", "inviato", "fatta", "confermato"]):
        if stato["link"] and stato["categoria"]:
            stato["reciprocita_confermata"] = True
            print(f"✅ [LOG TICKET - RECIPROCITÀ]: Confermata dall'utente nel canale #{message.channel.name}!")

    print(f"📊 [LOG TICKET - STATO CORRENTE] (Canale ID: {channel_id}): {stato}")

    # Se l'IA è disattivata, non generiamo risposte automatiche basate su di essa
    if not ATTIVA_IA:
        return

    risposta_ia = await genera_risposta_staff(stato, message.content)
    
    match_gestione = re.search(r"\[GESTISCI_PARTNERSHIP: Categoria=(.+), Nome=(.+), CanaleID=(.+)\]", risposta_ia)
    if match_gestione and stato["reciprocita_confermata"] and stato["descrizione_partner"]:
        cat = match_gestione.group(1).strip()
        nome = match_gestione.group(2).strip()
        canale_id_destinazione = int(match_gestione.group(3).strip())
        
        print(f"🎯 [LOG TICKET - COMPLETAMENTO]: Tutti i dati verificati. Invio descrizione partner nella destinazione corretta...")
        await gestisci_destinazione_partnership(message.guild, nome, cat, stato["membri"] or 0, stato["descrizione_partner"], canale_id_destinazione)
            
        risposta_pulita = re.sub(r"\[GESTISCI_PARTNERSHIP: .+\]", "", risposta_ia).strip()
        await message.channel.send(content=risposta_pulita)
        
        embed_log = discord.Embed(
            title="📋 Log Finale Partnership - Ticket Chiuso",
            description="Tutte le fasi della partnership sono state completate con successo.",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow()
        )
        embed_log.add_field(name="Nome Server", value=str(stato['nome_server']), inline=True)
        embed_log.add_field(name="Membri", value=str(stato['membri']), inline=True)
        embed_log.add_field(name="Categoria", value=str(stato['categoria']), inline=True)
        embed_log.add_field(name="Link Server", value=str(stato['link']), inline=False)
        
        await message.channel.send(content="✅ **Partnership completata e pubblicata!** Ecco il log definitivo del dossier:", embed=embed_log)
        
        if channel_id in memoria_ticket:
            del memoria_ticket[channel_id]
            
        print(f"🗑️ [LOG TICKET - ARCHIVIAZIONE]: Ticket {channel_id} completato, log inviato. Chiusura canale in corso...")
        
        await asyncio.sleep(5)
        try:
            await message.channel.delete()
        except Exception as e:
            print(f"⚠️ [ERRORE ELIMINAZIONE TICKET]: {e}")
    else:
        risposta_pulita = re.sub(r"\[GESTISCI_PARTNERSHIP: .+\]", "", risposta_ia).strip()
        await message.channel.send(content=risposta_pulita)

# ---------------------------------------------------------
# 7. TASK AUTOMATICI (Saluti e Gerarchia)
# ---------------------------------------------------------
@tasks.loop(minutes=10)
async def aggiorna_messaggio_automatico():
    if not bot.is_ready():
        return
    if TARGET_CHANNEL_ID == 0 or TARGET_MESSAGE_ID == 0:
        return

    for guild in bot.guilds:
        try:
            channel = guild.get_channel(TARGET_CHANNEL_ID)
            if channel:
                message = await channel.fetch_message(TARGET_MESSAGE_ID)
                new_embed = await genera_embed_staff(guild)
                await message.edit(embed=new_embed)
                print(f"[{discord.utils.utcnow()}] Embed staff aggiornato con successo!")
        except discord.NotFound:
            print("Impossibile trovare il messaggio o il canale da aggiornare.")
        except Exception as e:
            print(f"Errore durante l'aggiornamento automatico: {e}")

@tasks.loop(time=ORARIO_BUONGIORNO)
async def invia_buongiorno_automatico():
    canale = bot.get_channel(ID_CANALE_SALUTI)
    if not canale: return
    ora_attuale = datetime.datetime.now(TZ_ITALIA)
    embed = discord.Embed(
        title="🇮🇹 ☕ Buon Inizio Giornata!",
        description="Un caffè e si parte su Discord Italia 🇮🇹!",
        color=discord.Color.from_str("#5865F2"),
        timestamp=ora_attuale
    )
    await canale.send(content="@everyone", embed=embed, allowed_mentions=discord.AllowedMentions(everyone=True))
    print("🌅 [TASK]: Messaggio del buongiorno inviato con successo.")

@tasks.loop(time=ORARIO_BUONASERA)
async def invia_buonasera_automatica():
    canale = bot.get_channel(ID_CANALE_SALUTI)
    if not canale: return
    ora_attuale = datetime.datetime.now(TZ_ITALIA)
    embed = discord.Embed(
        title="🇮🇹 🌙 Buonasera Community!",
        description="La serata su Discord Italia è nel vivo!",
        color=discord.Color.from_str("#2b2d31"),
        timestamp=ora_attuale
    )
    await canale.send(content="@everyone", embed=embed, allowed_mentions=discord.AllowedMentions(everyone=True))
    print("🌃 [TASK]: Messaggio della buonasera inviato con successo.")

# ---------------------------------------------------------
# AVVIO FINALE
# ---------------------------------------------------------
if __name__ == "__main__":
    keep_alive()
    TOKEN = os.environ.get("DISCORD_TOKEN")
    if TOKEN:
        bot.run(TOKEN)
    else:
        print("❌ [ERRORE CRITICO]: Inserisci il DISCORD_TOKEN nelle variabili d'ambiente!")
