# Discord Bot on Render

## 必要ファイル
- `bot.py` … メインコード
- `requirements.txt` … 依存ライブラリ
- `.env.example` … 環境変数のひな型（このまま公開OK。**.envは公開しない**）

## 使い方（超ざっくり）
1. この3ファイルを GitHub リポジトリに追加（スマホブラウザ/アプリどちらでもOK）
2. Discord Developer Portal で Bot を作ってトークン発行
3. Botを招待  
   - 招待URL例：
     ```
     https://discord.com/oauth2/authorize?client_id=YOUR_CLIENT_ID&scope=bot%20applications.commands&permissions=0
     ```
   - チャンネルで「メッセージ送信」「メッセージ読み取り」は付与しておく
4. Render で New → Web Service → GitHubリポジトリを選択  
   - Environment: Python 3  
   - Start Command: `python3 bot.py`  
   - Environment Variables へ以下を追加  
     - `DISCORD_TOKEN` … Botトークン  
     - `GUILD_ID` … 即UI反映したいサーバーID（なければ 0）  
     - `MOD_LOG_CHANNEL_ID` … ログ用チャンネルID（なければ 0）

5. デプロイ後、Discordで `/ping` が表示され「Pong!」が返ればOK

## よくあるつまづき
- スラッシュコマンドが出ない  
  - Bot招待時のスコープに `applications.commands` を入れて再招待  
  - `GUILD_ID` を設定しているか確認（ギルド同期だと即反映）
  - Discordクライアントを再起動
- `/mute` が失敗する  
  - **Botロール**に「メンバーをタイムアウト」権限が必要