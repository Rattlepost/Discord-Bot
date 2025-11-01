from discord.ext import commands
import discord
import sqlite3
from config import GM_ROLE, DM_HUSH_HUT, DATABASE_PATH, PLAYER_INFO_TABLE
import math

# =========================
# Currency helpers & schema
# =========================

# Base-10 denominations: 1 gp = 10 sp = 100 cp
DENOMS = {"gp": 100, "sp": 10, "cp": 1}

def _parse_unit(unit: str) -> str:
    u = (unit or "").lower().strip()
    if u in ("g", "gp"): return "gp"
    if u in ("s", "sp"): return "sp"
    if u in ("c", "cp"): return "cp"
    raise ValueError("Unit must be gp, sp, or cp")

def _to_cp(gp: int, sp: int, cp: int) -> int:
    return gp * 100 + sp * 10 + cp

def _from_cp(total_cp: int) -> tuple[int, int, int]:
    if total_cp < 0:
        raise ValueError("Negative currency")
    gp = total_cp // 100
    rem = total_cp % 100
    sp = rem // 10
    cp = rem % 10
    return gp, sp, cp

def _ensure_currency_columns(conn, table: str):
    """Adds SILVER and COPPER columns to PLAYER_INFO_TABLE if missing (idempotent)."""
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    cols = {r[1].upper() for r in cur.fetchall()}
    if "SILVER" not in cols:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN SILVER INTEGER NOT NULL DEFAULT 0;")
    if "COPPER" not in cols:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN COPPER INTEGER NOT NULL DEFAULT 0;")
    conn.commit()

def _get_player_row(cur, player_name: str):
    cur.execute(
        f"SELECT PLAYER, LEVEL, GOLD, SILVER, COPPER, QUEST_POINTS FROM {PLAYER_INFO_TABLE} WHERE PLAYER = ?",
        (player_name,)
    )
    return cur.fetchone()

# ============
# Player Cog
# ============

