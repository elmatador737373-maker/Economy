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

STAFF_MGMT_ROLE_ID = 1455297916708192373
STAFF_GENERAL_ROLE_ID = 1455297926468468777  # Ruolo taggato all'apertura del ticket
LOG_CHANNEL_ID = 1234567890123456789        # 👈 INSERISCI QUI L'ID DEL CANALE LOG/ARCHIVIO

class CustomBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        self.add_view(TicketSelectView())
        self.add_view(TicketControlView())
        self.add_view(ClosedTranscriptView()) # Registrazione View persistente per il bottone nei log
        self.add_view(StaffApplicationView())

bot = CustomBot()

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

        # Configurazione permessi canale
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }

        owner_member = guild.get_member(owner_id) if owner_id else None
        if owner_member:
            overwrites[owner_member] = discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True)

        if staff_role:
            overwrites[staff_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True)

        # Creazione del nuovo canale ticket
        new_channel = await guild.create_text_channel(name=f"reopen-{channel_name}", overwrites=overwrites)

        # Creazione del Webhook per la ricostruzione chat
        webhook = await new_channel.create_webhook(name="Transcript Replicator")

        header_embed = discord.Embed(
            title="🔄 RICOSTRUZIONE CHAT DA TRANSCRIPT",
            description=f"Ticket riaperto da {interaction.user.mention} tramite il pannello log.",
            color=discord.Color.green()
        )
        await new_channel.send(embed=header_embed)

        # Ricostruzione messaggi tramite Webhook
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
        await interaction.response.send_message("🔒 Generazione automatica del transcript ed eliminazione in corso...")

        owner_id = None
        for overwrite, perms in channel.overwrites.items():
            if isinstance(overwrite, discord.Member) and not overwrite.bot:
                owner_id = overwrite.id
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

        filename = f"transcript-{channel.name}.json"
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(transcript_payload, f, ensure_ascii=False, indent=4)

        log_channel = interaction.guild.get_channel(LOG_CHANNEL_ID)
        if log_channel:
            embed_log = discord.Embed(
                title=f"📦 Transcript Archiviato: {channel.name}",
                description=f"**Chiuso da:** {interaction.user.mention}\nClicca il bottone sottostante per riaprire automaticamente questo ticket.",
                color=discord.Color.red()
            )
            # Invia il file JSON allegato insieme al bottone persistente per la riapertura
            await log_channel.send(embed=embed_log, file=discord.File(filename), view=ClosedTranscriptView())

        await asyncio.sleep(3)
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

        ticket_channel = await guild.create_text_channel(name=channel_name, overwrites=overwrites)

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
async def ticket_rename(interaction: discord.Interaction, new_name: str):
    await interaction.channel.edit(name=f"ticket-{new_name}")
    await interaction.response.send_message(f"✏️ Ticket rinominato in `ticket-{new_name}`.")

bot.tree.add_command(ticket_group)

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
