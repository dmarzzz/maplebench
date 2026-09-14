# Ordinary buff parser source fixtures

Exact public-source copies from the privately verified production source snapshot.
Journey upstream bc0234fe7c7f53322453e7bdd79564d9aca4cd8b has historical
MapleBench patches through 0016. Client candidate d2fe067 adds 0017–0022;
none changes Buff.h/Buff.cpp/ActiveBuffs or the BuffHandler body here.
The only earlier PlayerHandlers change is the level-byte signedness fix.

SHA256.json pins every copy. Existing upstream license notices are retained.
Cosmic sources are the matching public emulator source used by the isolated
runtime; PacketCreator preserves caller order, and StatEffect establishes the
checked four-toolkit cast order. Other callers are not universally sorted. No game assets, SQL, credentials, recordings or private host config
are included. Tests compile the production handler, packet reader and buff/stat
application methods with inert player/UI collaborators.