class PlayerInfo(commands.Cog, name="Player Info"):
    """Commands for player info: level, gold/silver/copper, quest points."""

    def __init__(self, bot):
        self.bot = bot
        # Run a safe migration at startup to add SILVER/COPPER if missing
        conn = self.get_db_connection(DATABASE_PATH)
        if conn:
            try:
                _ensure_currency_columns(conn, PLAYER_INFO_TABLE)
            finally:
                conn.close()

    def get_db_connection(self, db_path: str):
        try:
            conn = sqlite3.connect(db_path, timeout=5)
            conn.row_factory = sqlite3.Row
            return conn
        except sqlite3.Error:
            return None

    # ----------------
    # Info & Roster
    # ----------------

    @commands.command()
    async def info(self, ctx, *, player_name: str):
        """Get player info. Users can only view their own."""
        requester = str(ctx.author.display_name)
        rq_role = discord.utils.get(ctx.author.roles, id=GM_ROLE)
        if rq_role is not None:
            await self.player_info(ctx, player_name=player_name, view_type="GM")
        elif requester == player_name:
            await self.player_info(ctx, player_name=player_name, view_type="USER")
        else:
            await ctx.reply("You can only view your own info. GMs can view anyone's info.")

    async def player_info(self, ctx, player_name: str, view_type: str):
        conn = self.get_db_connection(DATABASE_PATH)
        if not conn:
            await ctx.reply("Database connection failed. See logs for details.")
            return

        cur = conn.cursor()
        cur.execute(
            f"SELECT LEVEL, GOLD, SILVER, COPPER, QUEST_POINTS FROM {PLAYER_INFO_TABLE} WHERE PLAYER = ?",
            (player_name,)
        )
        row = cur.fetchone()
        conn.close()

        if row is None:
            await ctx.reply(f"No player named `{player_name}` found.")
            return

        embed = discord.Embed(title=f"{player_name}", color=discord.Color.blue())
        embed.add_field(name="Level", value=str(row["LEVEL"]), inline=True)
        embed.add_field(name="Gold", value=f"{row['GOLD']} gp", inline=True)
        embed.add_field(name="Silver", value=f"{row['SILVER']} sp", inline=True)
        embed.add_field(name="Copper", value=f"{row['COPPER']} cp", inline=True)
        embed.add_field(name="QP", value=str(row["QUEST_POINTS"]), inline=True)

        if view_type == "GM":
            channel = self.bot.get_channel(DM_HUSH_HUT)
            await channel.send(embed=embed)
        else:
            await ctx.author.send(embed=embed)
            await ctx.reply("I've sent your info in a DM!")

    @commands.command(name="players")
    async def players(self, ctx):
        """
        Show a summary of all players.
        GMs see exact stored balances; regular users see names only.
        """
        conn = self.get_db_connection(DATABASE_PATH)
        if not conn:
            await ctx.reply("Database connection failed.")
            return

        cur = conn.cursor()
        cur.execute(
            f"SELECT PLAYER, LEVEL, GOLD, SILVER, COPPER, QUEST_POINTS "
            f"FROM {PLAYER_INFO_TABLE} "
            f"ORDER BY PLAYER ASC"
        )
        rows = cur.fetchall()
        conn.close()

        if not rows:
            await ctx.reply("No players found in the database.")
            return

        is_gm = discord.utils.get(ctx.author.roles, id=GM_ROLE) is not None

        embed = discord.Embed(title="🏰 Player Roster", color=discord.Color.purple())

        for r in rows:
            if is_gm:
                # Show EXACT stored counts (no normalization)
                embed.add_field(
                    name=r["PLAYER"],
                    value=(
                        f"Lvl {r['LEVEL']} | "
                        f"💰 {r['GOLD']}gp {r['SILVER']}sp {r['COPPER']}cp | "
                        f"🧭 {r['QUEST_POINTS']} QP"
                    ),
                    inline=False
                )
            else:
                embed.add_field(
                    name=r["PLAYER"],
                    value="_Hidden (GM-only data)_",
                    inline=False
                )

        embed.set_footer(text="Use !info <your name> to see your details.")
        await ctx.reply(embed=embed, mention_author=False)


    # ----------------
    # Currency Admin (GM)
    # ----------------

    from typing import List

    @commands.command()
    @commands.has_role(GM_ROLE)
    async def addMoney(self, ctx, *args):
        """
        Usage:
        !addMoney <player1> [player2 ...] <amount> [gp|sp|cp]

        Examples:
        !addMoney Gorn 5 gp
        !addMoney Gorn Glib Pat 10
        !addMoney "Sir Tristan" "Lady Mave" 3 sp
        """
        # need at least: name + amount
        if len(args) < 2:
            await ctx.reply("Usage: !addMoney <player1> [player2 ...] <amount> [gp|sp|cp]")
            return

        # try to figure out if the *last* arg is a unit
        maybe_unit = args[-1].lower()
        has_unit = maybe_unit in ("g", "gp", "s", "sp", "c", "cp")

        if has_unit:
            unit_raw = maybe_unit
            amount_str = args[-2]
            name_parts = args[:-2]
        else:
            unit_raw = "gp"
            amount_str = args[-1]
            name_parts = args[:-1]

        # parse amount
        try:
            amount = int(amount_str)
        except ValueError:
            await ctx.reply("Amount must be an integer.")
            return

        # normalize unit
        try:
            unit = _parse_unit(unit_raw)  # your helper
        except ValueError as e:
            await ctx.reply(str(e))
            return

        # safety: must have at least one name
        if not name_parts:
            await ctx.reply("You must specify at least one player name.")
            return

        conn = self.get_db_connection(DATABASE_PATH)
        if not conn:
            await ctx.reply("Database connection failed.")
            return

        cur = conn.cursor()

        results = []   # to show per-player outcome
        for player_name in name_parts:
            row = _get_player_row(cur, player_name)
            if not row:
                # don't early-return — just note the failure for this name
                results.append(f"❌ `{player_name}` not found.")
                continue

            total_cp = _to_cp(row["GOLD"], row["SILVER"], row["COPPER"]) + amount * DENOMS[unit]
            gp, sp, cp = _from_cp(total_cp)

            cur.execute(
                f"UPDATE {PLAYER_INFO_TABLE} SET GOLD=?, SILVER=?, COPPER=? WHERE PLAYER=?",
                (gp, sp, cp, player_name)
            )

            results.append(f"✅ Added {amount}{unit} to `{player_name}` → {gp}gp {sp}sp {cp}cp")

        conn.commit()
        conn.close()

        # send a combined result
        msg = "\n".join(results)
        await ctx.reply(msg)

    @commands.command()
    @commands.has_role(GM_ROLE)
    async def rmMoney(self, ctx, player_name: str, amount: int, unit: str = "gp"):
        """Usage: !rmMoney <player> <amount> [gp|sp|cp]"""
        try:
            unit = _parse_unit(unit)
        except ValueError as e:
            await ctx.reply(str(e))
            return

        conn = self.get_db_connection(DATABASE_PATH)
        if not conn:
            await ctx.reply("Database connection failed.")
            return
        cur = conn.cursor()

        row = _get_player_row(cur, player_name)
        if not row:
            conn.close()
            await ctx.reply(f"Player `{player_name}` not found.")
            return

        total_cp = _to_cp(row["GOLD"], row["SILVER"], row["COPPER"])
        delta = amount * DENOMS[unit]
        if total_cp < delta:
            conn.close()
            await ctx.reply(f"❌ {player_name} doesn’t have enough funds to remove {amount}{unit}.")
            return

        total_cp -= delta
        gp, sp, cp = _from_cp(total_cp)
        cur.execute(
            f"UPDATE {PLAYER_INFO_TABLE} SET GOLD=?, SILVER=?, COPPER=? WHERE PLAYER=?",
            (gp, sp, cp, player_name)
        )
        conn.commit()
        conn.close()

        await ctx.reply(f"Removed {amount}{unit} from {player_name} → {gp}gp {sp}sp {cp}cp")

    # Back-compat aliases (gold-only)
    @commands.command()
    @commands.has_role(GM_ROLE)
    async def addGold(self, ctx, player_name: str, amount: int):
        """Alias: gold-only add. Usage: !addGold <player> <amount>"""
        await self.addMoney(ctx, player_name, amount, "gp")

    @commands.command()
    @commands.has_role(GM_ROLE)
    async def rmGold(self, ctx, player_name: str, amount: int):
        """Alias: gold-only remove. Usage: !rmGold <player> <amount>"""
        await self.rmMoney(ctx, player_name, amount, "gp")

    # ----------------
    # Player Trades
    # ----------------

    @commands.command()
    async def giveMoney(self, ctx, receiver: str, amount: int, unit: str = "gp"):
        """
        Transfer currency with auto-conversion (make change) if needed.
        Examples:
        !giveMoney Alice 15 sp  (will break gp or combine cp if needed)
        !giveMoney Bob 3 gp     (will combine sp/cp to gp if exact multiples exist)
        """
        try:
            unit = _parse_unit(unit)  # gp|sp|cp
        except ValueError as e:
            await ctx.reply(str(e))
            return
        if amount <= 0:
            await ctx.reply("Amount must be positive.")
            return

        giver = str(ctx.author.display_name)
        if giver == receiver:
            await ctx.reply("You can’t pay yourself.")
            return

        conn = self.get_db_connection(DATABASE_PATH)
        if not conn:
            await ctx.reply("Database connection failed.")
            return
        cur = conn.cursor()

        # Fetch both rows
        cur.execute(
            f"SELECT PLAYER, GOLD, SILVER, COPPER FROM {PLAYER_INFO_TABLE} WHERE PLAYER IN (?, ?)",
            (giver, receiver)
        )
        rows = {r["PLAYER"]: r for r in cur.fetchall()}
        if giver not in rows:
            conn.close()
            await ctx.reply(f"Giver `{giver}` not found in the database.")
            return
        if receiver not in rows:
            conn.close()
            await ctx.reply(f"Receiver `{receiver}` not found in the database.")
            return

        g = rows[giver]
        r = rows[receiver]

        # Work on mutable copies
        g_counts = {"gp": g["GOLD"], "sp": g["SILVER"], "cp": g["COPPER"]}
        r_counts = {"gp": r["GOLD"], "sp": r["SILVER"], "cp": r["COPPER"]}

        # Quick sanity: do they have enough total value (in cp)?
        need_cp = amount * DENOMS[unit]
        have_cp = g_counts["gp"]*DENOMS["gp"] + g_counts["sp"]*DENOMS["sp"] + g_counts["cp"]
        if have_cp < need_cp:
            conn.close()
            await ctx.reply(f"❌ You don’t have enough total funds to send {amount}{unit}.")
            return

        # Helper: make change to ensure g_counts[unit] >= amount.
        # We try (a) break higher down, then (b) combine lower up where possible.
        def ensure_units(target: str, amt: int, counts: dict) -> list[str]:
            notes = []
            def break_gp_to_sp(u):
                # 1 gp -> 10 sp
                use = min(math.ceil(u/10), counts["gp"])
                if use > 0:
                    counts["gp"] -= use
                    made = use * 10
                    counts["sp"] += made
                    notes.append(f"broke {use}gp → {made}sp")

            def break_sp_to_cp(u):
                # 1 sp -> 10 cp
                use = min(math.ceil(u/10), counts["sp"])
                if use > 0:
                    counts["sp"] -= use
                    made = use * 10
                    counts["cp"] += made
                    notes.append(f"broke {use}sp → {made}cp")

            def combine_cp_to_sp(u):
                # 10 cp -> 1 sp
                possible = counts["cp"] // 10
                use = min(u, possible)
                if use > 0:
                    counts["cp"] -= use * 10
                    counts["sp"] += use
                    notes.append(f"combined {use*10}cp → {use}sp")

            def combine_sp_to_gp(u):
                # 10 sp -> 1 gp
                possible = counts["sp"] // 10
                use = min(u, possible)
                if use > 0:
                    counts["sp"] -= use * 10
                    counts["gp"] += use
                    notes.append(f"combined {use*10}sp → {use}gp")

            if target == "cp":
                # Need cp: break sp first, then gp; also combine cp from sp if possible.
                deficit = max(0, amt - counts["cp"])
                if deficit > 0:
                    break_sp_to_cp(deficit)
                    deficit = max(0, amt - counts["cp"])
                if deficit > 0:
                    need_gp = math.ceil(deficit / 100)
                    if need_gp > 0 and counts["gp"] > 0:
                        use = min(need_gp, counts["gp"])
                        counts["gp"] -= use
                        made = use * 100
                        counts["cp"] += made
                        notes.append(f"broke {use}gp → {made}cp")

            elif target == "sp":
                # Need sp: break gp down; if still short, combine cp up to sp
                deficit = max(0, amt - counts["sp"])
                if deficit > 0:
                    break_gp_to_sp(deficit)
                    deficit = max(0, amt - counts["sp"])
                if deficit > 0:
                    combine_cp_to_sp(deficit)  # only exact multiples are combined

            elif target == "gp":
                # Need gp: combine sp to gp, then cp to sp then sp to gp.
                deficit = max(0, amt - counts["gp"])
                if deficit > 0:
                    combine_sp_to_gp(deficit)
                    deficit = max(0, amt - counts["gp"])
                if deficit > 0:
                    # First roll cp up into sp, then sp into gp
                    combine_cp_to_sp(deficit * 10)  # we might need up to deficit*10 sp
                    combine_sp_to_gp(deficit)
            return notes

        notes = ensure_units(unit, amount, g_counts)

        # After making change, ensure we actually have enough of the requested unit
        if g_counts[unit] < amount:
            conn.close()
            await ctx.reply(f"❌ Even after making change, not enough {unit} to send {amount}{unit}.")
            return

        # Apply the transfer in the requested unit (no normalization)
        g_counts[unit] -= amount
        r_counts[unit] += amount

        try:
            cur.execute("BEGIN IMMEDIATE")
            cur.execute(
                f"UPDATE {PLAYER_INFO_TABLE} SET GOLD=?, SILVER=?, COPPER=? WHERE PLAYER=?",
                (g_counts["gp"], g_counts["sp"], g_counts["cp"], giver)
            )
            cur.execute(
                f"UPDATE {PLAYER_INFO_TABLE} SET GOLD=?, SILVER=?, COPPER=? WHERE PLAYER=?",
                (r_counts["gp"], r_counts["sp"], r_counts["cp"], receiver)
            )
            conn.commit()
        except Exception as e:
            conn.rollback()
            conn.close()
            await ctx.reply(f"Transfer failed: {e}")
            return

        conn.close()

        # Build a friendly summary (include any change-making steps)
        change_line = ""
        if notes:
            change_line = "  • Change made: " + "; ".join(notes) + "\n"

        await ctx.send(
            "💸 Transfer complete!\n"
            f"- {giver} → {receiver}: {amount}{unit}\n"
            f"{change_line}"
            f"- New balances:\n"
            f"  • {giver}: {g_counts['gp']}gp {g_counts['sp']}sp {g_counts['cp']}cp\n"
            f"  • {receiver}: {r_counts['gp']}gp {r_counts['sp']}sp {r_counts['cp']}cp"
        )   

    @commands.command()
    async def giveGold(self, ctx, receiver: str, amount: int):
        """Alias: gold-only transfer."""
        await self.giveMoney(ctx, receiver, amount, "gp")


    # ----------------
    # Conversion
    # ----------------

    @commands.command()
    async def convert(self, ctx, player_name: str, amount: int, from_unit: str, to_unit: str):
        """
        Convert a player's currency by moving units, without normalizing.
        Examples:
        !convert Gorn 10 gp sp  -> -10 gp, +100 sp
        !convert Gorn 30 sp gp  -> -30 sp, +3 gp (requires exact multiple of 10sp)
        """
        try:
            f = _parse_unit(from_unit)
            t = _parse_unit(to_unit)
        except ValueError as e:
            await ctx.reply(str(e))
            return

        if f == t:
            await ctx.reply("From and to units are the same.")
            return
        if amount <= 0:
            await ctx.reply("Amount must be positive.")
            return

        conn = self.get_db_connection(DATABASE_PATH)
        if not conn:
            await ctx.reply("Database connection failed.")
            return
        cur = conn.cursor()

        cur.execute(
            f"SELECT GOLD, SILVER, COPPER FROM {PLAYER_INFO_TABLE} WHERE PLAYER = ?",
            (player_name,)
        )
        row = cur.fetchone()
        if not row:
            conn.close()
            await ctx.reply(f"Player `{player_name}` not found.")
            return

        counts = {
            "gp": row["GOLD"],
            "sp": row["SILVER"],
            "cp": row["COPPER"],
        }

        # Ensure enough source units
        if counts[f] < amount:
            conn.close()
            await ctx.reply(f"❌ {player_name} doesn’t have {amount}{f} to convert.")
            return

        # Compute how many target units we add
        if DENOMS[f] > DENOMS[t]:
            # moving down (gp->sp, sp->cp)
            add_units = amount * (DENOMS[f] // DENOMS[t])
        else:
            # moving up (sp->gp, cp->sp, cp->gp) requires exact multiple
            needed = DENOMS[t] // DENOMS[f]
            if amount % needed != 0:
                conn.close()
                await ctx.reply(f"❌ To convert {f} → {t}, use multiples of {needed}{f}.")
                return
            add_units = amount // needed

        # Apply unit move (no normalization)
        counts[f] -= amount
        counts[t] += add_units

        cur.execute(
            f"UPDATE {PLAYER_INFO_TABLE} SET GOLD=?, SILVER=?, COPPER=? WHERE PLAYER=?",
            (counts["gp"], counts["sp"], counts["cp"], player_name)
        )
        conn.commit()
        conn.close()

        await ctx.reply(
            f"Converted {amount}{f} → {add_units}{t} for {player_name} → "
            f"{counts['gp']}gp {counts['sp']}sp {counts['cp']}cp"
        )



    # ----------------
    # Level & QP (kept as-is, minor tidy)
    # ----------------

    @commands.command()
    @commands.has_role(GM_ROLE)
    async def levelUp(self, ctx, player_name: str):
        """Increase a player's level by 1. Must have adequate QP. GM only."""
        conn = self.get_db_connection(DATABASE_PATH)
        if not conn:
            await ctx.reply("Database connection failed.")
            return
        cur = conn.cursor()

        cur.execute(f"SELECT LEVEL, QUEST_POINTS FROM {PLAYER_INFO_TABLE} WHERE PLAYER = ?", (player_name,))
        row = cur.fetchone()
        if not row:
            conn.close()
            await ctx.reply(f"Player `{player_name}` not found.")
            return

        level = row["LEVEL"]
        quest_points = row["QUEST_POINTS"]
        new_level = level + 1
        cost = new_level  # adjust if your rule differs

        if quest_points < cost:
            conn.close()
            await ctx.reply(
                f"{player_name} doesn’t have enough quest points to level up.\n"
                f"(QP: {quest_points}, Needed: {cost}, Current Level: {level})"
            )
            return

        new_qp = quest_points - cost
        cur.execute(
            f"UPDATE {PLAYER_INFO_TABLE} SET LEVEL = ?, QUEST_POINTS = ? WHERE PLAYER = ?",
            (new_level, new_qp, player_name)
        )
        conn.commit()
        conn.close()

        await ctx.reply(
            f"{player_name} has leveled up to **Level {new_level}**!\n"
            f"QP spent: {cost} • QP remaining: {new_qp}"
        )

    @commands.command()
    @commands.has_role(GM_ROLE)
    async def addQP(self, ctx, *args):
        """
        Usage:
        !addQP <player1> [player2 ...] [amount]

        Examples:
        !addQP Gorn 3
        !addQP Gorn Glib Pat 2
        !addQP Gorn Glib
        (Defaults to +1 QP if amount not specified)
        """

        # Must have at least one argument (name)
        if len(args) < 1:
            await ctx.reply("Usage: !addQP <player1> [player2 ...] [amount]")
            return

        # If the last argument looks like an integer, treat it as the amount
        try:
            amount = int(args[-1])
            player_names = args[:-1]
        except ValueError:
            amount = 1
            player_names = args

        # Safety check
        if not player_names:
            await ctx.reply("You must specify at least one player name.")
            return

        conn = self.get_db_connection(DATABASE_PATH)
        if not conn:
            await ctx.reply("Database connection failed.")
            return
        cur = conn.cursor()

        results = []
        for player_name in player_names:
            cur.execute(f"SELECT QUEST_POINTS FROM {PLAYER_INFO_TABLE} WHERE PLAYER = ?", (player_name,))
            row = cur.fetchone()

            if not row:
                results.append(f"❌ `{player_name}` not found.")
                continue

            new_qp = row["QUEST_POINTS"] + amount
            cur.execute(
                f"UPDATE {PLAYER_INFO_TABLE} SET QUEST_POINTS = ? WHERE PLAYER = ?",
                (new_qp, player_name)
            )
            results.append(f"✅ Gave {amount} quest point(s) to `{player_name}` → Total: {new_qp}")

        conn.commit()
        conn.close()

        await ctx.reply("\n".join(results))


    # ----------------
    # Player admin (unchanged behavior)
    # ----------------

    @commands.command()
    @commands.has_role(GM_ROLE)
    async def addPlayer(self, ctx, player_name: str, level: int = 2):
        """
        Add a new player. Gold defaults to 10gp, Silver 0, Copper 0, QP 0.
        """
        conn = self.get_db_connection(DATABASE_PATH)
        if not conn:
            await ctx.reply("Database connection failed.")
            return
        cur = conn.cursor()

        cur.execute(f"SELECT 1 FROM {PLAYER_INFO_TABLE} WHERE PLAYER = ?", (player_name,))
        if cur.fetchone():
            conn.close()
            await ctx.reply(f"Player `{player_name}` already exists.")
            return

        cur.execute(
            f"INSERT INTO {PLAYER_INFO_TABLE} (PLAYER, LEVEL, GOLD, SILVER, COPPER, QUEST_POINTS) VALUES (?, ?, ?, ?, ?, ?)",
            (player_name, level, 10, 0, 0, 0)
        )
        conn.commit()
        conn.close()

        await ctx.reply(f"Added `{player_name}` at Level {level}, 10gp 0sp 0cp, 0 quest points.")

    @commands.command()
    @commands.has_role(GM_ROLE)
    async def rmPlayer(self, ctx, player_name: str):
        """Remove a player from the database. GM only."""
        conn = self.get_db_connection(DATABASE_PATH)
        if not conn:
            await ctx.reply("Database connection failed.")
            return
        cur = conn.cursor()

        cur.execute(f"SELECT 1 FROM {PLAYER_INFO_TABLE} WHERE PLAYER = ?", (player_name,))
        if not cur.fetchone():
            conn.close()
            await ctx.reply(f"Player `{player_name}` not found.")
            return

        cur.execute(f"DELETE FROM {PLAYER_INFO_TABLE} WHERE PLAYER = ?", (player_name,))
        conn.commit()
        conn.close()

        await ctx.reply(f"Removed player `{player_name}` from the database.")

# --------------
# Cog setup
# --------------

async def setup(bot):
    await bot.add_cog(PlayerInfo(bot))
