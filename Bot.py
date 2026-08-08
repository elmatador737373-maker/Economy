import os
import json
import asyncio
import threading
import io
import datetime
import pytz
import re
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

# Dizionario globale per la memoria persistente dei ticket tramite dossier
memoria_ticket = {}

# Sostituisci con l'ID del ruolo staff reale abilitato a reclamare/intervenire
RUOLO_STAFF_ID = 1455297926468468777

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
        
        # Avvio dei task in background
        if not aggiorna_staff_automatico.is_running():
            aggiorna_staff_automatico.start()
        if not invia_buongiorno_automatico.is_running():
            invia_buongiorno_automatico.start()
        if not invia_buonasera_automatica.is_running():
            invia_buonasera_automatica.start()

        await self.tree.sync()
        print("✅ Albero dei comandi e Views persistenti registrati con successo.")

bot = CustomBot()

STAFF_MGMT_ROLE_ID = 1455297916708192373
STAFF_GENERAL_ROLE_ID = 1455297926468468777  
LOG_CHANNEL_ID = 1487393847830122597        
TICKET_CATEGORY_ID = 1455298169415012547    

CHAN_BL_UTENTI = 1455298385933504686
CHAN_BL_SERVER = 1455298390173941943
TAG_STAFF_BL = "<@&1455297933196001411> , <@&1455297952133284022>"
EMOJI_V4 = "<:V4:1530942846599827502>"

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

# --- FUNZIONE MOTORE IA CON GROQ, PROMPT DETTAGLIATO E DOSSIER ---
async def genera_risposta_staff(channel: discord.TextChannel, input_prompt: str, stato_corrente: dict) -> str:
    system_prompt = (
        "Sei l'assistente virtuale ufficiale e il responsabile delle partnership di Discord Italia. "
        "Il tuo obiettivo principale è accogliere cordialmente gli utenti nei ticket, guidarli passo dopo passo "
        "e gestire le richieste di partnership.\n\n"
        "REGOLE RIGIDE DA SEGUIRE:\n"
        "1. Leggi attentamente il DOSSIER MEMORIA PERSISTENTE fornito in ogni messaggio dell'utente per sapere lo stato attuale (tipo di ticket, link del server, nome, membri, categoria e conferma di reciprocità).\n"
        "2. Se l'utente non ha ancora fornito la descrizione e il link, accoglilo presentando la descrizione ufficiale di Discord Italia e chiedendo direttamente la descrizione del suo server (con link d'invito e categoria).\n"
        "3. Se il link è stato fornito ma la reciprocità NON è confermata, ringrazia, mostra i dati rilevati del server e ricorda la regola della reciprocità (l'utente deve pubblicare l'invito nel proprio server e mandare conferma o screen).\n"
        "4. Se la reciprocità è confermata (valore SÌ nel dossier), scrivi esattamente nel testo della risposta la stringa di comando di sistema formattata in questo modo esatto per creare il canale: [CREA_CANALE: Categoria=<categoria>, Nome=<nome_server>, CanaleID=<id_canale_attuale>].\n"
        "5. Mantieni sempre un tono professionale, caloroso, in lingua italiana, usando emoji a tema Discord e formattazione Markdown pulita."
    )

    descrizione_ufficiale_discord_italia = (
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

    tipo = stato_corrente.get("tipo_ticket", "Generale")

    if not stato_corrente["link"] and not stato_corrente["categoria"]:
        return (
            f"Grazie per aver aperto un ticket di tipo **{tipo}**! Dal canto nostro, ecco chi siamo e cosa offriamo:\n\n"
            f"{descrizione_ufficiale_discord_italia}\n\n"
            f"Per procedere, ti chiedo di inviarci la **descrizione del tuo server** (all'interno della quale includerai il link d'invito e la categoria di appartenenza, es. Community, Shop, PC, Xbox, PlayStation)."
        )

    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": input_prompt}
            ],
            temperature=0.7,
            max_tokens=600
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"Errore nella chiamata a Groq: {e}")
        if stato_corrente["link"] and not stato_corrente["reciprocita_confermata"]:
            return (
                f"Ho analizzato la descrizione e registrato il server **{stato_corrente['nome_server']}** "
                f"({stato_corrente['membri']} membri) per la categoria **{stato_corrente['categoria']}**!\n\n"
                f"Ti ricordo che la nostra partnership si basa sulla **regola della reciprocità**: "
                f"ti chiediamo di pubblicare il nostro invito nel vostro server e di mandarci una conferma o uno screen. "
                f"Appena fatto, procederemo subito alla creazione del canale dedicato nel nostro network!"
            )
        return "Perfetto, ho ricevuto le informazioni. Sto verificando gli ultimi dettagli."

