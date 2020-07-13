from dao import DataHandler
import time


class ServerTest:
    def __init__(self,id,name):
        self.id = id
        self.name = name

class MemberTest:
    def __init__(self,id,name):
        self.id = id
        self.name = name


Handler = DataHandler()
Server1 = ServerTest(12345,"Server 1")
Server2 = ServerTest(56789,"Server 2")
Server3 = ServerTest(98765,"Server 3")
Member1 = MemberTest(1111,"Dylan")
Member2 = MemberTest(2222,"Joseph")
Member3 = MemberTest(3333,"Harrison")

Handler.verify_files('db_discord.json')
Handler.verify_files('db_runescape.json')

# Add Server 1
Handler.add_server(Server1)
Handler.add_player(Server1, Member1, 'Green')
Handler.add_player(Server1, Member2, 'Zumori')
Handler.add_player(Server1, Member1, 'Red')
Handler.rename_player(Server1, Member1, 'Green', 'Blue')
Handler.add_player(Server1, Member1, 'Green')
# Add Server 2
Handler.add_server(Server2)
Handler.rename_player(Server2, Member2, 'Zumori', 'Blade')
Handler.add_player(Server2, Member1, 'Green')
Handler.add_player(Server2, Member2, 'Zumori')
Handler.rename_player(Server2, Member2, 'Zumori', 'Blade')
Handler.remove_player(Server1, Member1, 'Green')
Handler.remove_player(Server1, Member1, 'Blue')
Handler.add_player(Server2, Member2, 'Green')
Handler.remove_player(Server1, Member1, 'Zumori')
Handler.add_player(Server1, Member2, 'Beyond+Honor')
Handler.add_player(Server2, Member2, 'Beyond+Honor')
Handler.add_player(Server1, Member3, 'Wyskie')
Handler.add_player(Server2, Member3, 'Wyskie')
Handler.add_player(Server2, Member3, 'HarryBoy')

Handler.remove_player(Server2, Member3, 'Wyski')
Handler.remove_player(Server2, Member3, 'Wyskie')
Handler.remove_player(Server2, Member3, 'Wyskie')
Handler.rename_player(Server2, Member1, 'Green', 'Blue')
Handler.add_player(Server2, Member1, 'Yellow')

Handler.remove_server(Server1)