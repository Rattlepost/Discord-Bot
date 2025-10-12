from discord.ext import commands
import discord
import sqlite3
from config import GM_ROLE, DATABASE_PATH, QUEST_BOARD_TABLE

class Quests(commands.Cog, name="Quests"):
    """View and manage quests."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _get_db(self, db_path: str):
        try:
            conn = sqlite3.connect(db_path, timeout=5)
            conn.row_factory = sqlite3.Row  # access columns by name
            return conn
        except sqlite3.Error:
            return None

    @commands.command(name="addQuest")
    @commands.has_role(GM_ROLE)
    async def addQuest(self, ctx, title: str, qtype: str, *, description: str):
        """
        (GM only) Add a quest with title, type, and description.
        Usage:
          !addQuest "Goblin Menace" U Drive out the goblins raiding the northern farms.
        """
        qtype = (qtype or "").strip().upper()[:1] or "U"

        conn = self._get_db(DATABASE_PATH)
        cur = conn.cursor()
        cur.execute(
            f"INSERT INTO {QUEST_BOARD_TABLE} (NAME, TYPE, DESCRIPTION) VALUES (?, ?, ?)",
            (title, qtype, description)
        )
        quest_id = cur.lastrowid
        conn.commit()
        conn.close()

        await ctx.reply(f"✅ Added quest **[{quest_id}] ({qtype}) {title}**")

    @commands.command()
    @commands.has_role(GM_ROLE)
    async def rmQuest(self, ctx, quest_id: int):
        """(GM only) Remove a quest by id: !rmQuest <id>"""

        conn = self._get_db(DATABASE_PATH)
        cur = conn.cursor()
        # Use ROWID, not NAME
        cur.execute(f"DELETE FROM {QUEST_BOARD_TABLE} WHERE ROWID = ?", (quest_id,))
        removed = cur.rowcount
        conn.commit()
        conn.close()

        if removed:
            await ctx.reply(f"🗑️ Removed quest [{quest_id}].")
        else:
            await ctx.reply(f"❌ No quest found with id [{quest_id}].")

    # ---------- Player commands ----------
    @commands.command(name="quests")
    async def quests(self, ctx, show_id: str = None):
        """
        Show the current quest board.
        Usage:
        !quests         → hides quest IDs
        !quests id      → shows quest IDs
        """
        # Normalize argument
        show_id = (show_id or "").lower() in ["id", "ids", "true", "show"]

        conn = self._get_db(DATABASE_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(f"""
            SELECT
                ROWID AS id,
                NAME,
                TYPE,
                substr(COALESCE(DESCRIPTION, ''), 1, 200) AS blurb
            FROM {QUEST_BOARD_TABLE}
            ORDER BY ROWID ASC
            LIMIT 10
        """)
        rows = cur.fetchall()
        conn.close()

        if not rows:
            await ctx.reply("📜 The quest board is empty.")
            return

        embed = discord.Embed(
            title="📜 Quest Board",
            description="Use `!quest <id>` to view full details.",
            color=discord.Color.gold()
        )

        for r in rows:
            blurb = (r["blurb"] or "").rstrip()
            if len(blurb) == 200:
                blurb += "…"

            # add ID conditionally
            if show_id:
                blurb += f"\n*Quest ID:* `{r['id']}`"

            embed.add_field(
                name=f"{r['NAME']} ({r['TYPE']})",
                value=blurb if blurb else "_No description preview_",
                inline=False
            )

        footer_note = ""
        if show_id:
            footer_note += "IDs visible"
        embed.set_footer(text=footer_note)

        await ctx.reply(embed=embed, mention_author=False)

    @commands.command(name="quest")
    async def quest(self, ctx, quest_id: int):
        """Show one quest's full details: !quest <id>"""
        conn = self._get_db(DATABASE_PATH)
        # Make rows accessible by column name
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            f"SELECT NAME, TYPE, DESCRIPTION FROM {QUEST_BOARD_TABLE} WHERE ROWID = ?",
            (quest_id,)
        )
        r = cur.fetchone()
        conn.close()

        if not r:
            await ctx.reply(f"❌ No quest found with id [{quest_id}].")
            return

        embed = discord.Embed(
            title=f"📜 {r['NAME']} ({r['TYPE']})",
            description=r["DESCRIPTION"],
            color=discord.Color.green()
        )
        embed.set_footer(text=f"Quest ID: {quest_id}")

        await ctx.reply(embed=embed, mention_author=False)

async def setup(bot: commands.Bot):
    await bot.add_cog(Quests(bot))