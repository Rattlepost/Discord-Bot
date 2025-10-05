from discord.ext import commands
import discord
import sqlite3
from config import GM_ROLE, DM_HUSH_HUT

PLAYER_INFO_PATH = "player_info.db"      
PLAYER_INFO_TABLE_NAME = "player_info"

class PlayerInfo(commands.Cog, name="Player Info"):
    '''Commands for player info: level, gold, quest points.'''

    def __init__(self, bot):
        self.bot = bot

    def get_db_connection(self, db_path: str):
        try:
            conn = sqlite3.connect(db_path, timeout=5)
            conn.row_factory = sqlite3.Row  # access columns by name
            return conn
        except sqlite3.Error:
            return None

    @commands.command()
    async def info(self, ctx, *, player_name: str):
        '''Get player info. Users can only view their own.'''
        requester = str(ctx.author.display_name)
        rq_role = discord.utils.get(ctx.author.roles, id=GM_ROLE)
        if rq_role is not None:
            await self.player_info(ctx, player_name=player_name, type="GM")
        elif requester == player_name:
            await self.player_info(ctx, player_name=player_name, type="USER")
        else:
            await ctx.reply("You can only view your own info. GMs can view anyone's info.")

    async def player_info(self, ctx, player_name: str, type: str):
        conn = self.get_db_connection(PLAYER_INFO_PATH)
        if not conn:
            await ctx.reply("Database connection failed. See logs for details.")
            return
        
        cur = conn.cursor()
        sql = f"SELECT LEVEL, GOLD, QUEST_POINTS FROM {PLAYER_INFO_TABLE_NAME} WHERE PLAYER = ?"
        cur.execute(sql, (player_name,))
        row = cur.fetchone()

        if row is None:
            await ctx.reply(f"No player named `{player_name}` found.")
            return

        level = row["LEVEL"]
        gold = row["GOLD"]
        quest_points = row["QUEST_POINTS"]

        embed = discord.Embed(
            title=f"{player_name}",
            color=discord.Color.blue()
        )
        embed.add_field(name="Level", value=str(level), inline=True)
        embed.add_field(name="Gold", value=str(gold), inline=True)
        embed.add_field(name="QP", value=str(quest_points), inline=True)

        if type == "GM":
            channel = self.bot.get_channel(DM_HUSH_HUT)
            await channel.send(embed=embed)
        else:
            await ctx.author.send(embed=embed)
            await ctx.reply("I've sent your info in a DM!")

        cur.close()
        conn.close()

    @commands.command()
    @commands.has_role(GM_ROLE)
    async def addGold(self, ctx, player_name: str, amount: int):
        '''Add gold to a player's total. GM only.'''
        conn = self.get_db_connection(PLAYER_INFO_PATH)
        cur = conn.cursor()

        cur.execute(f"SELECT GOLD FROM {PLAYER_INFO_TABLE_NAME} WHERE PLAYER = ?", (player_name,))
        row = cur.fetchone()

        if not row:
            await ctx.reply(f"Player `{player_name}` not found.")
            conn.close()
            return

        new_gold = row[0] + amount
        cur.execute(f"UPDATE {PLAYER_INFO_TABLE_NAME} SET GOLD = ? WHERE PLAYER = ?", (new_gold, player_name))
        conn.commit()
        conn.close()

        await ctx.reply(f"Gave {amount} gold to {player_name}.")

    @commands.command()
    @commands.has_role(GM_ROLE)
    async def rmGold(self, ctx, player_name: str, amount: int):
        '''Remove gold from a player's total. GM only.'''
        conn = self.get_db_connection(PLAYER_INFO_PATH)
        cur = conn.cursor()

        cur.execute(f"SELECT GOLD FROM {PLAYER_INFO_TABLE_NAME} WHERE PLAYER = ?", (player_name,))
        row = cur.fetchone()

        if not row:
            await ctx.reply(f"Player `{player_name}` not found.")
            conn.close()
            return

        new_gold = row[0] - amount
        if new_gold < 0:
            await ctx.reply(f"Cannot remove more than {amount} gold from {player_name}.")
            conn.close()
            return
        cur.execute(f"UPDATE {PLAYER_INFO_TABLE_NAME} SET GOLD = ? WHERE PLAYER = ?", (new_gold, player_name))
        conn.commit()
        conn.close()

        await ctx.reply(f"Removed {amount} gold from {player_name}.")

    @commands.command()
    async def giveGold(self, ctx, receiver: str, amount: int):
        '''Trade gold with another player.'''
        conn = self.get_db_connection(PLAYER_INFO_PATH)
        cur = conn.cursor()
        giver = str(ctx.author.display_name)  # the command user’s server name

        # get giver row
        cur.execute(f"SELECT GOLD FROM {PLAYER_INFO_TABLE_NAME} WHERE PLAYER = ?", (giver,))
        giver_row = cur.fetchone()
        if not giver_row:
            await ctx.reply(f"Giver `{giver}` not found in the database.")
            conn.close()
            return

        giver_gold = giver_row[0]

        # get receiver row
        cur.execute(f"SELECT GOLD FROM {PLAYER_INFO_TABLE_NAME} WHERE PLAYER = ?", (receiver,))
        receiver_row = cur.fetchone()
        if not receiver_row:
            await ctx.reply(f"Receiver `{receiver}` not found in the database.")
            conn.close()
            return

        receiver_gold = receiver_row[0]

        # prevent negative
        if giver_gold < amount:
            await ctx.reply(f"❌ You don’t have enough gold to trade {amount}.")
            conn.close()
            return

        # update both
        new_giver_gold = giver_gold - amount
        new_receiver_gold = receiver_gold + amount

        cur.execute(f"UPDATE {PLAYER_INFO_TABLE_NAME} SET GOLD = ? WHERE PLAYER = ?", (new_giver_gold, giver))
        cur.execute(f"UPDATE {PLAYER_INFO_TABLE_NAME} SET GOLD = ? WHERE PLAYER = ?", (new_receiver_gold, receiver))
        conn.commit()
        conn.close()

        await ctx.send(
            f"💰 Trade complete!\n"
            f"- {giver} → {receiver}: {amount} gold\n"
        )


async def setup(bot):
    await bot.add_cog(PlayerInfo(bot))