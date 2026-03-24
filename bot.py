import os
import re
import discord
import aiohttp
from discord.ext import commands
from discord import app_commands

# Flask (keep-alive)
from flask import Flask
from threading import Thread

# ---------------------------
# Config
# ---------------------------
TOKEN = os.getenv("DISCORD_TOKEN")
GENIUS_API_KEY = os.getenv("GENIUS_API_KEY")

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# ---------------------------
# Flask Keep Alive
# ---------------------------
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot is alive."

def run_flask():
    app.run(host="0.0.0.0", port=8080)

def keep_alive():
    t = Thread(target=run_flask)
    t.start()

# ---------------------------
# Helpers
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

# ---------------------------
# API Calls (ASYNC)
# ---------------------------
async def fetch_songlink_data(query: str):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.song.link/v1-alpha.1/links",
                params={"url": query, "userCountry": "US"},
                timeout=aiohttp.ClientTimeout(total=15)
            ) as r:
                if r.status != 200:
                    return None
                return await r.json()
    except Exception:
        return None

async def get_genius_link(title: str, artist: str):
    if not title or not GENIUS_API_KEY:
        return None

    clean_title_str = clean_song_title(title)
    query = f"{clean_title_str} {artist}"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.genius.com/search",
                params={"q": query},
                headers={"Authorization": f"Bearer {GENIUS_API_KEY}"},
                timeout=aiohttp.ClientTimeout(total=15)
            ) as r:
                data = await r.json()
                hits = data.get("response", {}).get("hits", [])

                for hit in hits:
                    result = hit.get("result", {})
                    result_title = result.get("title", "").lower()
                    result_artist = result.get("primary_artist", {}).get("name", "").lower()

                    if clean_title_str.lower() in result_title or result_title in clean_title_str.lower():
                        return result.get("url")

                return hits[0]["result"].get("url") if hits else None
    except Exception:
        return None

# ---------------------------
# Embed Builder
# ---------------------------
async def send_songlink_embed(ctx_or_interaction, song_data, is_slash=False):
    entities = song_data.get("entitiesByUniqueId", {})
    entity_id = None

    for uid, entity in entities.items():
        if entity.get("type") == "song":
            entity_id = uid
            break

    if not entity_id:
        msg = "Could not parse song data."
        if is_slash:
            await ctx_or_interaction.followup.send(msg)
        else:
            await ctx_or_interaction.send(msg)
        return

    song = entities[entity_id]
    title = song.get("title", "Unknown Title")
    artist = song.get("artistName", "Unknown Artist")
    thumbnail = song.get("thumbnailUrl") or song.get("artworkUrl")

    genius_url = await get_genius_link(title, artist)

    raw_platforms = song_data.get("linksByPlatform", {})
    platforms = [
        (p, d) for p, d in raw_platforms.items()
        if isinstance(d, dict) and "url" in d
    ]

    priority = ["spotify", "youtube", "appleMusic", "soundcloud"]
    platforms.sort(key=lambda x: priority.index(x[0]) if x[0] in priority else 999)
    platforms = platforms[:25]

    platform_links = "\n".join(
        f"[{p.replace('_',' ').title()}]({d['url']})"
        for p, d in platforms
    )

    chunks, current = [], ""
    for line in platform_links.split("\n"):
        if len(current) + len(line) + 1 > 1000:
            chunks.append(current)
            current = line
        else:
            current += ("\n" if current else "") + line
    if current:
        chunks.append(current)

    chunks = chunks[:3]

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
        embed.set_footer(text=f"Powered by song.link • Page {i+1}/{len(chunks)}")

        if is_slash:
            await ctx_or_interaction.followup.send(embed=embed)
        else:
            await ctx_or_interaction.send(embed=embed)

# ---------------------------
# Commands
# ---------------------------
@bot.command(name="sl")
async def prefix_songlink(ctx, *, query: str):
    if len(query.strip()) < 3:
        return await ctx.send("Give me a valid song or link.")

    async with ctx.typing():
        song_data = await fetch_songlink_data(query)

    if not song_data:
        return await ctx.send("Nothing found.")

    await send_songlink_embed(ctx, song_data)


@bot.tree.command(name="sl", description="Get song links across platforms")
async def slash_songlink(interaction: discord.Interaction, query: str):
    await interaction.response.defer()

    if len(query.strip()) < 3:
        return await interaction.followup.send("Give me a valid song or link.")

    song_data = await fetch_songlink_data(query)

    if not song_data:
        return await interaction.followup.send("Nothing found.")

    await send_songlink_embed(interaction, song_data, is_slash=True)

# ---------------------------
# Events
# ---------------------------
@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash commands")
    except Exception as e:
        print(f"Sync failed: {e}")

    print(f"Logged in as {bot.user}")

# ---------------------------
# Run
# ---------------------------
keep_alive()
bot.run(TOKEN)