async def crea_canale_partner(guild: discord.Guild, nome_partner: str, categoria_scelta: str):
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
            reason=f"Partnership ratificata per la categoria: {categoria_scelta}"
        )
        return nuovo_canale
    except Exception as e:
        print(f"Errore nella creazione del canale stilizzato: {e}")
        return None

# --- TASK AUTOMATICI ---
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
    embed.set_footer(text="Discord Italia 🇮🇹 • Make your day awesome!", icon_url=canale.guild.icon.url if canale.guild.icon else None)

    await canale.send(content="@everyone", embed=embed, allowed_mentions=discord.AllowedMentions(everyone=True))

@tasks.loop(time=ORARIO_BUONASERA)
async def invia_buonasera_automatica():
    canale = bot.get_channel(ID_CANALE_SALUTI)
    if not canale: return
    ora_attuale = datetime.datetime.now(TZ_ITALIA)
    data_formattata = ora_attuale.strftime("%d/%m/%Y")

    embed = discord.Embed(
        title="🇮🇹 🌙 Good Night & Night Vibes — Discord Italia!",
        description="La giornata volge al termine, ma la notte su Discord Italia 🇮🇹 è appena iniziata!",
        color=discord.Color.from_str("#2b2d31"),
        timestamp=ora_attuale
    )
    if canale.guild.icon: embed.set_thumbnail(url=canale.guild.icon.url)
    embed.add_field(name="🎧 Canali Vocali", value="Entra nelle room vocali per fare due chiacchiere!", inline=False)
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
        description=f"Ciao {member.mention}, benvenuto nel nostro server ufficiale!",
        color=discord.Color.from_rgb(0, 146, 70)
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    if file: embed.set_image(url="attachment://welcome.png")

    if file: await channel.send(content=f"🎉 Benvenuto {member.mention}!", embed=embed, file=file)
    else: await channel.send(content=f"🎉 Benvenuto {member.mention}!", embed=embed)

