import os
import re
import datetime
import pytz
import asyncio
import threading
import openai
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

# Dizionario globale per la memoria persistente dei ticket
memoria_ticket = {}

RUOLO_STAFF_ID = 1455297926468468777
STAFF_MGMT_ROLE_ID = 1455297916708192373
STAFF_GENERAL_ROLE_ID = 1455297926468468777  
LOG_CHANNEL_ID = 1487393847830122597        
TICKET_CATEGORY_ID = 1455298169415012547    

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

TARGET_CHANNEL_ID = 0
TARGET_MESSAGE_ID = 0

ID_CANALE_SALUTI = 1455298208413520014
TZ_ITALIA = pytz.timezone("Europe/Rome")
ORARIO_BUONGIORNO = datetime.time(hour=8, minute=0, second=0, tzinfo=TZ_ITALIA)
ORARIO_BUONASERA  = datetime.time(hour=21, minute=0, second=0, tzinfo=TZ_ITALIA)

# Configurazione Client Groq
groq_client = openai.OpenAI(
    api_key=os.environ.get("GROQ_API_KEY"),
    base_url="https://api.groq.com/openai/v1"
)

# ---------------------------------------------------------
# 3. DEFINIZIONE DEL BOT (CustomBot)
# ---------------------------------------------------------
class CustomBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        self.add_view(StaffApplicationView())
        self.add_view(TicketControlView())
        self.add_view(TicketSelectView())
        self.add_view(ClosedTranscriptView())
        self.add_view(BlacklistApprovalView())
        
        if not aggiorna_staff_automatico.is_running():
            aggiorna_staff_automatico.start()
        if not invia_buongiorno_automatico.is_running():
            invia_buongiorno_automatico.start()
        if not invia_buonasera_automatica.is_running():
            invia_buonasera_automatica.start()

        await self.tree.sync()
        print("✅ Albero dei comandi e Views persistenti registrati con successo.")

bot = CustomBot()

# ---------------------------------------------------------
# 4. DESCRIZIONE UFFICIALE & MOTORE IA CON GROQ
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

async def genera_risposta_staff(channel: discord.TextChannel, input_prompt: str) -> str:
    system_prompt = (
        "SEI IL RESPONSABILE DI DIREZIONE E DESK DELLE PARTNERSHIPS DI 'DISCORD ITALIA 🇮🇹'.\n"
        "Il tuo tono è formale, autorevole, impeccabile, estremamente professionale ma umano ed elastico. "
        "Non sei un bot: sei un professionista che gestisce la crescita del network. "
        "Il tuo obiettivo è guidare l'utente passo dopo passo, raccogliendo tutte le informazioni necessarie senza risultare meccanico.\n\n"

        "=== CONTESTO INIZIALE TICKET PARTNERSHIP ===\n"
        f"Se l'utente apre il ticket per la prima volta, includi e presenta sempre la descrizione ufficiale di Discord Italia:\n{DESCRIZIONE_UFFICIALE_DISCORD_ITALIA}\n\n"

        "=== DATI DA RACCOGLIERE (GUIDA L'UTENTE) ===\n"
        "Nel corso della conversazione, devi tassativamente accertarti di avere:\n"
        "1. **Il link di invito del server:** (Se l'utente non lo fornisce, chiediglielo gentilmente invitandolo a inviarlo per analizzare l'anteprima ufficiale).\n"
        "   - *Nota di sistema:* Quando l'utente invia il link, riceverai un'anteprima automatica con il nome esatto e il conteggio approssimativo dei membri.\n"
        "2. **La categoria del progetto:** Scegliendo rigorosamente tra:\n"
        "   - **Shop** (Assegna emoji 🛍️)\n"
        "   - **PC** (Assegna emoji 💻)\n"
        "   - **Community**\n"
        "   - **Xbox**\n"
        "   - **PlayStation**\n"
        "3. **Il nome ufficiale del server/progetto:** Mantenendo rigorosamente le maiuscole iniziali fornite dall'utente.\n\n"

        "=== DATABASE CANALI E FASCE (SMISTAMENTO AUTOMATICO) ===\n"
        "In base alla categoria e al numero di membri rilevato dall'anteprima, saprai esattamente dove pubblicare:\n"
        "- **SHOP:** Canale ID `1455298162813046854`\n"
        "- **PC:** Canale ID `1455298158748897413`\n"
        "- **COMMUNITY:** \n"
        "  • 0-600 (`1455298333366292512`) | 600-1500 (`1505914982443778157`) | 1500-2300 (`1455298340588879954`) | 2300-5000 (`1459223502107181180`) | 5k+ (`1497864519433846845`)\n"
        "- **XBOX:** \n"
        "  • 0-600 (`1506366880842252299`) | 600-1500 (`1506366972726874182`) | 1500-2300 (`1460365011171151882`) | 2300-5000 (`1487403274658381864`) | 5000+ (`1455298295680204932`)\n"
        "- **PLAYSTATION:** \n"
        "  • 0-600 (`1457119066043977973`) | 600-1500 (`1455298305041895604`) | 1500-2300 (`1455298300315046042`) | 2300-5000 (`1485211001719619624`) | 5000+ (`1489956038362009630`)\n\n"

        "=== LA REGOLA SACRA DELLA RECIPROCITÀ ===\n"
        "- La partnership viene ratificata **SOLO** dopo che l'altro server ha pubblicato la nostra descrizione.\n"
        "- Guida l'utente allo scambio: chiedigli la conferma o la prova (screenshot o messaggio) dell'avvenuta pubblicazione da parte loro.\n\n"

        "=== COMANDO FINALE PER IL SISTEMA ===\n"
        "Quando hai raccolto tutti i dati (Categoria, Nome con maiuscole, Canale ID corretto in base ai membri) E hai ricevuto la conferma della reciprocità, "
        "concludi la risposta inserendo obbligatoriamente questo tag di sistema alla fine:\n"
        "`[CREA_CANALE: Categoria=X, Nome=Y, CanaleID=Z]`\n"
        "Esempio: `[CREA_CANALE: Categoria=Shop, Nome=CryptoShop, CanaleID=1455298162813046854]`\n"
        "Il sistema creerà automaticamente il canale formattato e pubblicherà la partnership nel canale di destinazione."
    )

    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": input_prompt}
            ],
            temperature=0.7,
            max_tokens=1000
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"Errore nella chiamata a Groq: {e}")
        return "Vi è stato un piccolo problema tecnico nell'elaborazione della risposta. Ti chiedo di ripetere l'ultimo messaggio."

