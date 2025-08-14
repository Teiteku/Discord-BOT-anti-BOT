import os, time, re
import discord
from discord.ext import commands
from collections import deque, defaultdict
from dotenv import load_dotenv

# ====== 環境変数 ======
load_dotenv()  # ローカル実行時のみ有効。Renderでは不要だが置いておいてOK
TOKEN = os.environ.get("DISCORD_TOKEN", "")
GUILD_ID = int(os.environ.get("GUILD_ID", "0"))  # 即UI表示したいサーバーID。不要なら0
LOG_CH_ID = int(os.environ.get("MOD_LOG_CHANNEL_ID", "0"))

# ====== Intents ======
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

# ====== Bot ======
bot = commands.Bot(command_prefix="!", intents=intents)

# ====== 簡易モデレーション設定 ======
NG_WORDS = {"死ね", "荒らし", "カジノ招待"}  # /setng で追加、/delng で削除、/nglist で確認
WINDOW_SEC = 6          # 速度スパム検知ウィンドウ（秒）
MAX_MSG_PER_WIN = 8     # 短時間の最大発言
MAX_DUPLICATES = 3      # 同一文連投の閾値
MAX_MENTIONS = 5        # 一度にメンション許容量

user_msgs = defaultdict(lambda: deque())
user_last_text = defaultdict(lambda: deque(maxlen=MAX_DUPLICATES))

INVITE_RE = re.compile(r"(?:https?://)?discord(?:\.gg|\.com/invite)/\S+", re.I)

async def mod_log(guild: discord.Guild, text: str):
    if LOG_CH_ID:
        ch = guild.get_channel(LOG_CH_ID)
        if ch:
            await ch.send(text)

# ====== 起動時 ======
@bot.event
async def on_ready():
    # スラッシュコマンド同期
    if GUILD_ID:
        guild = discord.Object(id=GUILD_ID)
        await bot.tree.sync(guild=guild)   # 指定ギルドに即反映（開発・テスト向け）
        print(f"✅ Synced commands to guild {GUILD_ID}")
    else:
        await bot.tree.sync()               # グローバル同期（最大1時間かかる）
        print("✅ Synced global commands")
    print(f"✅ Logged in as {bot.user} (ID: {bot.user.id})")

# ====== メンバー参加ログ（任意） ======
@bot.event
async def on_member_join(member: discord.Member):
    try:
        age_days = (discord.utils.utcnow() - member.created_at).days
        await mod_log(member.guild, f"🕒 新規参加: {member}（作成 {age_days}日）")
    except Exception:
        pass

# ====== メッセージ監視（NGワード/スパム） ======
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    uid = message.author.id
    now = time.time()
    content = message.content or ""

    # NGワード削除
    if any(w in content for w in NG_WORDS):
        try:
            await message.delete()
            await message.channel.send(
                f"{message.author.mention} 禁止語はNGです。", delete_after=5
            )
            await mod_log(message.guild, f"🧹 削除: {message.author} > {content[:80]}")
        except discord.Forbidden:
            pass
        return

    # メンション過多・@everyone/@here 連投
    is_everyone = message.mention_everyone
    mentions_count = len(message.mentions)
    if is_everyone or mentions_count >= MAX_MENTIONS:
        dq = user_msgs[str(uid) + "_everyone"]
        dq.append(now)
        while dq and now - dq[0] > WINDOW_SEC:
            dq.popleft()
        if len(dq) > 2:  # 3回目で削除
            try:
                await message.delete()
                await mod_log(message.guild, f"🚨 @everyone/@here連投: {message.author}")
            except discord.Forbidden:
                pass
            return

    # 速度スパム
    dq = user_msgs[uid]
    dq.append(now)
    while dq and now - dq[0] > WINDOW_SEC:
        dq.popleft()
    if len(dq) > MAX_MSG_PER_WIN:
        try:
            await message.delete()
            await message.channel.send(
                f"{message.author.mention} 連投は禁止です。", delete_after=5
            )
            await mod_log(message.guild, f"🚨 速度スパム: {message.author}")
        except discord.Forbidden:
            pass
        return

    # 同一文連投
    lastq = user_last_text[uid]
    if lastq and all(x == content for x in lastq):
        try:
            await message.delete()
            await message.channel.send(
                f"{message.author.mention} 同じ内容の連投は禁止です。", delete_after=5
            )
            await mod_log(message.guild, f"🔁 重複スパム: {message.author}")
        except discord.Forbidden:
            pass
        return
    lastq.append(content)

    # 下のコマンド処理（prefixコマンド用）に渡す
    await bot.process_commands(message)

# ====== スラッシュコマンド群（管理者不要で実行可能） ======

@bot.tree.command(name="ping", description="Botの応答確認")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message("Pong!")

@bot.tree.command(name="setng", description="NGワードを追加（スペース区切り）")
async def setng(interaction: discord.Interaction, words: str):
    added = {w.strip() for w in words.split() if w.strip()}
    if not added:
        await interaction.response.send_message("追加する語がありません。", ephemeral=True)
        return
    NG_WORDS.update(added)
    await interaction.response.send_message(f"NGワード追加: {', '.join(sorted(added))}")

@bot.tree.command(name="nglist", description="現在のNGワード一覧を表示")
async def nglist(interaction: discord.Interaction):
    if NG_WORDS:
        await interaction.response.send_message(f"現在のNGワード: {', '.join(sorted(NG_WORDS))}")
    else:
        await interaction.response.send_message("現在、NGワードはありません。")

@bot.tree.command(name="delng", description="指定したNGワードを削除（スペース区切り）")
async def delng(interaction: discord.Interaction, words: str):
    targets = {w.strip() for w in words.split() if w.strip()}
    removed = set()
    for w in list(targets):
        if w in NG_WORDS:
            NG_WORDS.remove(w)
            removed.add(w)
    if removed:
        await interaction.response.send_message(f"削除しました: {', '.join(sorted(removed))}")
    else:
        await interaction.response.send_message("削除できる語がありませんでした。", ephemeral=True)

@bot.tree.command(name="mute", description="指定ユーザーをタイムアウト（秒）")
async def mute(interaction: discord.Interaction, member: discord.Member, seconds: int = 600):
    # 実行者は権限不要だが、Bot側に「メンバーをタイムアウト」の権限が必要
    until = discord.utils.utcnow() + discord.timedelta(seconds=max(1, seconds))
    try:
        await member.timeout(until, reason=f"Requested by {interaction.user}")
        await interaction.response.send_message(
            f"{member.mention} を {seconds} 秒タイムアウトしました。"
        )
        await mod_log(interaction.guild, f"⏱️ Timeout: {member} ({seconds}s) by {interaction.user}")
    except discord.Forbidden:
        await interaction.response.send_message(
            "Botにタイムアウト権限がありません。ロール/権限を確認してください。",
            ephemeral=True
        )
    except Exception as e:
        await interaction.response.send_message(f"エラー: {e}", ephemeral=True)

# ====== 起動 ======
if not TOKEN:
    raise SystemExit("DISCORD_TOKEN が未設定です。Renderの Environment Variables に設定してください。")
bot.run(TOKEN)