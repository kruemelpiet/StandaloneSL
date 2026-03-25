import os
import re
import discord
import aiohttp
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv

# ---------------------------
# Load ENV
# ---------------------------
load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
GENIUS_API_KEY = os.getenv("GENIUS_API_KEY")

# ---------------------------
# Discord Setup
# ---------------------------
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# ---------------------------
# GLOBAL SESSION (important)
# ---------------------------
session = None

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
async def fetch_song_links(query: str):
    try:
        async with session.get(
            "https://api.song.link/v1-alpha.1/links",
            params={"url": query, "userCountry": "US"}
        ) as r:
            if r.status != 200:
                return None
            return await r.json()
    except:
        return None


async def get_genius_link(title: str, artist: str):
    if not title or not GENIUS_API_KEY:
        return None

    clean_title_str = clean_song_title(title)
    query = f"{clean_title_str} {artist}"

    try:
        async with session.get(
            "https://api.genius.com/search",
            params={"q": query},
            headers={"Authorization": f"Bearer {GENIUS_API_KEY}"}
        ) as r:
            data = await r.json()
            hits = data.get("response", {}).get("hits", [])

            for hit in hits:
                result = hit.get("result", {})
                result_title = result.get("title", "").lower()
                result_artist = result.get("primary_artist", {}).get("name", "").lower()

                if clean_title_str.lower() in result_title:
                    return result.get("url")

            return hits[0]["result"].get("url") if hits else None

    except:
        return None

# ---------------------------
# Embed Builder
# ---------------------------
async def send_songlink_embed(ctx_or_interaction, song_data, is_slash=False):
    entities = song_data.get("entitiesByUniqueId", {})

    song = next(
        (e for e in entities.values() if e.get("type") == "song"),
        None
    )

    if not song:
        msg = "Could not parse song data."
        if is_slash:
            await ctx_or_interaction.followup.send(msg)
        else:
            await ctx_or_interaction.send(msg)
        return

    title = song.get("title", "Unknown Title")
    artist = song.get("artistName", "Unknown Artist")
    thumbnail = song.get("thumbnailUrl") or song.get("artworkUrl")

    genius_url = await get_genius_link(title, artist)

    raw_platforms = song_data.get("linksByPlatform", {})

    platforms = [
        (p, d) for p, d in raw_platforms.items()
        if isinstance(d, dict) and "url" in d
    ]

    # prioritize major platforms first
    priority = ["spotify", "youtube", "appleMusic", "soundcloud"]
    platforms.sort(key=lambda x: priority.index(x[0]) if x[0] in priority else 999)

    # allow more platforms again (like old version)
    platforms = platforms[:50]

    platform_links = "\n".join(
        f"[{p.replace('_',' ').title()}]({d['url']})"
        for p, d in platforms
    )

    # ---------------------------
    # MULTI-PAGE CHUNKING (RESTORED)
    # ---------------------------
    chunks = []
    current = ""

    for line in platform_links.split("\n"):
        if len(current) + len(line) + 1 > 1000:
            chunks.append(current)
            current = line
        else:
            current += ("\n" if current else "") + line

    if current:
        chunks.append(current)


    # ---------------------------
    # SEND EMBEDS
    # ---------------------------
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

        embed.set_footer(
            text=f"Powered by song.link • Page {i+1}/{len(chunks)}"
        )

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
        data = await fetch_song_links(query)

    if not data:
        return await ctx.send("Nothing found.")

    await send_songlink_embed(ctx, data)


@tree.command(name="sl", description="Get song links across platforms")
async def slash_songlink(interaction: discord.Interaction, query: str):
    await interaction.response.defer()

    if len(query.strip()) < 3:
        return await interaction.followup.send("Give me a valid song or link.")

    data = await fetch_song_links(query)

    if not data:
        return await interaction.followup.send("Nothing found.")

    await send_songlink_embed(interaction, data, is_slash=True)

# ---------------------------
# Events
# ---------------------------
@bot.event
async def on_ready():
    global session
    session = aiohttp.ClientSession()

    await tree.sync()
    print(f"Logged in as {bot.user}")

@bot.event
async def on_close():
    if session:
        await session.close()

# ---------------------------
# Run
# ---------------------------
bot.run(TOKEN)