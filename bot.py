import os
import re
import aiohttp
import discord
from discord.ext import commands
from dotenv import load_dotenv
from flask import Flask
import threading
import requests  # Needed for fetch_song_links

# ---------------------------
# Load Environment Variables
# ---------------------------
load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
GENIUS_API_KEY = os.getenv("GENIUS_API_KEY")

# ---------------------------
# Discord Setup
# ---------------------------
intents = discord.Intents.default()  # No message_content needed if only using slash commands
bot = commands.Bot(command_prefix=None, intents=intents)  # No prefix commands
tree = bot.tree

# ---------------------------
# Song.link helpers
# ---------------------------
def clean_song_title(title: str) -> str:
    if not title:
        return ""
    title = re.sub(r"\(feat\.?.*?\)|\[feat\.?.*?\]", "", title, flags=re.IGNORECASE)
    title = re.sub(r"\(.*?Remix.*?\)|\[.*?Remix.*?\]", "", title, flags=re.IGNORECASE)
    title = re.sub(r"[\[\]\(\)]", "", title)
    title = re.sub(r"[^\w\s&'-]", "", title)
    title = re.sub(r"\s+", " ", title)
    return title.strip()

async def fetch_song_links(query: str, interaction=None, is_slash=False):
    try:
        r = requests.get(
            "https://api.song.link/v1-alpha.1/links",
            params={"url": query, "userCountry": "US"},
            timeout=20
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        if is_slash and interaction:
            await interaction.followup.send(f"Error fetching song data: {e}")
        return None

def get_genius_link(title: str, artist: str):
    if not title or not GENIUS_API_KEY:
        return None
    clean_title_str = clean_song_title(title)
    query = f"{clean_title_str} {artist}"
    try:
        r = requests.get(
            "https://api.genius.com/search",
            params={"q": query},
            headers={"Authorization": f"Bearer {GENIUS_API_KEY}"},
            timeout=20
        )
        data = r.json()
        hits = data.get("response", {}).get("hits", [])
        for hit in hits:
            result = hit.get("result", {})
            if clean_title_str.lower() in result.get("title", "").lower() and artist.lower() in result.get("primary_artist", {}).get("name", "").lower():
                return result.get("url")
        return hits[0]["result"].get("url") if hits else None
    except Exception:
        return None

async def send_songlink_embed(interaction, song_data):
    entity_id = None
    for uid, entity in song_data.get("entitiesByUniqueId", {}).items():
        if entity.get("type") == "song":
            entity_id = uid
            break
    if not entity_id:
        await interaction.followup.send("Could not parse song data.")
        return

    song = song_data["entitiesByUniqueId"][entity_id]
    title = song.get("title", "Unknown Title")
    artist = song.get("artistName", "Unknown Artist")
    thumbnail = song.get("thumbnailUrl") or song.get("artworkUrl")
    genius_url = get_genius_link(title, artist)
    platforms = list(song_data.get("linksByPlatform", {}).items())[:50]
    platform_links = "\n".join(
        f"[{platform.replace('_',' ').title()}]({data['url']})"
        for platform, data in platforms
        if isinstance(data, dict) and "url" in data
    )

    # Split into 1000-char chunks
    chunks, current_chunk = [], ""
    for line in platform_links.split("\n"):
        if len(current_chunk) + len(line) + 1 > 1000:
            chunks.append(current_chunk)
            current_chunk = line
        else:
            current_chunk += ("\n" if current_chunk else "") + line
    if current_chunk:
        chunks.append(current_chunk)

    for i, chunk in enumerate(chunks):
        embed = discord.Embed(
            title=title,
            url=genius_url if genius_url else None,
            description=f"by {artist}",
            color=0x1DB954
        )
        if thumbnail:
            embed.set_thumbnail(url=thumbnail)
        embed.add_field(name="Listen On", value=chunk, inline=False)
        if len(chunks) > 1:
            embed.set_footer(text=f"Page {i+1}/{len(chunks)}")
        await interaction.followup.send(embed=embed)

# ---------------------------
# Slash Commands Only
# ---------------------------
@tree.command(
    name="sl",
    description="Song links + Genius",
)
async def slash_songlink(interaction: discord.Interaction, query: str):
    await interaction.response.defer()
    song_data = await fetch_song_links(query, interaction, is_slash=True)
    if not song_data:
        await interaction.followup.send("Nothing found.")
        return
    await send_songlink_embed(interaction, song_data)

# ---------------------------
# Bot Events
# ---------------------------
@bot.event
async def on_ready():
    await tree.sync()
    print(f"Bot is online as {bot.user}!")
    print("Slash commands synced and ready to use.")

# ---------------------------
# Keep-Alive Web Server
# ---------------------------
app = Flask(__name__)
@app.route("/")
def home():
    return "Bot is alive."

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

threading.Thread(target=run_flask).start()

# ---------------------------
# Start Bot
# ---------------------------
bot.run(DISCORD_TOKEN)