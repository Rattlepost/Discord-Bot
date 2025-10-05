from discord.ext import commands
import discord
import asyncio
from datetime import datetime, timedelta
from config import GM_ROLE, logging, DETROIT, DATE_FORMAT, THE_CROSSROADS


class AdminCommands(commands.Cog, name="Admin Commands"):
    '''Commands for Admins.'''

    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    @commands.has_role(GM_ROLE)
    async def dta(self, ctx, *, time:str):
        """Post a downtime poll, collect all reactions, DM a summary."""
        await self.run_weekly_job(ctx.author, duration=float(time))
    async def run_weekly_job(self, author, duration: float):
        actions = [
            ("🛠️", "Train a Trade"),
            ("🎲", "Odd Job"),
            ("🔮", "Craft an Item"),
            ("🪙", "Do Your Day Job"),
            ("💞", "Build Relationships"),
        ]

        close_time = (datetime.now(DETROIT) + timedelta(hours=duration)).strftime("%I:%M %p")
        desc_lines = [
            f"This poll will close at {close_time} (Eastern Time).",
            "",
            *[f"{emoji}  —  **{label}**" for emoji, label in actions],
        ]
        description = "\n".join(desc_lines)

        embed = discord.Embed(
            title="Downtime Actions",
            description=description,
            color=0xFF8800,
        )

        channel = self.bot.get_channel(THE_CROSSROADS)
        if channel is None:
            channel = await self.bot.fetch_channel(THE_CROSSROADS)

        poll_message = await channel.send(embed=embed)
        
        for emoji, _ in actions:
            await poll_message.add_reaction(emoji)
        

        # ----- TEST WAIT -----
        await asyncio.sleep(duration*60*60)  # only 10 seconds instead of all day

        try:
            poll_message = await channel.fetch_message(poll_message.id)
        except Exception as e:
            logging.exception("Failed to refetch poll message: %s", e)
            return

        # Map: user_id -> set of (emoji, label)
        user_choices: dict[int, set[tuple[str, str]]] = {}

        for emoji, label in actions:
            react = discord.utils.get(poll_message.reactions, emoji=emoji)
            if not react:
                continue
            try:
                async for user in react.users(limit=None):
                    if getattr(user, "bot", False):
                        continue
                    user_choices.setdefault(user.id, set()).add((emoji, label))
            except Exception as e:
                logging.exception("Error reading users for %s: %s", emoji, e)

        date_str = datetime.now(DETROIT).strftime(DATE_FORMAT)

        # --- 5) Build DM summary (per-option counts + per-user selections) ---
        if not user_choices:
            summary_text = f"No participants reacted today. ({date_str})"
        else:
            # Per-user lines (try to include display name)
            per_user_lines = []
            for uid, choices in user_choices.items():
                # Order their choices by our actions order
                order_index = {e: i for i, (e, _) in enumerate(actions)}
                ordered = sorted(choices, key=lambda x: order_index.get(x[0], 999))
                pretty = ", ".join(f"{e} {l}" for e, l in ordered)

                name = f"<@{uid}>"
                try:
                    member = channel.guild.get_member(uid) or await channel.guild.fetch_member(uid)
                    if member and member.display_name:
                        name = f"<@{uid}>"
                except Exception:
                    pass

                per_user_lines.append(f"- {name}: {pretty}")

            per_user_lines.sort(key=lambda s: s.lower())


            summary_text = "\n".join([
                f"## Downtime Actions for {date_str}",
                "",
                "**Per-user selections:**",
                *per_user_lines
            ])

        # --- 6) DM the summary to the target user ---
        try:
            target_user = await self.bot.fetch_user(author.id)
            await target_user.send(summary_text)
        except discord.Forbidden:
            logging.warning("Cannot DM target user (Forbidden).")
        except Exception as e:
            logging.exception("Failed to DM summary: %s", e)

    

        try:
            await poll_message.delete()
        except discord.Forbidden:
            logging.warning("Bot doesn't have permission to delete the poll message.")
        except Exception as e:
            logging.exception("Failed to delete poll message: %s", e)

        try:
            await channel.send(f"Downtime Actions for {date_str} have closed.")
            await channel.send(f"If you missed them, you will have to wait for next week.")
            
        except Exception as e:
            logging.exception("Failed to send closing notice: %s", e)



async def setup(bot):
    await bot.add_cog(AdminCommands(bot))