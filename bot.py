import os
import json
import time
from threading import Thread
from collections import defaultdict, deque

from flask import Flask
import discord
from discord.ext import commands
from discord import app_commands

# ------------------------
# 環境変数
# ------------------------
TOKEN = os.environ.get("DISCORD_TOKEN")
PORT = int(os.environ.get("PORT", 8080))  # Renderで使う場合

# ------------------------
# Flask 設定
# ------------------------
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!"

# ------------------------
# JSONファイル管理
# ------------------------
NG_FILE = "ng_words.json"
SPAM_FILE = "spam_settings.json"
LOG_FILE = "log_channel.json"
PERM_FILE = "ng_perms.json"

def load_json(file, default={}):
    if os.path.exists(file):
        with open(file, "r", encoding="utf-8") as f:
            return json.load(f)
    return default

def save_json(file, data):
    with open(file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

guild_ng_words = load_json(NG_FILE, {})
server_spam_settings = load_json(SPAM_FILE, {})
log_channels = load_json(LOG_FILE, {})
ng_permissions = load_json(PERM_FILE, {})

# ------------------------
# Discord Bot 設定
# ------------------------
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ------------------------
# スパム管理
# ------------------------
user_msgs = defaultdict(lambda: deque())
user_last_text = defaultdict(lambda: deque(maxlen=3))

# ------------------------
# 権限チェック
# ------------------------
def check_permission(user: discord.Member):
    if user.guild_permissions.administrator:
        return True
    gid = str(user.guild.id)
    allowed_roles = ng_permissions.get(gid, [])
    return any(role.id in allowed_roles for role in user.roles)

# ------------------------
# モデレーションログUI
# ------------------------
class WarnButtons(discord.ui.View):
    def __init__(self, target_user: discord.Member):
        super().__init__(timeout=None)
        self.target_user = target_user

    @discord.ui.button(label="確認", style=discord.ButtonStyle.primary)
    async def confirm(self, interaction, button):
        await interaction.message.edit(view=None)
        await interaction.response.send_message("✅ 確認しました。", ephemeral=True)

    @discord.ui.button(label="タイムアウト", style=discord.ButtonStyle.secondary)
    async def timeout_btn(self, interaction, button):
        await interaction.message.edit(view=None)
        if interaction.user.guild_permissions.moderate_members:
            await self.target_user.timeout(duration=60)
            await interaction.response.send_message(f"⏱ {self.target_user} を1分タイムアウトしました。", ephemeral=True)
        else:
            await interaction.response.send_message("❌ 権限がありません。", ephemeral=True)

    @discord.ui.button(label="キック", style=discord.ButtonStyle.danger)
    async def kick_btn(self, interaction, button):
        await interaction.message.edit(view=None)
        if interaction.user.guild_permissions.kick_members:
            await self.target_user.kick(reason="警告ログから")
            await interaction.response.send_message(f"👢 {self.target_user} をキックしました。", ephemeral=True)
        else:
            await interaction.response.send_message("❌ 権限がありません。", ephemeral=True)

    @discord.ui.button(label="BAN", style=discord.ButtonStyle.danger)
    async def ban_btn(self, interaction, button):
        await interaction.message.edit(view=None)
        if interaction.user.guild_permissions.ban_members:
            await self.target_user.ban(reason="警告ログから")
            await interaction.response.send_message(f"🔨 {self.target_user} をBANしました。", ephemeral=True)
        else:
            await interaction.response.send_message("❌ 権限がありません。", ephemeral=True)

# ------------------------
# モデレーションログ送信
# ------------------------
async def mod_log(guild: discord.Guild, user: discord.Member, reason: str, content: str):
    gid = str(guild.id)
    ch_id = log_channels.get(gid)
    if not ch_id:
        return
    ch = guild.get_channel(int(ch_id))
    if not isinstance(ch, discord.TextChannel):
        return
    embed = discord.Embed(title="⚠️ 警告ログ", color=discord.Color.red(), timestamp=discord.utils.utcnow())
    embed.add_field(name="ユーザー", value=f"{user} ({user.id})", inline=False)
    embed.add_field(name="理由", value=reason, inline=False)
    embed.add_field(name="内容", value=content[:1024] or "なし", inline=False)
    view = WarnButtons(user)
    await ch.send(embed=embed, view=view)

# ------------------------
# イベント
# ------------------------
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"✅ ログイン: {bot.user}")