# ---------------------------------------------------------
# 5. FUNZIONE CREAZIONE CANALI PARTNER
# ---------------------------------------------------------
async def crea_canale_partner(guild: discord.Guild, nome_partner: str, categoria_scelta: str, membri_totali: int):
    categoria_pulita = categoria_scelta.upper()
    nome_formattato = nome_partner.strip().replace(" ", "-")
    
    if "SHOP" in categoria_pulita:
        nome_canale = f"🛍️⎱{nome_formattato}"
    elif "PC" in categoria_pulita:
        nome_canale = f"💻⎱{nome_formattato}"
    else:
        nome_canale = f"🤝⎱{nome_formattato}"

    categoria_server = discord.utils.get(guild.categories, name="PARTNERSHIPS")

    try:
        nuovo_canale = await guild.create_text_channel(
            name=nome_canale,
            category=categoria_server or discord.utils.get(guild.categories, id=TICKET_CATEGORY_ID),
            reason=f"Partnership ratificata per la categoria: {categoria_scelta} ({membri_totali} membri)"
        )
        return nuovo_canale
    except Exception as e:
        print(f"Errore nella creazione del canale stilizzato: {e}")
        return None

# ---------------------------------------------------------
# 6. GESTIONE EVENTO ON_MESSAGE E MEMORIA TICKET
# ---------------------------------------------------------
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot: return
    
    if message.channel.name.startswith("ticket-"):
        channel_id = message.channel.id
        
        if channel_id not in memoria_ticket:
            memoria_ticket[channel_id] = {
                "link": None,
                "nome_server": None,
                "membri": None,
                "categoria": None,
                "reciprocita_confermata": False
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
            except Exception as e:
                print(f"Errore nel recupero dell'invito: {e}")

        testo_utente = message.content.lower()
        
        if "shop" in testo_utente:
            stato["categoria"] = "Shop"
        elif "pc" in testo_utente:
            stato["categoria"] = "PC"
        elif "community" in testo_utente:
            stato["categoria"] = "Community"
        elif "xbox" in testo_utente:
            stato["categoria"] = "Xbox"
        elif "playstation" in testo_utente or "ps4" in testo_utente or "ps5" in testo_utente:
            stato["categoria"] = "PlayStation"
            
        if any(parola in testo_utente for parola in ["fatto", "pubblicato", "postato", "screen", "inviato", "controlla"]):
            if stato["link"] and stato["categoria"]:
                stato["reciprocita_confermata"] = True

        dossier_memoria = (
            f"\n\n[DOSSIER MEMORIA PERSISTENTE - AGGIORNATO IN TEMPO REALE]:\n"
            f"- Link Server: {stato['link'] or 'Non ancora fornito'}\n"
            f"- Nome Server (Anteprima): {stato['nome_server'] or 'Sconosciuto'}\n"
            f"- Membri Totali: {stato['membri'] or 'Non ancora calcolati'}\n"
            f"- Categoria Rilevata: {stato['categoria'] or 'Non ancora dichiarata'}\n"
            f"- Reciprocità Confermata: {'SÌ (Pronto per la chiusura)' if stato['reciprocita_confermata'] else 'NO'}\n"
            f"--------------------------------------------------\n"
        )
        
        input_per_ia = f"Messaggio utente: {message.content} {dossier_memoria}"
        
        risposta_ia = await genera_risposta_staff(message.channel, input_per_ia)
        
        match_creazione = re.search(r"\[CREA_CANALE: Categoria=(.+), Nome=(.+), CanaleID=(.+)\]", risposta_ia)
        if match_creazione and stato["reciprocita_confermata"]:
            cat = match_creazione.group(1).strip()
            nome = match_creazione.group(2).strip()
            canale_id_destinazione = int(match_creazione.group(3).strip())
            
            await crea_canale_partner(message.guild, nome, cat, stato["membri"] or 0)
            
            canale_target = message.guild.get_channel(canale_id_destinazione)
            if canale_target:
                await canale_target.send(f"Nuova partnership ratificata per il network: **{nome}**! 🤝")
                
            risposta_pulita = re.sub(r"\[CREA_CANALE: .+\]", "", risposta_ia).strip()
            await message.channel.send(content=risposta_pulita)
            
            del memoria_ticket[channel_id]
        else:
            risposta_pulita = re.sub(r"\[CREA_CANALE: .+\]", "", risposta_ia).strip()
            await message.channel.send(content=risposta_pulita)

# ---------------------------------------------------------
# 7. INTERFACCE UI, MODALS E COMANDI BOT
# ---------------------------------------------------------
class StaffApplicationModal(discord.ui.Modal, title="📋 MODULO CANDIDATURA STAFF"):
    info = discord.ui.TextInput(label="👤 Informazioni Personali", style=discord.TextStyle.paragraph, required=True, max_length=500)
    esperienza = discord.ui.TextInput(label="🛡️ Esperienza", style=discord.TextStyle.paragraph, required=True, max_length=500)
    conoscenze = discord.ui.TextInput(label="📚 Conoscenze Discord", style=discord.TextStyle.paragraph, required=True, max_length=1000)
    partnership = discord.ui.TextInput(label="🤝 Esperienza Partnership", style=discord.TextStyle.paragraph, required=True, max_length=500)
    motivazioni = discord.ui.TextInput(label="🎯 Motivazioni", style=discord.TextStyle.paragraph, required=True, max_length=500)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.send_message("✅ Candidatura inviata!", ephemeral=True)

class StaffApplicationView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="📝 Compila Modulo", style=discord.ButtonStyle.primary, custom_id="open_staff_modal_btn")
    async def open_modal(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(StaffApplicationModal())

class BlacklistRequestModal(discord.ui.Modal, title="📋 RICHIESTA BLACKLIST"):
    tipo = discord.ui.TextInput(label="📲 TIPO (UTENTE/SERVER)", style=discord.TextStyle.short, required=True)
    nome_id = discord.ui.TextInput(label="🆔️ NOME UTENTE / SERVER", style=discord.TextStyle.short, required=True)
    motivo = discord.ui.TextInput(label="❓️ MOTIVO", style=discord.TextStyle.paragraph, required=True)
    prove = discord.ui.TextInput(label="🖇️ PROVE", style=discord.TextStyle.paragraph, required=True)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.send_message("✅ Richiesta inviata con successo allo staff!", ephemeral=True)

class BlacklistApprovalView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)

