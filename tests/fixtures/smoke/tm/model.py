"""pytm model for the smoke fixture: one actor, one server, one datastore, two flows."""
from pytm import TM, Actor, Boundary, Dataflow, Datastore, Server

tm = TM("smoke")
tm.description = "MOADIX confined-engine smoke fixture"
internet = Boundary("Internet")
user = Actor("User")
user.inBoundary = internet
web = Server("Web")
db = Datastore("Store")
Dataflow(user, web, "request")
Dataflow(web, db, "write")
tm.process()