@bot.event
async def on_message(message):
    if message.author.bot or not message.guild:
        return

    uid = message.author.id
    now = time.time()
    content = message.content or ""

    # NGワードチェック
    IGNORE_WORDS = {"しまね"}
    ng_words = set(guild_ng_words.get(str(message.guild.id), []))
    if any(w in content for w in ng_words if w not in IGNORE_WORDS):
        try:
            await message.delete()
            await message.channel.send(f"{message.author.mention} 禁止語です。", delete_after=5)
            await mod_log(message.guild, message.author, "NGワード使用", content)
        except discord.Forbidden:
            pass
        return

    # スパムチェック
    default_setting = {"window_sec":6, "max_msg":8, "max_duplicates":3, "max_mentions":5}
    setting = server_spam_settings.get(str(message.guild.id), default_setting)
    window_sec = setting.get("window_sec",6)
    max_msg = setting.get("max_msg",8)
    max_duplicates = setting.get("max_duplicates",3)
    max_mentions = setting.get("max_mentions",5)

    dq = user_msgs[uid]
    dq.append(now)
    while dq and now - dq[0] > window_sec:
        dq.popleft()
    if len(dq) > max_msg:
        try:
            await message.delete()
            await message.channel.send(f"{message.author.mention} 連投禁止です。", delete_after=5)
            await mod_log(message.guild, message.author, "速度スパム", content)
        except discord.Forbidden:
            pass
        return

    lastq = user_last_text[uid]
    if lastq and all(x == content for x in lastq):
        try:
            await message.delete()
            await message.channel.send(f"{message.author.mention} 同じ内容の連投は禁止です。", delete_after=5)
            await mod_log(message.guild, message.author, f"{max_duplicates}回同内容連投", content)
        except discord.Forbidden:
            pass
        return
    lastq.append(content)

    await bot.process_commands(message)

# ------------------------
# /コマンド 全部
# ------------------------
# NG追加
@app_commands.command(name="ng追加", description="NGワードを追加（管理者/権限ロール専用）")
@app_commands.describe(words="スペース区切りで追加")
async def ng_add(interaction: discord.Interaction, words: str):
    if not check_permission(interaction.user):
        await interaction.response.send_message("❌ 権限がありません。", ephemeral=True)
        return
    gid = str(interaction.guild.id)
    if gid not in guild_ng_words:
        guild_ng_words[gid] = []
    added = [w.strip() for w in words.split() if w.strip()]
    guild_ng_words[gid].extend(added)
    save_json(NG_FILE, guild_ng_words)
    await interaction.response.send_message(f"✅ NG追加: {', '.join(added)}")

# NG一覧
@app_commands.command(name="ng一覧", description="NGワード一覧表示")
async def ng_list(interaction: discord.Interaction):
    ngs = guild_ng_words.get(str(interaction.guild.id), [])
    if ngs:
        await interaction.response.send_message(f"📜 NGワード: {', '.join(ngs)}")
    else:
        await interaction.response.send_message("ℹ️ NGワードはありません。")

# NG削除UI
@app_commands.command(name="ng削除_ui", description="選択式でNGワードを削除（管理者/権限ロール専用）")
async def ng_del_ui(interaction: discord.Interaction):
    if not check_permission(interaction.user):
        await interaction.response.send_message("❌ 権限がありません。", ephemeral=True)
        return
    ngs = list(guild_ng_words.get(str(interaction.guild.id), []))
    if not ngs:
        await interaction.response.send_message("ℹ️ NGワードはありません。")
        return
    class Select(discord.ui.Select):
        def __init__(self):
            options = [discord.SelectOption(label=w) for w in ngs[:25]]
            super().__init__(placeholder="削除するNGワードを選択", options=options, min_values=1, max_values=len(options))
        async def callback(self, interaction2: discord.Interaction):
            gid = str(interaction2.guild.id)
            removed = self.values
            guild_ng_words[gid] = [w for w in guild_ng_words[gid] if w not in removed]
            save_json(NG_FILE, guild_ng_words)
            await interaction2.response.send_message(f"🗑 NG削除: {', '.join(removed)}", ephemeral=True)
    view = discord.ui.View()
    view.add_item(Select())
    await interaction.response.send_message("選択して削除してください", view=view, ephemeral=True)

