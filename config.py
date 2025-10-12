import logging
from zoneinfo import ZoneInfo

# config.py

# Time and Date
DETROIT = ZoneInfo("America/Detroit")
DATE_FORMAT = "%m-%d-%Y"


# SQLite
DATABASE_PATH = "database.db"

PLAYER_INFO_TABLE = "player_info"
QUEST_BOARD_TABLE = "quest_board"



# Users
ZIREN1236 = 314500928290160640
RATTLEPOST = 499200328399323186


# Roles
GM_ROLE = 1424088644821454848
LAB_MANIAC = 1424290214599196722


# Channels
THE_CROSSROADS = 1420451034639110278
THE_LAB = 1422696917464256655
DM_HUSH_HUT = 1424222020060577842


# Logging
handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')
