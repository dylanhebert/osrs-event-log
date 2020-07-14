import database.handler as db
import time
import asyncio


class ServerTest:
    def __init__(self,id,name):
        self.id = id
        self.name = name

class MemberTest:
    def __init__(self,id,name):
        self.id = id
        self.name = name


Server1 = ServerTest(12345,"Server 1")
Server2 = ServerTest(56789,"Server 2")
Server3 = ServerTest(98765,"Server 3")
Member1 = MemberTest(1111,"Dylan")
Member2 = MemberTest(2222,"Joseph")
Member3 = MemberTest(3333,"Jeremy")


async def run_test():
    db.verify_files('db_discord.json')
    db.verify_files('db_runescape.json')
    # Add Server 1
    await db.add_server(Server1)
    await db.add_player(Server1, Member3, 'Urbigmad')
    # await db.add_player(Server1, Member2, 'Zumori')
    # await db.add_player(Server1, Member1, 'Red')
    # await db.rename_player(Server1, Member1, 'Green', 'Blue')
    # await db.remove_player(Server1, Member1, 'Green')
    # await db.add_player(Server1, Member1, 'Green')
    # await db.update_server_entry(Server1, 'role', 10101010)
    # await db.update_server_entry(Server1, 'channel', 32323232)
    # await db.update_server_entry(Server1, 'role', None)
    # # Add Server 2
    # await db.add_server(Server2)
    # await db.rename_player(Server2, Member2, 'Zumori', 'Blade')
    # await db.add_player(Server2, Member1, 'Green')
    # await db.add_player(Server2, Member2, 'Zumori')
    # await db.rename_player(Server2, Member2, 'Zumori', 'Blade')
    # await db.remove_player(Server1, Member1, 'Green')
    # await db.remove_player(Server1, Member1, 'Blue')
    # await db.add_player(Server2, Member2, 'Green')
    # await db.remove_player(Server1, Member1, 'Zumori')
    # await db.add_player(Server1, Member2, 'Beyond+Honor')
    # await db.add_player(Server2, Member2, 'Beyond+Honor')
    # await db.add_player(Server1, Member3, 'Wyskie')
    # await db.add_player(Server2, Member3, 'Wyskie')
    # await db.add_player(Server2, Member3, 'HarryBoy')

    # await db.remove_player(Server2, Member3, 'Wyski')
    # await db.remove_player(Server2, Member3, 'Wyskie')
    # await db.remove_player(Server2, Member3, 'Wyskie')
    # await db.rename_player(Server2, Member1, 'Green', 'Blue')
    # await db.add_player(Server2, Member1, 'Yellow')

    # await db.remove_server(Server1)

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    task = loop.create_task(run_test())
    loop.run_until_complete(task)
    loop.close()
    print("Done!")