class ClosedTranscriptView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)

class TicketControlView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)

    @discord.ui.button(label="🔒 Chiudi ed Elimina", style=discord.ButtonStyle.red, custom_id="btn_ticket_close")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.channel.id in memoria_ticket:
            del memoria_ticket[interaction.channel.id]
        await interaction.channel.delete()

    @discord.ui.button(label="🙋‍♂️ Reclama", style=discord.ButtonStyle.green, custom_id="btn_ticket_claim")
    async def claim_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.channel.id in memoria_ticket:
            memoria_ticket[interaction.channel.id]["staff_intervenuto"] = True
        button.disabled = True
        button.label = f"Reclamato da {interaction.user.display_name}"
        await interaction.message.edit(view=self)
        await interaction.response.send_message(content=f"📌 Preso in carico da {interaction.user.mention}. L'assistenza IA è stata disattivata.")

class TicketSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Ticket Generale", description="Assistenza generica", emoji="📩", value="Generale"),
            discord.SelectOption(label="Partnership", description="Richieste partnership", emoji="🤝", value="Partnership"),
            discord.SelectOption(label="Bando Staff", description="Candidati per lo staff", emoji="📋", value="Staff"),
            discord.SelectOption(label="Richiesta Blacklist", description="Segnala utente o server", emoji="🚫", value="Blacklist"),
            discord.SelectOption(label="Amministrazione", description="Supporto direttivo", emoji="👑", value="Amministrazione"),
            discord.SelectOption(label="Grafiche & Bot", description="Richieste grafiche o bot", emoji="🎨", value="Grafiche & Bot"),
        ]
        super().__init__(placeholder="Scegli la categoria del Ticket...", min_values=1, max_values=1, options=options, custom_id="select_ticket_category")

    async def callback(self, interaction: discord.Interaction):
        category_type = self.values[0]
        guild = interaction.guild
        user = interaction.user

        if category_type == "Blacklist":
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
        ticket_channel = await guild.create_text_channel(name=f"ticket-{category_type.lower()}-{user.name}", overwrites=overwrites, category=category if isinstance(category, discord.CategoryChannel) else None)

        await interaction.response.send_message(f"✅ Ticket creato: {ticket_channel.mention}", ephemeral=True)
        tag_message = f"<@&{STAFF_GENERAL_ROLE_ID}> | {user.mention}"

        stato_iniziale = {
            "link": None,
            "nome_server": None,
            "membri": None,
            "categoria": None,
            "reciprocita_confermata": False
        }
        memoria_ticket[ticket_channel.id] = stato_iniziale

        risposta_iniziale = await genera_risposta_staff(ticket_channel, f"Apertura ticket di tipo {category_type}")
        messaggio_completo = f"{tag_message}\n\n{risposta_iniziale}"
        
        await ticket_channel.send(content=messaggio_completo, view=TicketControlView())

