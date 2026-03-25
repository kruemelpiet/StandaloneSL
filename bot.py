import os
import re
import discord
import aiohttp
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv

# ---------------------------
# Load environment variables
# ---------------------------
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
GENIUS_API_KEY = os.getenv("GENIUS_API_KEY")
ALLOWED_CHANNEL_ID = int(os.getenv("ALLOWED_CHANNEL_ID", 0))  # optional, set 0 to disable

# ---------------------------
# Discord setup
# ---------------------------
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# ---------------------------
# Global aiohttp session
# ---------------------------
session: aiohttp.ClientSession | None = None

async def get_session():
    global session
    if session is None or session.closed:
        session = aiohttp.ClientSession()
    return session

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
# API calls
# ---------------------------
async def fetch_song_links(query: str, ctx_or_interaction=None, is_slash=False):
    try:
        s = await get_session()
        async with s.get(
            "https://api.song.link/v1-alpha.1/links",
            params={"url": query, "userCountry": "US"},
        ) as r:
            if r.status != 200:
                raise Exception(f"Status {r.status}")
            return await r.json()
    except Exception as e:
        msg = f"Error fetching song data: {e}"
        if ctx_or_interaction:
            try:
                if is_slash:
                    await ctx_or_interaction.followup.send(msg)
                else:
                    await ctx_or_interaction.send(msg)
            except:
                pass
        return None

async def get_genius_link(title: str, artist: str):
    if not title or not GENIUS_API_KEY:
        return None
    clean_title_str = clean_song_title(title)
    query = f"{clean_title_str} {artist}"
    try:
        s = await get_session()
        async with s.get(
            "https://api.genius.com/search",
            params={"q": query},
            headers={"Authorization": f"Bearer {GENIUS_API_KEY}"},
        ) as r:
            data = await r.json()
        hits = data.get("response", {}).get("hits", [])
        for hit in hits:
            result = hit.get("result", {})
            result_title = result.get("title", "").lower()
            result_artist = result.get("primary_artist", {}).get("name", "").lower()
            if clean_title_str.lower() in result_title and artist.lower() in result_artist:
                return result.get("url")
        return hits[0]["result"].get("url") if hits else None
    except:
        return None

# ---------------------------
# Embed builder
# ---------------------------
async def send_songlink_embed(ctx_or_interaction, song_data, is_slash=False):
    entities = song_data.get("entitiesByUniqueId", {})
    song = next((e for e in entities.values() if e.get("type") == "song"), None)
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
    platforms = [(p, d) for p, d in raw_platforms.items() if isinstance(d, dict) and "url" in d]

    # prioritize major platforms
    priority = ["spotify", "youtube", "appleMusic", "soundcloud"]
    platforms.sort(key=lambda x: priority.index(x[0]) if x[0] in priority else 999)
    platforms = platforms[:50]  # limit

    platform_links = "\n".join(f"[{p.replace('_',' ').title()}]({d['url']})" for p, d in platforms)

    # split into 1000-char chunks
    chunks, current = [], ""
    for line in platform_links.split("\n"):
        if len(current) + len(line) + 1 > 1000:
            chunks.append(current)
            current = line
        else:
            current += ("\n" if current else "") + line
    if current:
        chunks.append(current)

    # send embeds
    for i, chunk in enumerate(chunks):
        embed = discord.Embed(
            title=title,
            url=genius_url if genius_url else None,
            description=f"by {artist}",
            color=0x1DB954,
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
    if ALLOWED_CHANNEL_ID and ctx.channel.id != ALLOWED_CHANNEL_ID:
        return await ctx.send("This command is not allowed in this channel.")

    async with ctx.typing():
        song_data = await fetch_song_links(query, ctx)
    if not song_data:
        return await ctx.send("Nothing found.")

    await send_songlink_embed(ctx, song_data)

@tree.command(name="sl", description="Get song links across platforms")
async def slash_songlink(interaction: discord.Interaction, query: str):
    if ALLOWED_CHANNEL_ID and interaction.channel_id != ALLOWED_CHANNEL_ID:
        await interaction.response.send_message("Not allowed here.", ephemeral=True)
        return

    await interaction.response.defer()
    song_data = await fetch_song_links(query, interaction, is_slash=True)
    if not song_data:
        await interaction.followup.send("Nothing found.")
        return

    await send_songlink_embed(interaction, song_data, is_slash=True)

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