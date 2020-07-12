from dao import DataHandler


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
Member1 = MemberTest(1111,"Green Donut")
Member2 = MemberTest(2222,"Joseph")

Handler.verify_files('db_discord.json')
Handler.verify_files('db_runescape.json')
Handler.add_server(Server1)
Handler.add_player(Server1, Member1, 'Green+Donut')
Handler.add_player(Server1, Member1, 'Verde+Donut')
Handler.add_server(Server2)
Handler.add_player(Server2, Member2, 'Zumori')
Handler.add_player(Server2, Member1, 'Green+Donut')
Handler.add_player(Server1, Member2, 'Beyond+Honor')
Handler.add_player(Server1, Member1, 'Third+Donut')
Handler.add_player(Server2, Member1, 'Third+Donut')
Handler.add_player(Server1, Member2, 'Zumori')
Handler.add_server(Server3)
Handler.add_player(Server3, Member1, 'Green+Donut')