class TicketSelectView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None); self.add_item(TicketSelect())

@bot.tree.command(name="setup_ticket", description="Invia il pannello principale dei Ticket (Solo Admin)")
@app_commands.checks.has_permissions(administrator=True)
async def setup_ticket(interaction: discord.Interaction):
    await interaction.response.send_message("✅ Pannello in fase di invio...", ephemeral=True)
    
    embed = discord.Embed(
        title="🇮🇹 Assistenza & Supporto - Discord Italia",
        description="Seleziona dal menu a tendina la categoria desiderata:\n\n📩 **Generale**\n🤝 **Partnership**\n📋 **Bando Staff**\n🚫 **Richiesta Blacklist**\n👑 **Amministrazione**\n🎨 **Grafiche & Bot**",
        color=discord.Color.from_rgb(0, 146, 70)
    )
    embed.set_footer(text="Discord Italia 🇮🇹 • Sistema di Supporto")
    await interaction.channel.send(embed=embed, view=TicketSelectView())

# ---------------------------------------------------------
# 8. TASK AUTOMATICI (Saluti e Staff)
# ---------------------------------------------------------
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

    embed = discord.Embed(title="👑 Gerarchia dello Staff", color=discord.Color.blue(), timestamp=discord.utils.utcnow())
    for role in roles:
        members = role_members.get(role.id, [])
        value_text = ", ".join(members) if members else "*Nessun membro*"
        embed.add_field(name=f"➤ {role.name}", value=value_text, inline=False)
    return embed

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
