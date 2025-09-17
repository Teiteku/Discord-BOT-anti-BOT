import discord
from discord.ext import commands, tasks
from discord import app_commands
from utils import add_entry, get_guild_settings, update_guild_settings, load_blacklist, create_session, check_session
from datetime import datetime

BOT_TOKEN = "YOUR_BOT_TOKEN"

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    await bot.tree.sync()
    scan_audit_logs.start()

# --------------------------
# /addBlack 手動追加
# --------------------------
@bot.tree.command(name="addBlack", description="ブラックリストに手動追加")
@app_commands.describe(user="対象ユーザー", type="理由", punishment="処罰メモ")
async def addBlack(interaction: discord.Interaction, user: discord.User, type: str, punishment: str):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("管理者のみ使用可能です。", ephemeral=True)
        return
    add_entry(interaction.guild.id, user.id, type, punishment)
    await interaction.response.send_message(f"{user.name} をブラックリストに追加しました。")

# --------------------------
# /checkBlack 確認
# --------------------------
@bot.tree.command(name="checkBlack", description="ユーザーのブラックリスト確認")
@app_commands.describe(user="対象ユーザー")
async def checkBlack(interaction: discord.Interaction, user: discord.User):
    blacklist = load_blacklist()
    data = blacklist.get(str(interaction.guild.id), {}).get(str(user.id))
    if data:
        msg = "\n".join([f"{e['type']} | {e['punishment']} | {e['timestamp']}" for e in data])
        await interaction.response.send_message(f"{user.name} の履歴:\n{msg}", ephemeral=True)
    else:
        await interaction.response.send_message(f"{user.name} はブラックリストに入っていません。", ephemeral=True)

# --------------------------
# /setPassword Discord側パスワード設定
# --------------------------
@bot.tree.command(name="setPassword", description="Webアクセス用パスワード設定")
@app_commands.describe(password="4〜6文字のパスワード")
async def setPassword(interaction: discord.Interaction, password: str):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("管理者のみ使用可能です。", ephemeral=True)
        return
    if not (4 <= len(password) <= 6):
        await interaction.response.send_message("パスワードは4〜6文字で設定してください。", ephemeral=True)
        return
    update_guild_settings(interaction.guild.id, password=password)
    # 自動でセッション作成
    create_session(interaction.guild.id, interaction.user.id)
    await interaction.response.send_message(f"パスワードを設定しました。Webアクセス可能です（セッション作成済み）。", ephemeral=True)

# --------------------------
# 自動監査ログ
# --------------------------
@tasks.loop(minutes=10)
async def scan_audit_logs():
    for guild in bot.guilds:
        settings = get_guild_settings(guild.id)
        if not settings["auto_mode"] or not settings["watch_channel_id"]:
            continue
        channel = guild.get_channel(settings["watch_channel_id"])
        if channel:
            async for entry in guild.audit_logs(limit=50):
                if entry.target:
                    if entry.action.name in ["kick", "ban", "timeout"]:
                        add_entry(guild.id, entry.target.id, entry.action.name, entry.reason or "理由なし")

bot.run(BOT_TOKEN)