# NG権限設定
@app_commands.command(name="ng権限設定", description="NG追加削除権限ロール設定（管理者専用）")
@app_commands.describe(role="権限を与えるロール")
async def ng_perm(interaction: discord.Interaction, role: discord.Role):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
        return
    gid = str(interaction.guild.id)
    if gid not in ng_permissions:
        ng_permissions[gid] = []
    if role.id not in ng_permissions[gid]:
        ng_permissions[gid].append(role.id)
        save_json(PERM_FILE, ng_permissions)
        await interaction.response.send_message(f"✅ {role.name} にNG権限を付与しました。")
    else:
        await interaction.response.send_message("ℹ️ すでに権限があります。")

# NG権限削除
@app_commands.command(name="ng権限削除", description="NG追加削除権限ロール削除（管理者専用）")
@app_commands.describe(role="削除する権限ロール")
async def ng_perm_remove(interaction: discord.Interaction, role: discord.Role):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
        return
    gid = str(interaction.guild.id)
    if gid in ng_permissions and role.id in ng_permissions[gid]:
        ng_permissions[gid].remove(role.id)
        save_json(PERM_FILE, ng_permissions)
        await interaction.response.send_message(f"✅ {role.name} のNG権限を削除しました。")
    else:
        await interaction.response.send_message("ℹ️ 権限がありません。")

# スパム設定
@app_commands.command(name="スパム設定", description="サーバーごとのスパム設定（管理者/権限ロール専用）")
@app_commands.describe(window_sec="秒", max_msg="連投数", max_duplicates="同一文連投数", max_mentions="メンション数")
async def spam_setting(interaction: discord.Interaction, window_sec: int=6, max_msg: int=8, max_duplicates: int=3, max_mentions: int=5):
    if not check_permission(interaction.user):
        await interaction.response.send_message("❌ 権限がありません。", ephemeral=True)
        return
    gid = str(interaction.guild.id)
    server_spam_settings[gid] = {"window_sec":window_sec, "max_msg":max_msg, "max_duplicates":max_duplicates, "max_mentions":max_mentions}
    save_json(SPAM_FILE, server_spam_settings)
    await interaction.response.send_message(f"✅ スパム設定を更新しました。\n時間:{window_sec}s, 連投:{max_msg}, 同文:{max_duplicates}, メンション:{max_mentions}")

# ログチャンネル設定
@app_commands.command(name="ログチャンネル設定", description="モデレーションログ送信チャンネル設定（管理者専用）")
@app_commands.describe(channel="ログを送るチャンネル")
async def log_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ 管理者専用です。", ephemeral=True)
        return
    log_channels[str(interaction.guild.id)] = channel.id
    save_json(LOG_FILE, log_channels)
    await interaction.response.send_message(f"✅ ログチャンネルを {channel.mention} に設定しました。")

# help
@app_commands.command(name="help", description="コマンド一覧表示")
async def help_command(interaction: discord.Interaction):
    txt = """
**NG管理コマンド**
/ng追加 [単語] - NG追加
/ng一覧 - NG一覧
/ng削除_ui - 選択式NG削除
/ng権限設定 [ロール] - NG権限ロール付与
/ng権限削除 [ロール] - NG権限ロール削除

**スパム管理**
/スパム設定 [秒] [連投] [同文] [メンション] - スパム設定

**ログ管理**
/ログチャンネル設定 [チャンネル] - モデレーションログ設定
/help - コマンド一覧
"""
    await interaction.response.send_message(txt, ephemeral=True)

# 過去メッセージ削除
@app_commands.guild_only()
@bot.tree.command(name="clearuser", description="指定ユーザーの過去メッセージを削除します")
async def clearuser(interaction: discord.Interaction, user: discord.User, limit: int = 100):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("⚠️ このコマンドは管理者のみ実行可能です。", ephemeral=True)
        return
    deleted = 0
    async for msg in interaction.channel.history(limit=limit):
        if msg.author.id == user.id:
            await msg.delete()
            deleted += 1
    await interaction.response.send_message(f"✅ {deleted}件のメッセージを削除しました。")

# コマンド登録
bot.tree.add_command(ng_add)
bot.tree.add_command(ng_list)
bot.tree.add_command(ng_del_ui)
bot.tree.add_command(ng_perm)
bot.tree.add_command(ng_perm_remove)
bot.tree.add_command(spam_setting)
bot.tree.add_command(log_channel)
bot.tree.add_command(help_command)
bot.tree.add_command(clearuser)

# ------------------------
# Discord Bot をスレッドで起動
# ------------------------
def run_discord():
    bot.run(TOKEN)

# ------------------------
# Render 用に Flask と Bot 並行起動
# ------------------------
if __name__ == "__main__":
    Thread(target=run_discord).start()
    app.run(host="0.0.0.0", port=PORT)