# ---------------------------------------------------------
# INTERCETTAZIONE MESSAGGI & MEMORIA DOSSIER TICKET
# ---------------------------------------------------------
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot: return
    
    if message.channel.name.startswith("ticket-"):
        channel_id = message.channel.id
        
        if channel_id not in memoria_ticket:
            tipo_estratto = "Generale"
            async for hist_msg in message.channel.history(limit=5, oldest_first=True):
                if hist_msg.author == message.guild.me and hist_msg.embeds:
                    titolo_embed = hist_msg.embeds[0].title or ""
                    if "Ticket" in titolo_embed:
                        parti = titolo_embed.split("Ticket")
                        if len(parti) > 1:
                            tipo_estratto = parti[1].strip()
                    break
            
            memoria_ticket[channel_id] = {
                "tipo_ticket": tipo_estratto,
                "link": None, 
                "nome_server": None, 
                "membri": None, 
                "categoria": None, 
                "reciprocita_confermata": False, 
                "staff_intervenuto": False
            }
        
        stato = memoria_ticket[channel_id]
        
        is_staff = any(role.id == RUOLO_STAFF_ID for role in message.author.roles) if hasattr(message.author, "roles") else False
        if is_staff or "claim" in message.content.lower() or "staff" in message.content.lower():
            stato["staff_intervenuto"] = True
            return

        if stato["staff_intervenuto"]:
            return

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
        if "shop" in testo_utente: stato["categoria"] = "Shop"
        elif "pc" in testo_utente: stato["categoria"] = "PC"
        elif "community" in testo_utente: stato["categoria"] = "Community"
        elif "xbox" in testo_utente: stato["categoria"] = "Xbox"
        elif "playstation" in testo_utente or "ps4" in testo_utente or "ps5" in testo_utente: stato["categoria"] = "PlayStation"
            
        if any(parola in testo_utente for parola in ["fatto", "pubblicato", "postato", "screen", "inviato", "controlla"]):
            if stato["link"] and stato["categoria"]:
                stato["reciprocita_confermata"] = True

        dossier_memoria = (
            f"\n\n[DOSSIER MEMORIA PERSISTENTE]:\n"
            f"- Tipo Ticket: {stato['tipo_ticket']}\n"
            f"- Link Server (Estratto da descrizione): {stato['link'] or 'Non ancora fornito'}\n"
            f"- Nome Server: {stato['nome_server'] or 'Sconosciuto'}\n"
            f"- Membri Totali: {stato['membri'] or 'Non calcolati'}\n"
            f"- Categoria Rilevata: {stato['categoria'] or 'Non ancora dichiarata'}\n"
            f"- Reciprocità Confermata: {'SÌ' if stato['reciprocita_confermata'] else 'NO'}\n"
            f"--------------------------------------------------\n"
        )
        
        input_per_ia = f"Messaggio utente: {message.content} {dossier_memoria}"
        risposta_ia = await genera_risposta_staff(message.channel, input_per_ia, stato)
        
        match_creazione = re.search(r"\[CREA_CANALE: Categoria=(.+), Nome=(.+), CanaleID=(.+)\]", risposta_ia)
        if match_creazione and stato["reciprocita_confermata"]:
            cat = match_creazione.group(1).strip()
            nome = match_creazione.group(2).strip()
            canale_id_destinazione = int(match_creazione.group(3).strip())
            
            await crea_canale_partner(message.guild, nome, cat)
            
            canale_target = message.guild.get_channel(canale_id_destinazione)
            if canale_target:
                await canale_target.send(f"Nuova partnership ratificata per il network: **{nome}**! 🤝")
                
            risposta_pulita = re.sub(r"\[CREA_CANALE: .+\]", "", risposta_ia).strip()
            await message.reply(risposta_pulita)
            
            del memoria_ticket[channel_id]
        else:
            risposta_pulita = re.sub(r"\[CREA_CANALE: .+\]", "", risposta_ia).strip()
            await message.reply(risposta_pulita)

# ---------------------------------------------------------
# GESTIONE GERARCHIA STAFF & ALTRI PANNELLI
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

    embed = discord.Embed(title="👑 Gerarchia dello Staff", color=discord.Color.blue(), timestamp=discord.utils.utcnow())
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

# --- MODAL CANDIDATURA & BLACKLIST ---
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

# --- TICKET CONTROL & TRANSCRIPT ---
class ClosedTranscriptView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)

class TicketControlView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)

    @discord.ui.button(label="🔒 Chiudi ed Elimina", style=discord.ButtonStyle.red, custom_id="btn_ticket_close")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.channel.delete()

    @discord.ui.button(label="🙋‍♂️ Reclama", style=discord.ButtonStyle.green, custom_id="btn_ticket_claim")
    async def claim_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.channel.id in memoria_ticket:
            memoria_ticket[interaction.channel.id]["staff_intervenuto"] = True
        button.disabled = True
        button.label = f"Reclamato da {interaction.user.display_name}"
        await interaction.message.edit(view=self)
        await interaction.response.send_message(embed=discord.Embed(description=f"📌 Preso in carico da {interaction.user.mention}. L'assistenza IA è stata disattivata.", color=discord.Color.gold()))

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
            "tipo_ticket": category_type,
            "link": None,
            "nome_server": None,
            "membri": None,
            "categoria": None,
            "reciprocita_confermata": False,
            "staff_intervenuto": False
        }
        memoria_ticket[ticket_channel.id] = stato_iniziale

        risposta_iniziale = await genera_risposta_staff(ticket_channel, "Nuovo ticket aperto dall'utente.", stato_iniziale)
        embed_gen = discord.Embed(title=f"Ticket {category_type}", description=risposta_iniziale, color=discord.Color.green())
        
        await ticket_channel.send(content=tag_message, embed=embed_gen, view=TicketControlView())

class TicketSelectView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None); self.add_item(TicketSelect())

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
